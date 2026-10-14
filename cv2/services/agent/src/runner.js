import fs from "fs";
import path from "path";
import { ApplicationState, AgentUiMode } from "./states.js";
import {
  launchBrowser,
  screenshot,
  closeExtraPages,
  canUseHeadedDisplay,
  pageLooksLikeBotChallenge,
  resolveBrowserMode,
  resolveBrowserEngine,
  resolveCdpEndpoint,
} from "./browser.js";
import {
  openGlassdoorSearch,
  listResultCards,
  openResultCard,
  extractJobFromPage,
  scrollJobDescription,
  clickApply,
} from "./glassdoor/search.js";
import { resolveAdapter, AtsType } from "./ats/index.js";
import {
  RISK,
  QUESTION_ACTION,
  isAlreadyAppliedStatus,
} from "./policy.js";
import {
  humanDelay,
  loadAgentConfig,
  envConfig,
  resolveSearchUrl,
  normalizeApplyMode,
  isCompanyApplyMode,
  isEasyApplyMode,
  APPLY_MODE_META,
} from "./config.js";
import { createHumanTakeover } from "./humanTakeover.js";

function splitName(fullName = "") {
  const parts = String(fullName).trim().split(/\s+/);
  return {
    firstName: parts[0] || "",
    lastName: parts.slice(1).join(" ") || "",
    fullName: String(fullName).trim(),
  };
}

function packageFolder(pkg) {
  if (!pkg) return null;
  if (pkg.folder || pkg.folderPath || pkg.absolutePath) {
    return pkg.folder || pkg.folderPath || pkg.absolutePath;
  }
  if (pkg.folderName) {
    const root =
      process.env.GENERATED_APPLICATIONS_DIR ||
      path.join(envConfig().profileDir, "..", "..", "..", "generated-applications");
    return path.join(root, pkg.folderName);
  }
  return null;
}

function packageResumePath(pkg) {
  if (!pkg) return null;
  const folder = packageFolder(pkg);
  const files = pkg.files || [];
  const hasPdf = files.includes("resume.pdf");
  const hasDocx = files.includes("resume.docx");
  const name = hasPdf ? "resume.pdf" : hasDocx ? "resume.docx" : null;
  if (folder && name) return path.join(folder, name);
  if (pkg.resumePdfPath) return pkg.resumePdfPath;
  return null;
}

/**
 * Cover letter artifacts from generate-package (Ollama or OpenAI via documentProvider).
 */
function packageCoverLetter(pkg) {
  if (!pkg) return { pdfPath: null, docxPath: null, text: "" };
  const folder = packageFolder(pkg);
  const files = pkg.files || [];
  const pdfPath =
    folder && files.includes("cover-letter.pdf")
      ? path.join(folder, "cover-letter.pdf")
      : null;
  const docxPath =
    folder && files.includes("cover-letter.docx")
      ? path.join(folder, "cover-letter.docx")
      : null;
  let text = String(pkg.previews?.coverLetter?.content || "").trim();
  if (!text && folder) {
    const txtPath = path.join(folder, "cover-letter.txt");
    try {
      if (fs.existsSync(txtPath)) {
        text = fs.readFileSync(txtPath, "utf8").trim();
      }
    } catch {
      /* ignore */
    }
  }
  return { pdfPath, docxPath, text };
}

/**
 * Main Glassdoor → score → apply runner.
 */
