import path from "path";
import { ApplicationState, AgentUiMode } from "./states.js";
import { launchBrowser, screenshot, closeExtraPages } from "./browser.js";
import {
  openGlassdoorSearch,
  listResultCards,
  openResultCard,
  extractJobFromPage,
  clickApply,
} from "./glassdoor/search.js";
import { resolveAdapter, AtsType } from "./ats/index.js";
import { RISK } from "./policy.js";
import { humanDelay, loadAgentConfig, envConfig, resolveSearchUrl } from "./config.js";

function splitName(fullName = "") {
  const parts = String(fullName).trim().split(/\s+/);
  return {
    firstName: parts[0] || "",
    lastName: parts.slice(1).join(" ") || "",
    fullName: String(fullName).trim(),
  };
}

function packageResumePath(pkg) {
  if (!pkg) return null;
  const folder = pkg.folder || pkg.folderPath || pkg.absolutePath || null;
  const files = pkg.files || [];
  const hasPdf = files.includes("resume.pdf");
  const hasDocx = files.includes("resume.docx");
  const name = hasPdf ? "resume.pdf" : hasDocx ? "resume.docx" : null;
  if (folder && name) return path.join(folder, name);
  if (pkg.resumePdfPath) return pkg.resumePdfPath;
  if (pkg.folderName) {
    const root =
      process.env.GENERATED_APPLICATIONS_DIR ||
      path.join(envConfig().profileDir, "..", "..", "..", "generated-applications");
    return path.join(root, pkg.folderName, "resume.pdf");
  }
  return null;
}

/**
 * Main Glassdoor → score → apply runner.
 */
