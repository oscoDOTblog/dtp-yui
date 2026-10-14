import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline/promises";
import { stdin as input, stdout as output } from "node:process";

// OpenClaw owns the visible browser. Ollama owns extraction, scoring, and drafting.
const root = path.resolve(process.env.CV2_ROOT || path.join(import.meta.dirname, ".."));
const openclaw = process.env.OPENCLAW_BIN || "/home/argo/.openclaw/bin/openclaw";
const model = process.env.OLLAMA_MODEL || "qwen3:8b";
const browserProfile = process.env.OPENCLAW_BROWSER_PROFILE || "user";
const runId = new Date().toISOString().replace(/[:.]/g, "-") + "-" + crypto.randomBytes(3).toString("hex");
const runDir = path.join(root, "runs", runId);
const state = { runId, status: "starting", startedAt: new Date().toISOString(), model, browserProfile, events: [] };

async function saveJson(filename, value) {
  await fs.mkdir(runDir, { recursive: true });
  const destination = path.join(runDir, filename);
  const temporary = destination + "." + process.pid + ".tmp";
  await fs.writeFile(temporary, JSON.stringify(value, null, 2) + "\n");
  await fs.rename(temporary, destination);
}

async function saveState() { await saveJson("run.json", state); }

async function report(message, details = {}) {
  const event = { at: new Date().toISOString(), message, ...details };
  state.events.push(event);
  await fs.appendFile(path.join(runDir, "events.jsonl"), JSON.stringify(event) + "\n");
  console.log("[progress] " + message);
}

async function transition(status, message, details = {}) {
  state.status = status;
  Object.assign(state, details);
  await report(message, { status, ...details });
  await saveState();
}

// Run one OpenClaw browser command and stream diagnostics to the terminal.
function runBrowserCommand(command, args = []) {
  return new Promise((resolve, reject) => {
    const child = spawn(openclaw, [
      "--no-color", "browser", "--browser-profile", browserProfile,
      "--json", command, ...args,
    ], { cwd: root, env: process.env, stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => {
      const text = chunk.toString();
      stderr += text;
      text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
        .forEach((line) => console.log("[openclaw] " + line));
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) resolve(stdout);
      else reject(new Error("OpenClaw " + command + " failed (" + code + "): " + (stderr || stdout)));
    });
  });
}

function parseSnapshot(raw) {
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed.snapshot === "string" ? parsed : { snapshot: raw };
  } catch {
    return { snapshot: raw };
  }
}

async function captureSnapshot(label, filename) {
  await report("Capturing " + label + " browser snapshot");
  const raw = await runBrowserCommand("snapshot", ["--format", "ai", "--limit", "1200"]);
  if (filename) await fs.writeFile(path.join(runDir, filename), raw);
  return parseSnapshot(raw);
}

function externalUrls(text) {
  return [...new Set((text.match(/https?:\/\/[^\s<>"')]+/g) || [])
    .map((url) => url.replace(/[),.;]+$/, ""))
    .filter((url) => !/mail\.google\.com|google\.com\/accounts/i.test(url)))];
}

function firstRef(payload, role) {
  return Object.entries(payload.refs || {}).find(([, value]) => value?.role === role)?.[0] || null;
}

function refByName(payload, role, namePattern) {
  return Object.entries(payload.refs || {}).find(([, value]) =>
    value?.role === role && namePattern.test(value?.name || ""))?.[0] || null;
}

function responseUrl(raw) {
  try {
    const value = JSON.parse(raw);
    return value?.url || value?.tab?.url || value?.target?.url || null;
  } catch {
    return null;
  }
}

async function askOllama(prompt) {
  const baseUrl = process.env.OLLAMA_BASE_URL || "http://127.0.0.1:11434";
  const response = await fetch(baseUrl + "/api/chat", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ model, stream: false, format: "json", messages: [{ role: "user", content: prompt }] }),
  });
  if (!response.ok) throw new Error("Ollama returned " + response.status + ": " + (await response.text()).slice(0, 300));
  const body = await response.json();
  return JSON.parse(body.message.content);
}