export function createRunner({ api, events, inputBroker, preview }) {
  let browserHandle = null;
  let context = null;
  let running = false;
  let abortRequested = false;
  let pauseRequested = false;
  let userControl = false;
  let state = ApplicationState.IDLE;
  let uiMode = AgentUiMode.IDLE;
  let currentJob = null;
  let currentRun = null;
  let activePageUrl = null;
  let headed = !envConfig().headless;
  let activePage = null;
  let applyMode = "easyApplyLocal";
  let browserMode = resolveBrowserMode();
  let cdpEndpoint = null;

  const humanTakeover = createHumanTakeover({
    getUiMode: () => uiMode,
    getUserControl: () => userControl,
    onTakeover: async (payload) => {
      if (userControl) return;
      userControl = true;
      pauseRequested = true;
      await setUiMode(AgentUiMode.PAUSED_BY_USER);
      await setState(
        ApplicationState.PAUSED_BY_USER,
        "You took control — agent paused"
      );
      await events.emit("HUMAN_TAKEOVER", {
        message: "You took control — agent paused",
        kind: payload?.kind || "interaction",
      });
    },
  });

  async function focusPreview(page) {
    if (!page) return;
    activePage = page;
    try {
      activePageUrl = page.url();
    } catch {
      activePageUrl = null;
    }
    if (preview) {
      await preview.setActivePage(page).catch((err) => {
        console.error("preview setActivePage failed:", err.message || err);
      });
    }
  }

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
    humanTakeover.noteUiMode(mode);
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
        await events.emit("HUMAN_TAKEOVER", {
          message: "You took control — agent paused",
          kind: "button",
        });
      },
      returnControl: async () => {
        userControl = false;
        pauseRequested = false;
        await setUiMode(AgentUiMode.OBSERVING);
        await events.emit("ACTION_COMPLETED", {
          message: "Control returned to agent — rescanning page",
        });
      },
      focusWindow: async () => {
        const page = activePage;
        if (!page || page.isClosed()) {
          throw new Error("No active browser page to focus");
        }
        await page.bringToFront();
        return { ok: true, headed };
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

  async function waitForHumanChallenge(page, contextLabel = "page") {
    if (!(await pageLooksLikeBotChallenge(page))) return false;
    await setState(
      ApplicationState.BLOCKED,
      `Bot challenge on ${contextLabel} — complete Verify you are human in the browser window`
    );
    await events.emit("ACTION_COMPLETED", {
      message: `Cloudflare / bot challenge detected on ${contextLabel} — waiting for you`,
      pageUrl: page.url(),
    });
    const answer = await askUser({
      question:
        "Glassdoor/Cloudflare is asking to verify you are human. Complete the checkbox in the Chrome window (same profile as the agent), then choose Resume.",
      options: ["Resume", "Skip / abort wait"],
      riskLevel: RISK.HIGH,
      kind: "CAPTCHA",
    });
    if (
      answer?.action === "SKIP" ||
      /skip|abort/i.test(String(answer?.value || ""))
    ) {
      return true;
    }
    await new Promise((r) => setTimeout(r, 1500));
    if (await pageLooksLikeBotChallenge(page)) {
      await events.emit("ACTION_COMPLETED", {
        message:
          "Challenge may still be visible — continuing; use Take control if needed",
        pageUrl: page.url(),
      });
    }
    return false;
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
    await focusPreview(page);
    if (await waitForHumanChallenge(page, "job listing")) {
      return;
    }
    await scrollJobDescription(page);
    await screenshot(page, "job_opened");

    await setUiMode(AgentUiMode.OBSERVING);
    const extracted = await extractJobFromPage(page);
    currentJob = {
      title: extracted.title,
      company: extracted.company,
      location: extracted.location,
      sourceUrl: extracted.sourceUrl,
      easyApply: Boolean(extracted.easyApply),
      applicationStatus: null,
    };
    await setState(
      ApplicationState.JOB_EXTRACTED,
      `Found: ${extracted.title} — ${extracted.company}`
    );

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
    const priorStatus = job.applicationStatus || null;
    currentJob = {
      ...currentJob,
      jobId: job._id,
      match: ingest.match || null,
      applicationStatus: priorStatus,
    };

    await setState(
      ApplicationState.DUPLICATE_CHECKED,
      created
        ? "New job upserted"
        : `Duplicate / existing (${ingest.reason || "existing"})`
    );

    if (isAlreadyAppliedStatus(priorStatus)) {
      await events.emit("DECISION_MADE", {
        decision: "SKIP",
        reason: "already_applied",
        message: `Already applied / tracked as ${priorStatus}`,
        confidence: 1,
        applicationStatus: priorStatus,
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

    if (
      overall < cfg.minimumScore ||
      recommendation === "reject" ||
      recommendation === "skip"
    ) {
      await setState(
        ApplicationState.REJECTED_BY_POLICY,
        "Below apply threshold"
      );
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

    await setState(
      ApplicationState.DOCUMENTS_GENERATING,
      "Generating application package"
    );
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
    const coverLetter = packageCoverLetter(pkg);
    stats.applicationsStarted += 1;

    await setState(ApplicationState.APPLICATION_STARTED, "Clicking Easy Apply");
    let applyPage;
    try {
      applyPage = await clickApply(page, context, cfg, events);
    } catch (err) {
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
    await focusPreview(applyPage);

    if (await waitForHumanChallenge(applyPage, "apply form")) {
      if (applyPage !== page) await applyPage.close().catch(() => {});
      await focusPreview(page);
      return;
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
      await focusPreview(page);
      return;
    }

    await adapter.begin(applyPage, { cfg, events });
    await setState(ApplicationState.FORM_FILLING, "Filling application form");

    const fillCtx = {
      profile,
      resumePath,
      coverLetter,
      events,
      cfg,
    };
    const { unknowns } = await adapter.fill(applyPage, fillCtx);

    // Auto-Yes tech questions that adapters surfaced (non-Indeed paths)
    for (const q of unknowns || []) {
      if (q.action !== QUESTION_ACTION.AUTO_YES) continue;
      await events.emit("DECISION_MADE", {
        decision: "AUTO_YES",
        reason: "tech_default_yes",
        message: `Answered Yes: ${(q.question || "").slice(0, 120)}`,
        confidence: q.confidence ?? 0.9,
      });
      try {
        if (q.name) {
          const safeName = String(q.name).replace(/"/g, '\\"');
          const loc = applyPage.locator(
            `[name="${safeName}"][value="Yes"], [name="${safeName}"][value="yes"]`
          );
          if ((await loc.count()) > 0) await loc.first().check({ force: true });
        }
      } catch {
        /* ignore */
      }
    }

    const toAsk = (unknowns || []).filter(
      (u) =>
        u.action === QUESTION_ACTION.ASK_USER &&
        (u.risk === RISK.LEGAL ||
          u.risk === RISK.HIGH ||
          u.risk === RISK.MEDIUM ||
          (u.confidence ?? 0) < 0.7)
    );

    for (const q of toAsk.slice(0, 5)) {
      const answer = await askUser({
        question: q.question,
        options: q.options?.length ? q.options : undefined,
        riskLevel: q.risk,
        fieldType: q.fieldType,
      });
      if (answer?.value && q.name) {
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
        await focusPreview(page);
        return;
      }
    }

    const reviewSummary = {
      company: extracted.company,
      role: extracted.title,
      score: overall,
      atsType,
      applyMode: cfg.applyMode,
      easyApply: Boolean(extracted.easyApply),
      latestRole: profile.latestRole
        ? `${profile.latestRole.title} @ ${profile.latestRole.company}`
        : null,
      resumePath: resumePath ? path.basename(resumePath) : null,
      coverLetter: Boolean(coverLetter?.text || coverLetter?.pdfPath),
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
      await focusPreview(page);
      await setState(
        ApplicationState.RETURNING_TO_RESULTS,
        "Returning to results"
      );
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
      await setState(
        ApplicationState.SUBMISSION_CONFIRMED,
        "Submission confirmed"
      );
      await api.setApplicationStatus(
        job._id,
        "pending",
        "Submitted via apply agent"
      );
      currentJob = { ...currentJob, applicationStatus: "pending" };
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
      currentJob = { ...currentJob, applicationStatus: "pending" };
    }

    await events.emit("ACTION_COMPLETED", {
      message: "Application flow finished",
      confirmation,
    });

    if (applyPage !== page) {
      await applyPage.close().catch(() => {});
      await focusPreview(page);
    } else if (/smartapply\.indeed|indeed\.com/i.test(applyPage.url())) {
      // Return to Glassdoor results after same-tab Easy Apply
      await openGlassdoorSearch(page, cfg, events);
      await focusPreview(page);
    }
    await setState(
      ApplicationState.RETURNING_TO_RESULTS,
      "Returning to Glassdoor results"
    );
  }

  async function start(overrides = {}) {
    if (running) throw new Error("A run is already in progress");
    running = true;
    abortRequested = false;
    pauseRequested = false;
    userControl = false;
    currentJob = null;
    activePage = null;
    humanTakeover.reset();

    const cfg = { ...(await loadAgentConfig()), ...overrides };
    if (overrides.applyMode) {
      cfg.applyMode = normalizeApplyMode(overrides.applyMode);
    } else {
      cfg.applyMode = normalizeApplyMode(cfg.applyMode);
    }
    applyMode = cfg.applyMode;

    if (isCompanyApplyMode(cfg.applyMode)) {
      running = false;
      throw new Error(
        "Company Apply modes are not implemented yet — choose Easy Apply (Local) or Easy Apply (Remote)"
      );
    }

    const env = envConfig();
    // Per-run override: overrides.headed ?? !env.headless
    let wantHeaded =
      overrides.headed !== undefined
        ? Boolean(overrides.headed)
        : !env.headless;
    if (wantHeaded && !canUseHeadedDisplay()) {
      wantHeaded = false;
      await events.emit("ACTION_COMPLETED", {
        message:
          "Headed display unavailable (no DISPLAY) — falling back to headless",
      });
    }
    headed = wantHeaded;

    const startedAt = Date.now();
    const deadline = startedAt + cfg.maxRuntimeMinutes * 60 * 1000;

    try {
      await setUiMode(AgentUiMode.ACTING);
      let agentProfile = null;
      try {
        agentProfile = await api.getAgentProfile();
      } catch {
        agentProfile = null;
      }
      const candidate = agentProfile
        ? null
        : await api.getCandidate().catch(() => ({}));
      const names = splitName(
        agentProfile?.fullName || candidate?.name || ""
      );
      const profile = {
        ...names,
        email: agentProfile?.email || candidate?.email || "",
        phone: agentProfile?.phone || candidate?.phone || "",
        location: agentProfile?.location || candidate?.location || "",
        linkedin: agentProfile?.linkedin || candidate?.linkedin || "",
        github: agentProfile?.github || candidate?.github || "",
        latestRole: agentProfile?.latestRole || null,
      };

      const run = await api.createRun({
        source: "glassdoor",
        query: cfg.query,
        location: cfg.location,
        searchUrl: resolveSearchUrl(cfg) || null,
        config: {
          applyMode: cfg.applyMode,
          maxResultsPerRun: cfg.maxResultsPerRun,
          maxApplicationsPerRun: cfg.maxApplicationsPerRun,
          minimumScore: cfg.minimumScore,
          requireApprovalBeforeSubmit: cfg.requireApprovalBeforeSubmit,
          searchUrls: cfg.searchUrls || null,
          headed,
          easyApply: isEasyApplyMode(cfg.applyMode),
          browserEngine: resolveBrowserEngine(),
          browserMode: resolveBrowserMode(),
          cdpEndpoint:
            resolveBrowserMode() === "cdp" ? resolveCdpEndpoint() : null,
        },
        state: ApplicationState.GLASSDOOR_SEARCHING,
      });
      currentRun = { runId: run._id };
      events.setRunId(run._id);

      browserHandle = await launchBrowser({
        headless: !headed,
        slowMoMs: cfg.slowMoMs,
        profileDir: env.profileDir,
      });
      context = browserHandle.context;
      browserMode = browserHandle.mode || resolveBrowserMode();
      cdpEndpoint = browserHandle.cdpEndpoint || null;
      await humanTakeover.install(context);
      const page =
        browserHandle.page ||
        context.pages()[0] ||
        (await context.newPage());
      if (preview) {
        await preview.start(page).catch((err) => {
          console.error("preview start failed:", err.message || err);
        });
      }
      await focusPreview(page);

      await setState(
        ApplicationState.GLASSDOOR_SEARCHING,
        `Opening Glassdoor (${APPLY_MODE_META[cfg.applyMode]?.shortLabel || cfg.applyMode})`
      );
      await openGlassdoorSearch(page, cfg, events);
      await focusPreview(page);
      if (await waitForHumanChallenge(page, "Glassdoor search")) {
        await setState(
          ApplicationState.BLOCKED,
          "Stopped — bot challenge not cleared"
        );
        return { runId: run._id, blocked: true };
      }
      await screenshot(page, "search_results");

      const cards = await listResultCards(page, cfg.maxResultsPerRun, cfg);
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
          await focusPreview(page);
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
        await focusPreview(page);
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
      if (preview) {
        await preview.stop().catch(() => {});
      }
      activePageUrl = null;
      activePage = null;
      humanTakeover.reset();
      if (browserHandle) {
        // CDP: disconnect (kill only if we spawned Chrome). Launch: close context.
        await browserHandle.close().catch(() => {});
        browserHandle = null;
        context = null;
      } else if (context) {
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
      headed,
      applyMode,
      applyModeLabel: APPLY_MODE_META[applyMode]?.shortLabel || applyMode,
      browserEngine: resolveBrowserEngine(),
      browserMode,
      cdpEndpoint:
        cdpEndpoint ||
        (browserMode === "cdp" ? resolveCdpEndpoint() : null),
      preview: preview ? preview.getMeta() : { enabled: false },
      pageUrl: activePageUrl || preview?.getMeta?.()?.pageUrl || null,
    };
  }

  return {
    start,
    getStatus,
    controls: controls(),
    resolveInput: (requestId, answer) => inputBroker.resolve(requestId, answer),
  };
}