export function createRunner({ api, events, inputBroker }) {
  let context = null;
  let running = false;
  let abortRequested = false;
  let pauseRequested = false;
  let userControl = false;
  let state = ApplicationState.IDLE;
  let uiMode = AgentUiMode.IDLE;
  let currentJob = null;
  let currentRun = null;

  async function setState(next, message, extra = {}) {
    state = next;
    await events.emit("STATE_CHANGED", {
      state: next,
      uiMode,
      message: message || next,
      currentJob,
      ...extra,
    });
    if (currentRun?.runId) {
      await api.patchRun(currentRun.runId, {
        state: next,
        uiMode,
        currentJob,
      }).catch(() => {});
    }
  }

  async function setUiMode(mode) {
    uiMode = mode;
  }

  function resolveSubmissionPending(action) {
    const pending = inputBroker.listPending();
    const sub = pending.find((p) => p.kind === "SUBMISSION_APPROVAL");
    if (sub?.requestId) {
      inputBroker.resolve(sub.requestId, { action, value: action });
      return true;
    }
    return false;
  }

  function controls() {
    return {
      pauseAfterAction: () => {
        pauseRequested = true;
      },
      pauseNow: async () => {
        pauseRequested = true;
        await setUiMode(AgentUiMode.PAUSED_BY_USER);
        await setState(ApplicationState.PAUSED_BY_USER, "Paused by user");
      },
      resume: async () => {
        pauseRequested = false;
        userControl = false;
        await setUiMode(AgentUiMode.ACTING);
        await events.emit("ACTION_COMPLETED", { message: "Resumed by user" });
      },
      takeControl: async () => {
        userControl = true;
        pauseRequested = true;
        await setUiMode(AgentUiMode.PAUSED_BY_USER);
        await setState(ApplicationState.PAUSED_BY_USER, "User took browser control");
      },
      returnControl: async () => {
        userControl = false;
        pauseRequested = false;
        await setUiMode(AgentUiMode.OBSERVING);
        await events.emit("ACTION_COMPLETED", {
          message: "Control returned to agent — rescanning page",
        });
      },
      abort: async () => {
        abortRequested = true;
        inputBroker.clearAll("Aborted");
      },
      skipJob: async () => {
        if (!resolveSubmissionPending("SKIP")) {
          inputBroker.clearAll("Skipped");
        }
      },
      approveSubmit: async () => {
        resolveSubmissionPending("SUBMIT");
      },
      rejectSubmit: async () => {
        resolveSubmissionPending("SKIP");
      },
    };
  }

  async function waitIfPaused() {
    while ((pauseRequested || userControl) && !abortRequested) {
      await new Promise((r) => setTimeout(r, 400));
    }
  }

  async function askUser(questionSpec) {
    await setUiMode(AgentUiMode.AWAITING_USER_INPUT);
    await setState(ApplicationState.AWAITING_USER_INPUT, questionSpec.question);
    const requestId = questionSpec.requestId || `req_${Date.now()}`;
    await events.emit("USER_INPUT_REQUIRED", {
      requestId,
      question: questionSpec.question,
      options: questionSpec.options,
      riskLevel: questionSpec.riskLevel || RISK.MEDIUM,
      fieldType: questionSpec.fieldType,
      kind: questionSpec.kind,
      reviewSummary: questionSpec.reviewSummary,
    });
    const answer = await inputBroker.request({ ...questionSpec, requestId });
    await setUiMode(AgentUiMode.ACTING);
    return answer;
  }

  async function awaitSubmissionApproval(summary) {
    await setUiMode(AgentUiMode.AWAITING_SUBMISSION_APPROVAL);
    await setState(ApplicationState.AWAITING_REVIEW, "Awaiting submission approval", {
      reviewSummary: summary,
    });
    const answer = await askUser({
      question: "Approve final submission?",
      options: ["Submit", "Skip application"],
      riskLevel: RISK.HIGH,
      kind: "SUBMISSION_APPROVAL",
      reviewSummary: summary,
    });
    if (answer?.action === "SUBMIT" || answer?.value === "Submit") {
      return { action: "SUBMIT" };
    }
    return { action: "SKIP" };
  }

  async function processCard(page, card, cfg, profile, stats) {
    await waitIfPaused();
    if (abortRequested) return;

    await setUiMode(AgentUiMode.ACTING);
    await openResultCard(page, card, cfg);
    await screenshot(page, "job_opened");

    await setUiMode(AgentUiMode.OBSERVING);
    const extracted = await extractJobFromPage(page);
    currentJob = {
      title: extracted.title,
      company: extracted.company,
      location: extracted.location,
      sourceUrl: extracted.sourceUrl,
    };
    await setState(ApplicationState.JOB_EXTRACTED, `Found: ${extracted.title} — ${extracted.company}`);

    stats.resultsViewed += 1;

    await setUiMode(AgentUiMode.DECIDING);
    const ingest = await api.ingestGlassdoorJob({
      title: extracted.title,
      company: extracted.company,
      location: extracted.location,
      salary: extracted.salary,
      descriptionRaw: extracted.description,
      sourceUrl: extracted.sourceUrl,
      canonicalApplyUrl: extracted.applicationUrl || extracted.sourceUrl,
      sourceJobId: extracted.sourceJobId,
      analyze: true,
    });

    const job = ingest.job;
    const created = ingest.created;
    currentJob = {
      ...currentJob,
      jobId: job._id,
      match: ingest.match || null,
    };

    await setState(
      ApplicationState.DUPLICATE_CHECKED,
      created
        ? "New job upserted"
        : `Duplicate / existing (${ingest.reason || "existing"})`
    );

    if (job.applicationStatus === "pending" || job.applicationStatus === "apply") {
      await events.emit("DECISION_MADE", {
        decision: "SKIP",
        reason: `Already tracked as ${job.applicationStatus}`,
        confidence: 1,
      });
      return;
    }

    let match = ingest.match;
    if (!match && job._id) {
      try {
        match = await api.analyzeJob(job._id);
      } catch (err) {
        await events.emit("ERROR", {
          message: `Analyze failed: ${err.message}`,
          recoverable: true,
        });
        return;
      }
    }

    const overall = match?.score ?? match?.overallScore ?? 0;
    const recommendation = match?.recommendation || "skip";
    await setState(ApplicationState.SCORED, `Match score: ${overall}/100`, {
      score: overall,
      recommendation,
    });
    await events.emit("DECISION_MADE", {
      decision:
        overall >= cfg.minimumScore && recommendation !== "reject"
          ? "APPLY"
          : "SKIP",
      reason: match?.summary || recommendation,
      confidence: match?.confidence ?? 0.7,
      evidence: match?.strongMatches?.slice?.(0, 5) || [],
      concerns: match?.meaningfulGaps?.slice?.(0, 5) || [],
      score: overall,
    });

    if (overall < cfg.minimumScore || recommendation === "reject" || recommendation === "skip") {
      await setState(ApplicationState.REJECTED_BY_POLICY, "Below apply threshold");
      return;
    }

    if (stats.applicationsStarted >= cfg.maxApplicationsPerRun) {
      await events.emit("DECISION_MADE", {
        decision: "SKIP",
        reason: "maxApplicationsPerRun reached",
        confidence: 1,
      });
      return;
    }

    await setState(ApplicationState.DOCUMENTS_GENERATING, "Generating application package");
    await setUiMode(AgentUiMode.ACTING);
    let pkg;
    try {
      pkg = await api.generatePackage(job._id);
    } catch (err) {
      await events.emit("ERROR", {
        message: `Package generation failed: ${err.message}`,
        recoverable: true,
      });
      await setState(ApplicationState.FAILED, err.message);
      return;
    }

    const resumePath = packageResumePath(pkg);
    stats.applicationsStarted += 1;

    await setState(ApplicationState.APPLICATION_STARTED, "Clicking Apply");
    let applyPage;
    try {
      applyPage = await clickApply(page, context, cfg, events);
    } catch (err) {
      // Try direct application URL if Glassdoor apply failed.
      if (extracted.applicationUrl) {
        applyPage = await context.newPage();
        await applyPage.goto(extracted.applicationUrl, {
          waitUntil: "domcontentloaded",
          timeout: 60000,
        });
      } else {
        await events.emit("ERROR", {
          message: `Apply failed: ${err.message}`,
          recoverable: true,
        });
        await setState(ApplicationState.BLOCKED, err.message);
        return;
      }
    }

    // CAPTCHA / challenge pause
    const bodyText = await applyPage.locator("body").innerText().catch(() => "");
    if (/captcha|verify you are human|unusual traffic/i.test(bodyText)) {
      await setState(ApplicationState.BLOCKED, "CAPTCHA requires manual completion");
      await askUser({
        question: "A CAPTCHA requires manual completion. Complete it in the browser, then Resume.",
        options: ["Resume", "Skip application"],
        riskLevel: RISK.HIGH,
        kind: "CAPTCHA",
      });
    }

    const { atsType, adapter } = await resolveAdapter(applyPage);
    await events.emit("ACTION_COMPLETED", {
      message: `Detected ATS: ${atsType}`,
      atsType,
      pageUrl: applyPage.url(),
    });

    if (atsType === AtsType.WORKDAY) {
      await setState(
        ApplicationState.BLOCKED,
        "Workday adapter deferred — skipping"
      );
      await events.emit("DECISION_MADE", {
        decision: "SKIP",
        reason: "Workday not supported in MVP",
        confidence: 1,
      });
      if (applyPage !== page) await applyPage.close().catch(() => {});
      return;
    }

    await adapter.begin(applyPage, { cfg, events });
    await setState(ApplicationState.FORM_FILLING, "Filling application form");

    const fillCtx = {
      profile,
      resumePath,
      events,
      cfg,
    };
    const { unknowns } = await adapter.fill(applyPage, fillCtx);

    const toAsk = (unknowns || []).filter(
      (u) =>
        u.action === "ASK_USER" &&
        (u.risk === RISK.LEGAL ||
          u.risk === RISK.HIGH ||
          u.risk === RISK.MEDIUM ||
          (u.confidence ?? 0) < 0.7)
    );

    // Cap interactive prompts per job for MVP.
    for (const q of toAsk.slice(0, 5)) {
      const answer = await askUser({
        question: q.question,
        options: q.options?.length ? q.options : undefined,
        riskLevel: q.risk,
        fieldType: q.fieldType,
      });
      if (answer?.value && q.name) {
        // Best-effort: fill by name if still on page.
        try {
          const safeName = String(q.name).replace(/"/g, '\\"');
          const loc = applyPage.locator(`[name="${safeName}"]`);
          if ((await loc.count()) > 0) {
            await loc.first().fill(String(answer.value));
          }
        } catch {
          /* ignore */
        }
      }
      if (answer?.reusePolicy && answer?.value) {
        await api
          .saveAnswer({
            normalizedQuestion: q.question.slice(0, 200).toLowerCase(),
            answer: answer.value,
            answerType: "TEXT",
            source: "USER_CONFIRMED",
            riskLevel: q.risk,
            allowedForAutofill: answer.reusePolicy !== "ONCE",
            reusePolicy: answer.reusePolicy,
          })
          .catch(() => {});
      }
      if (answer?.action === "SKIP" || answer?.value === "Skip application") {
        if (applyPage !== page) await applyPage.close().catch(() => {});
        return;
      }
    }

    const reviewSummary = {
      company: extracted.company,
      role: extracted.title,
      score: overall,
      atsType,
      resumePath: resumePath ? path.basename(resumePath) : null,
      pageUrl: applyPage.url(),
      unknownCount: toAsk.length,
    };

    const decision = cfg.requireApprovalBeforeSubmit
      ? await awaitSubmissionApproval(reviewSummary)
      : { action: "SUBMIT" };

    if (!decision || decision.action !== "SUBMIT") {
      await events.emit("DECISION_MADE", {
        decision: "SKIP",
        reason: "User skipped submission",
        confidence: 1,
      });
      if (applyPage !== page) await applyPage.close().catch(() => {});
      await setState(ApplicationState.RETURNING_TO_RESULTS, "Returning to results");
      return;
    }

    await setState(ApplicationState.SUBMITTING, "Submitting application");
    await setUiMode(AgentUiMode.ACTING);
    let confirmation;
    try {
      confirmation = await adapter.submit(applyPage, fillCtx);
    } catch (err) {
      await setState(ApplicationState.SUBMISSION_UNCERTAIN, err.message);
      await events.emit("ERROR", {
        message: err.message,
        recoverable: false,
      });
      return;
    }

    if (confirmation.submissionStatus === "CONFIRMED") {
      await setState(ApplicationState.SUBMISSION_CONFIRMED, "Submission confirmed");
      await api.setApplicationStatus(job._id, "pending", "Submitted via apply agent");
      stats.applicationsSubmitted += 1;
    } else {
      await setState(
        ApplicationState.SUBMISSION_UNCERTAIN,
        "Submission uncertain — not retrying"
      );
      await api.setApplicationStatus(
        job._id,
        "pending",
        "Submit clicked; confirmation uncertain"
      );
    }

    await events.emit("ACTION_COMPLETED", {
      message: "Application flow finished",
      confirmation,
    });

    if (applyPage !== page) {
      await applyPage.close().catch(() => {});
    }
    await setState(ApplicationState.RETURNING_TO_RESULTS, "Returning to Glassdoor results");
  }

  async function start(overrides = {}) {
    if (running) throw new Error("A run is already in progress");
    running = true;
    abortRequested = false;
    pauseRequested = false;
    userControl = false;
    currentJob = null;

    const cfg = { ...(await loadAgentConfig()), ...overrides };
    const startedAt = Date.now();
    const deadline = startedAt + cfg.maxRuntimeMinutes * 60 * 1000;

    try {
      await setUiMode(AgentUiMode.ACTING);
      const candidate = await api.getCandidate();
      const names = splitName(candidate.name || "");
      const profile = {
        ...names,
        email: candidate.email || "",
        phone: candidate.phone || "",
        location: candidate.location || "",
        linkedin: candidate.linkedin || "",
        github: candidate.github || "",
      };

      const run = await api.createRun({
        source: "glassdoor",
        query: cfg.query,
        location: cfg.location,
        searchUrl: resolveSearchUrl(cfg) || null,
        config: {
          maxResultsPerRun: cfg.maxResultsPerRun,
          maxApplicationsPerRun: cfg.maxApplicationsPerRun,
          minimumScore: cfg.minimumScore,
          requireApprovalBeforeSubmit: cfg.requireApprovalBeforeSubmit,
          preferRemote: Boolean(cfg.preferRemote),
          searchUrl: cfg.searchUrl || null,
          searchUrlRemote: cfg.searchUrlRemote || null,
        },
        state: ApplicationState.GLASSDOOR_SEARCHING,
      });
      currentRun = { runId: run._id };
      events.setRunId(run._id);

      context = await launchBrowser({
        headless: envConfig().headless,
        slowMoMs: cfg.slowMoMs,
        profileDir: envConfig().profileDir,
      });
      const page = context.pages()[0] || (await context.newPage());

      await setState(ApplicationState.GLASSDOOR_SEARCHING, "Opening Glassdoor search");
      await openGlassdoorSearch(page, cfg, events);
      await screenshot(page, "search_results");

      const cards = await listResultCards(page, cfg.maxResultsPerRun);
      await events.emit("ACTION_COMPLETED", {
        message: `Found ${cards.length} result card(s)`,
      });

      const stats = {
        resultsViewed: 0,
        jobsExtracted: 0,
        applicationsStarted: 0,
        applicationsSubmitted: 0,
      };

      for (const card of cards) {
        if (abortRequested || Date.now() > deadline) break;
        await waitIfPaused();
        // Prefer keeping results tab: if we navigated away, go back via history or search URL.
        if (!/glassdoor\.com/i.test(page.url()) || !/job/i.test(page.url())) {
          await openGlassdoorSearch(page, cfg, events);
        }
        try {
          await processCard(page, card, cfg, profile, stats);
          stats.jobsExtracted += 1;
        } catch (err) {
          await events.emit("ERROR", {
            message: err.message || String(err),
            recoverable: true,
          });
          await setState(ApplicationState.FAILED, err.message);
        }
        await closeExtraPages(context, page);
        await humanDelay(cfg);
      }

      await api.patchRun(run._id, {
        state: ApplicationState.COMPLETED,
        finishedAt: new Date().toISOString(),
        resultsViewed: stats.resultsViewed,
        jobsExtracted: stats.jobsExtracted,
        applicationsSubmitted: stats.applicationsSubmitted,
      });
      await setUiMode(AgentUiMode.COMPLETED);
      await setState(ApplicationState.COMPLETED, "Run complete", { stats });
      return { runId: run._id, stats };
    } catch (err) {
      await setUiMode(AgentUiMode.FAILED);
      await setState(ApplicationState.FAILED, err.message || String(err));
      if (currentRun?.runId) {
        await api
          .patchRun(currentRun.runId, {
            state: ApplicationState.FAILED,
            error: err.message || String(err),
            finishedAt: new Date().toISOString(),
          })
          .catch(() => {});
      }
      throw err;
    } finally {
      running = false;
      if (context) {
        // Keep persistent profile; close browser to free resources after run.
        await context.close().catch(() => {});
        context = null;
      }
    }
  }

  function getStatus() {
    return {
      running,
      state,
      uiMode,
      currentJob,
      runId: currentRun?.runId || events.getRunId(),
      pendingInputs: inputBroker.listPending(),
      pauseRequested,
      userControl,
      abortRequested,
    };
  }

  return {
    start,
    getStatus,
    controls: controls(),
    resolveInput: (requestId, answer) => inputBroker.resolve(requestId, answer),
  };
}