async function loadCandidateContext() {
  const seedDir = path.join(root, "..", "seed");
  const context = {};
  for (const name of ["candidates", "skills", "workHistory", "projects", "evidence"]) {
    try {
      context[name] = JSON.parse(await fs.readFile(path.join(seedDir, name + ".json"), "utf8"));
    } catch {
      context[name] = [];
    }
  }
  return context;
}

function slug(value) {
  return String(value || "job").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 80) || "job";
}

// Keep prompts small enough for the local model's context window. The full
// browser snapshots remain saved on disk for inspection after the run.
function promptJson(value, maxCharacters = 9000) {
  return JSON.stringify(value).slice(0, maxCharacters);
}

function isExternalUrl(value) {
  return /^https?:\/\//i.test(value || "") &&
    !/mail\.google\.com|google\.com\/accounts|google\.com\/search/i.test(value);
}

function collectListingLinks(payload) {
  const found = new Set(externalUrls(payload.snapshot));
  for (const value of Object.values(payload.refs || {})) {
    for (const candidate of [value?.url, value?.href, value?.description]) {
      if (isExternalUrl(candidate)) found.add(candidate);
    }
  }
  return [...found];
}

function jobIdFor(url, index) {
  return slug(url).slice(0, 54) + "-" + (index + 1);
}

function jobDirectory(jobId) {
  return path.join(runDir, "jobs", jobId);
}

async function saveJobArtifact(job, filename, value) {
  const directory = jobDirectory(job.jobId);
  await fs.mkdir(directory, { recursive: true });
  if (typeof value === "string") await fs.writeFile(path.join(directory, filename), value);
  else await saveJson(path.join("jobs", job.jobId, filename), value);
}

async function updateJob(job, jobs, applications) {
  const index = jobs.findIndex((item) => item.jobId === job.jobId);
  if (index >= 0) jobs[index] = job;
  else jobs.push(job);
  await saveJson("jobs.json", jobs);
  await saveJson("applications.json", applications);
}

function compactCandidate(candidate) {
  const profile = Array.isArray(candidate.candidates) ? candidate.candidates[0] : candidate.candidates;
  return {
    name: profile?.name,
    professionalTitle: profile?.professionalTitle,
    specialtyLine: profile?.specialtyLine,
    preferredRoles: profile?.preferredRoles,
    preferredLocations: profile?.preferredLocations,
    skills: candidate.skills,
    workHistory: candidate.workHistory,
    projects: candidate.projects,
    evidence: candidate.evidence,
  };
}

async function openExternalLinkFromSnapshot(payload, pattern) {
  const ref = refByName(payload, "link", pattern);
  if (!ref) return null;
  const result = await runBrowserCommand("click", [ref]);
  const url = responseUrl(result);
  return isExternalUrl(url) ? url : null;
}

async function verifyCareersPage(job, listing, jobs, applications) {
  const extracted = await askOllama(
    "Extract only the company name, job title, company homepage URL, and any careers URL visible in this listing. Return JSON with exactly company, title, companyUrl, careersUrl. Use null when absent. Do not invent URLs.\n\n" +
    listing.snapshot.slice(0, 5200),
  );
  job.company = extracted.company || null;
  job.title = extracted.title || null;
  job.companyUrl = extracted.companyUrl || null;
  job.careersUrl = extracted.careersUrl || null;
  await saveJobArtifact(job, "job.json", job);
  await updateJob(job, jobs, applications);
  await transition("company_found", "Identified company: " + (job.company || "unknown"), { jobId: job.jobId });

  let companyUrl = isExternalUrl(job.companyUrl) ? job.companyUrl : null;
  if (!companyUrl && job.company) {
    await report("Searching for the company homepage");
    await runBrowserCommand("open", ["https://www.google.com/search?q=" + encodeURIComponent(job.company)]);
    await new Promise((resolve) => setTimeout(resolve, 1400));
    const search = await captureSnapshot("company search", null);
    companyUrl = await openExternalLinkFromSnapshot(search, /official|company|home|about/i);
    if (!companyUrl) companyUrl = externalUrls(search.snapshot)[0] || null;
  }
  if (!companyUrl) throw new Error("Could not find a company homepage");
  job.companyUrl = companyUrl;
  await runBrowserCommand("open", [companyUrl]);
  await new Promise((resolve) => setTimeout(resolve, 1600));
  const company = await captureSnapshot("company homepage", "company-snapshot.txt");
  await saveJobArtifact(job, "company-snapshot.txt", company.snapshot);
  await transition("careers_opened", "Opened company homepage", { jobId: job.jobId, companyUrl });

  let careersUrl = isExternalUrl(job.careersUrl) ? job.careersUrl : null;
  if (!careersUrl) careersUrl = await openExternalLinkFromSnapshot(company, /career|jobs|join us|openings/i);
  if (!careersUrl && job.company) {
    await report("Searching for the company careers page");
    await runBrowserCommand("open", ["https://www.google.com/search?q=" + encodeURIComponent(job.company + " careers")]);
    await new Promise((resolve) => setTimeout(resolve, 1400));
    const search = await captureSnapshot("careers search", null);
    careersUrl = await openExternalLinkFromSnapshot(search, /career|jobs|join us|openings/i);
    if (!careersUrl) careersUrl = externalUrls(search.snapshot)[0] || null;
  }
  if (!careersUrl) {
    job.verification = { status: "uncertain", reason: "careers_page_not_found" };
    job.status = "failed";
    await transition("failed", "Could not locate a careers page", { jobId: job.jobId });
    return false;
  }

  job.careersUrl = careersUrl;
  await runBrowserCommand("open", [careersUrl]);
  await new Promise((resolve) => setTimeout(resolve, 1600));
  const careers = await captureSnapshot("company careers page", "careers-snapshot.txt");
  await saveJobArtifact(job, "careers-snapshot.txt", careers.snapshot);
  const verification = await askOllama(
    "Determine whether the company careers page contains the same job. Return JSON with exactly status (verified|not_found|uncertain|blocked), matchedTitle, reason. Compare the target title to visible careers-page text. Do not infer a match when the role is absent.\n\nTARGET COMPANY: " +
    (job.company || "") + "\nTARGET TITLE: " + (job.title || "") + "\n\nCAREERS PAGE:\n" + careers.snapshot.slice(0, 3800),
  );
  job.verification = verification;
  job.status = verification.status === "verified" ? "careers_verified" : verification.status === "not_found" ? "cancelled" : "failed";
  if (verification.status === "not_found") job.cancelReason = "careers_listing_not_found";
  await saveJobArtifact(job, "job.json", job);
  await transition(job.status, verification.status === "verified"
    ? "Careers verification: VERIFIED"
    : verification.status === "not_found"
      ? "Careers verification: NOT FOUND; cancelling job"
      : "Careers verification: " + verification.status, { jobId: job.jobId });
  return verification.status === "verified";
}

async function main() {
  await fs.mkdir(runDir, { recursive: true });
  for (const filename of ["emails.json", "jobs.json", "applications.json", "documents.json"]) {
    await saveJson(filename, []);
  }
  await report("Starting OpenClaw browser profile '" + browserProfile + "'", { openclaw, model });
  await saveState();

  const jobs = [];
  const applications = [];
  const documents = [];
  const candidate = await loadCandidateContext();

  try {
    await transition("starting", "Starting the visible OpenClaw Chrome browser");
    await runBrowserCommand("start");
    await transition("gmail_opened", "Opening Gmail inbox");
    await runBrowserCommand("open", ["https://mail.google.com/mail/u/0/#inbox"]);
    await new Promise((resolve) => setTimeout(resolve, 2500));

    let gmail = await captureSnapshot("Gmail inbox", "gmail-snapshot.txt");
    const jobsLabelRef = refByName(gmail, "link", /^Jobs(?:\s|$)/i);
    if (!jobsLabelRef) throw new Error("Gmail Jobs label was not found");
    await report("Opening the Gmail Jobs label");
    await runBrowserCommand("click", [jobsLabelRef]);
    await new Promise((resolve) => setTimeout(resolve, 1600));
    gmail = await captureSnapshot("Gmail Jobs label", "gmail-jobs-snapshot.txt");

    const rowRef = firstRef(gmail, "row") || refByName(gmail, "gridcell", /Apply Now|View jobs|View job/i);
    if (!rowRef) throw new Error("No job conversation was found in the Jobs label");
    await report("Opening the top Gmail conversation");
    await runBrowserCommand("click", [rowRef]);
    await new Promise((resolve) => setTimeout(resolve, 1200));
    gmail = await captureSnapshot("selected Gmail conversation", "gmail-message-snapshot.txt");

    const listingLinks = collectListingLinks(gmail);
    if (listingLinks.length === 0) {
      const linkRef = refByName(gmail, "link", /apply|view jobs|view job|job details|learn more/i);
      if (linkRef) {
        const clicked = await runBrowserCommand("click", [linkRef]);
        const clickedUrl = responseUrl(clicked);
        if (isExternalUrl(clickedUrl)) listingLinks.push(clickedUrl);
      }
    }
    if (listingLinks.length === 0) throw new Error("No external job links found in the Gmail conversation");
    await saveJson("emails.json", [{ subject: null, sender: null, listingLinks }]);
    await report("Found " + listingLinks.length + " listing link(s) in the Gmail conversation");

    for (let index = 0; index < listingLinks.length; index += 1) {
      const listingUrl = listingLinks[index];
      const job = { jobId: jobIdFor(listingUrl, index), listingUrl, status: "queued", verification: null, error: null };
      jobs.push(job);
      await updateJob(job, jobs, applications);
      await report("Starting job " + (index + 1) + "/" + listingLinks.length, { jobId: job.jobId, listingUrl });
      try {
        await transition("listing_opened", "Opening listing", { jobId: job.jobId });
        await runBrowserCommand("open", [listingUrl]);
        await new Promise((resolve) => setTimeout(resolve, 1800));
        const listing = await captureSnapshot("job listing", null);
        await saveJobArtifact(job, "listing-snapshot.txt", listing.snapshot);
        job.status = "listing_opened";

        const extracted = await askOllama(
          "Extract one job posting. Return JSON with exactly company, title, location, workMode, salary, description, requirements, applicationUrl, warnings. Keep description under 900 characters and requirements to at most 10 strings. Do not invent facts.\n\n" +
          listing.snapshot.slice(0, 5200),
        );
        Object.assign(job, extracted, { listingUrl, status: "listing_extracted" });
        await saveJobArtifact(job, "job.json", job);
        await updateJob(job, jobs, applications);
        await transition("listing_extracted", "Extracted listing facts", { jobId: job.jobId, title: job.title });

        if (!await verifyCareersPage(job, listing, jobs, applications)) continue;

        await report("Scoring compatibility", { jobId: job.jobId });
        const compactCandidate = compactCandidate(candidate);
        const score = await askOllama(
          "Score this verified job against the candidate. Return JSON with exactly compatibilityScore (0-100 integer), recommendation (apply|review|skip), strengths (array), gaps (array), reasoning (string), roleFamily (systems|product|mobile|ai|other). Never invent evidence.\n\nJOB:\n" +
          promptJson(job, 6000) + "\n\nCANDIDATE:\n" + promptJson(compactCandidate, 6500),
        );
        job.score = {
          compatibilityScore: Math.max(0, Math.min(100, Number(score.compatibilityScore) || 0)),
          recommendation: ["apply", "review", "skip"].includes(score.recommendation) ? score.recommendation : "review",
          strengths: Array.isArray(score.strengths) ? score.strengths : [],
          gaps: Array.isArray(score.gaps) ? score.gaps : [],
          reasoning: String(score.reasoning || ""),
          roleFamily: score.roleFamily || "other",
        };
        job.status = "scored";
        await saveJobArtifact(job, "score.json", job.score);
        await updateJob(job, jobs, applications);
        await transition("scored", "Compatibility score saved", { jobId: job.jobId, compatibilityScore: job.score.compatibilityScore });

        await report("Generating resume", { jobId: job.jobId });
        const resume = await askOllama(
          "Create a truthful tailored resume. Return JSON with exactly resumeText. Use only this job and candidate evidence. Keep it under 2500 characters.\n\nJOB:\n" +
          promptJson(job, 5000) + "\n\nCANDIDATE:\n" + promptJson(compactCandidate, 6500),
        );
        await report("Generating cover letter", { jobId: job.jobId });
        const cover = await askOllama(
          "Create a truthful tailored cover letter. Return JSON with exactly coverLetterText. Keep it under 1800 characters and use only this job and candidate evidence.\n\nJOB:\n" +
          promptJson(job, 5000) + "\n\nCANDIDATE:\n" + promptJson(compactCandidate, 5000),
        );
        const folder = path.join(root, "generated-applications", slug(job.company) + "-" + slug(job.title));
        await fs.mkdir(folder, { recursive: true });
        const resumePath = path.join(folder, "resume.txt");
        const coverLetterPath = path.join(folder, "cover-letter.txt");
        await fs.writeFile(resumePath, String(resume.resumeText || ""));
        await fs.writeFile(coverLetterPath, String(cover.coverLetterText || ""));
        const document = { jobId: job.jobId, model, resumePath, coverLetterPath };
        documents.push(document);
        await saveJobArtifact(job, "documents.json", document);
        await saveJson("documents.json", documents);
        job.resumePath = resumePath;
        job.coverLetterPath = coverLetterPath;
        job.status = "documents_generated";
        await updateJob(job, jobs, applications);
        await transition("documents_generated", "Documents saved", { jobId: job.jobId });

        await report("Opening application page", { jobId: job.jobId });
        await runBrowserCommand("open", [job.applicationUrl || listingUrl]);
        await new Promise((resolve) => setTimeout(resolve, 1200));
        job.status = "application_ready";
        await updateJob(job, jobs, applications);
        console.log("\nReady for review:\nCompany: " + (job.company || "Unknown") + "\nRole: " + (job.title || "Unknown") + "\nCompatibility: " + job.score.compatibilityScore + "%\nRecommendation: " + job.score.recommendation + "\n\nResume: " + resumePath + "\nCover letter: " + coverLetterPath + "\n");
        const readline = createInterface({ input, output });
        const answer = (await readline.question("Type APPROVE to mark ready, SKIP to skip, or PAUSE to stop: ")).trim().toUpperCase();
        readline.close();
        job.status = answer === "APPROVE" ? "approved_ready" : answer === "SKIP" ? "skipped" : "paused";
        applications.push({ jobId: job.jobId, status: job.status, approval: answer, submittedAt: null, fieldsEdited: [], submissionResult: null });
        await updateJob(job, jobs, applications);
        if (job.status === "paused") break;
      } catch (error) {
        job.status = "failed";
        job.error = error.message;
        await saveJobArtifact(job, "job.json", job);
        await updateJob(job, jobs, applications);
        await report("Job failed; continuing to the next listing: " + error.message, { jobId: job.jobId });
      }
    }
    await transition("completed", "Finished processing queued job listings", { jobCount: jobs.length });
  } catch (error) {
    state.error = error.message;
    await transition("failed", "Run failed: " + error.message);
    process.exitCode = 1;
  }
  state.completedAt = new Date().toISOString();
  await saveState();
  console.log("\nJSON results saved to: " + runDir);
}

async function legacyMain() {
  await fs.mkdir(runDir, { recursive: true });
  for (const filename of ["emails.json", "jobs.json", "applications.json", "documents.json"]) await saveJson(filename, []);
  await report("Starting OpenClaw browser profile '" + browserProfile + "'", { openclaw, model });
  await saveState();

  try {
    await transition("starting", "Starting the visible OpenClaw Chrome browser");
    await runBrowserCommand("start");
    await transition("gmail_opened", "Opening Gmail inbox");
    await runBrowserCommand("open", ["https://mail.google.com/mail/u/0/#inbox"]);
    await new Promise((resolve) => setTimeout(resolve, 3000));

    // Select the newest email with an external URL. If the inbox snapshot does
    // not include links, open the first visible Gmail row and inspect the email.
    await report("Opening the Gmail Jobs label");
    let gmail = await captureSnapshot("Gmail inbox", "gmail-snapshot.txt");
    const jobsLabelRef = refByName(gmail, "link", /^Jobs(?:\s|$)/i);
    if (!jobsLabelRef) throw new Error("Gmail Jobs label was not found");
    await runBrowserCommand("click", [jobsLabelRef]);
    await new Promise((resolve) => setTimeout(resolve, 1800));
    gmail = await captureSnapshot("Gmail Jobs label", "gmail-jobs-snapshot.txt");

    await report("Opening the top Gmail conversation before looking for links");
    const email = { subject: null, sender: null, sourceEmailId: null, listingUrl: null };
    // OpenClaw commonly exposes Gmail rows as gridcells rather than row refs.
    const rowRef = firstRef(gmail, "row") || refByName(gmail, "gridcell", /Apply Now|View jobs|View job/i);
    if (rowRef) {
      await runBrowserCommand("click", [rowRef]);
      await new Promise((resolve) => setTimeout(resolve, 1200));
      gmail = await captureSnapshot("selected Gmail message", "gmail-message-snapshot.txt");
    }
    await report("Looking for the job link inside the open Gmail conversation");
    let listingUrl = externalUrls(gmail.snapshot)[0];
    if (!listingUrl) {
      const linkRef = refByName(gmail, "link", /apply|view jobs|view job|job details|learn more/i);
      if (linkRef) {
        await report("Opening the top-level job link from the Gmail conversation");
        const clickResult = await runBrowserCommand("click", [linkRef]);
        listingUrl = responseUrl(clickResult);
        await new Promise((resolve) => setTimeout(resolve, 1800));
      }
    }
    if (!listingUrl) throw new Error("No external job link found in the newest Gmail message");
    email.listingUrl = listingUrl;
    await saveJson("emails.json", [email]);
    await transition("job_email_found", "Found the newest job email and listing link", { email });

    await transition("listing_opened", "Opening the job listing", { listingUrl });
    await runBrowserCommand("open", [listingUrl]);
    await new Promise((resolve) => setTimeout(resolve, 2500));
    const listing = await captureSnapshot("job listing", "job-snapshot.txt");
    const candidate = await loadCandidateContext();

    await report("Asking Ollama to extract the job details");
    const jobPrompt = "Extract one job posting from the browser text below. Return JSON with exactly these keys: company, title, location, workMode, salary, description, requirements, applicationUrl, warnings. Use null or [] when unavailable. Do not invent facts. The applicationUrl should be the original listing URL if no separate apply URL is visible.\n\nLISTING URL: " + listingUrl + "\n\nBROWSER TEXT:\n" + listing.snapshot.slice(0, 12000);
    const job = await askOllama(jobPrompt);
    job.listingUrl = listingUrl;
    job.sourceEmailId = email.sourceEmailId;
    await saveJson("jobs.json", [job]);
    await transition("job_extracted", "Extracted job details from the listing", { job });

    await report("Scoring compatibility against the local CV1 candidate profile");
    const scorePrompt = "Evaluate this job against the candidate context. Return JSON with exactly: compatibilityScore (integer 0-100), recommendation (apply|review|skip), strengths (string array), gaps (string array), reasoning (string), roleFamily (systems|product|mobile|ai|other). Use only evidence in the candidate context and never invent experience.\n\nJOB:\n" + promptJson(job, 7000) + "\n\nCANDIDATE CONTEXT:\n" + promptJson(candidate, 9000);
    const score = await askOllama(scorePrompt);
    const normalizedScore = {
      compatibilityScore: Math.max(0, Math.min(100, Number(score.compatibilityScore) || 0)),
      recommendation: ["apply", "review", "skip"].includes(score.recommendation) ? score.recommendation : "review",
      strengths: Array.isArray(score.strengths) ? score.strengths : [],
      gaps: Array.isArray(score.gaps) ? score.gaps : [],
      reasoning: String(score.reasoning || ""),
      roleFamily: score.roleFamily || "other",
    };
    job.score = normalizedScore;
    await saveJson("jobs.json", [job]);
    await transition("scored", "Compatibility score saved", { compatibilityScore: normalizedScore.compatibilityScore });

    await report("Generating a tailored resume and cover letter");
    const documentPrompt = "Create a truthful tailored resume and cover letter for this job. Return JSON with exactly resumeText and coverLetterText. Use only the candidate context; do not add employers, dates, skills, metrics, or credentials not present there.\n\nJOB:\n" + promptJson(job, 7000) + "\n\nCANDIDATE CONTEXT:\n" + promptJson(candidate, 9000);
    const documents = await askOllama(documentPrompt);
    const folder = path.join(root, "generated-applications", slug(job.company) + "-" + slug(job.title));
    await fs.mkdir(folder, { recursive: true });
    const resumePath = path.join(folder, "resume.txt");
    const coverLetterPath = path.join(folder, "cover-letter.txt");
    await fs.writeFile(resumePath, String(documents.resumeText || ""));
    await fs.writeFile(coverLetterPath, String(documents.coverLetterText || ""));
    await saveJson("documents.json", [{ model, generatedAt: new Date().toISOString(), resumePath, coverLetterPath, resumeText: documents.resumeText || "", coverLetterText: documents.coverLetterText || "" }]);
    job.resumePath = resumePath;
    job.coverLetterPath = coverLetterPath;
    await saveJson("jobs.json", [job]);
    await transition("documents_generated", "Tailored documents saved", { resumePath, coverLetterPath });

    await transition("application_ready", "Opening the application page for review");
    await runBrowserCommand("open", [job.applicationUrl || listingUrl]);
    await new Promise((resolve) => setTimeout(resolve, 1800));
    await report("Application page is open; no fields were edited and nothing was submitted");
    console.log("\nReady for review:\nCompany: " + (job.company || "Unknown") + "\nRole: " + (job.title || "Unknown") + "\nCompatibility: " + normalizedScore.compatibilityScore + "%\nRecommendation: " + normalizedScore.recommendation + "\n\nResume: " + resumePath + "\nCover letter: " + coverLetterPath + "\n");

    const readline = createInterface({ input, output });
    const answer = (await readline.question("Type APPROVE to mark ready, SKIP to skip, or PAUSE to stop: ")).trim().toUpperCase();
    readline.close();
    const application = {
      jobId: slug(job.company) + "-" + slug(job.title),
      status: answer === "APPROVE" ? "approved_ready" : answer === "SKIP" ? "skipped" : "paused",
      approval: answer,
      submittedAt: null,
      fieldsEdited: [],
      submissionResult: null,
    };
    await saveJson("applications.json", [application]);
    await transition("completed", "Terminal decision recorded: " + application.status, { application });
  } catch (error) {
    state.error = error.message;
    await transition("failed", "Run failed: " + error.message);
    process.exitCode = 1;
  }
  state.completedAt = new Date().toISOString();
  await saveState();
  console.log("\nJSON results saved to: " + runDir);
}

main();
