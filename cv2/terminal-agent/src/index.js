import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";

// -----------------------------------------------------------------------------
// Configuration
// -----------------------------------------------------------------------------

const root = path.resolve(
  process.env.CV2_ROOT || path.join(import.meta.dirname, ".."),
);
const openclaw =
  process.env.OPENCLAW_BIN || "/home/argo/.openclaw/bin/openclaw";
const model = process.env.OLLAMA_MODEL || "qwen3:4b-instruct";
const browserProfile = process.env.OPENCLAW_BROWSER_PROFILE || "user";

const runId = `${new Date().toISOString().replace(/[:.]/g, "-")}-${crypto
  .randomBytes(3)
  .toString("hex")}`;
const runDir = path.join(root, "runs", runId);

const state = {
  runId,
  status: "starting",
  startedAt: new Date().toISOString(),
  model,
  browserProfile,
  events: [],
};

// -----------------------------------------------------------------------------
// JSON and progress helpers
// -----------------------------------------------------------------------------

async function saveJson(filename, value) {
  const destination = path.join(runDir, filename);
  await fs.writeFile(destination, `${JSON.stringify(value, null, 2)}\n`);
}

async function saveState() {
  await fs.mkdir(runDir, { recursive: true });
  await saveJson("run.json", state);
}

/** Print and persist a human-readable progress event. */
async function report(message, details = {}) {
  const entry = {
    at: new Date().toISOString(),
    message,
    ...details,
  };

  state.events.push(entry);
  await fs.appendFile(
    path.join(runDir, "events.jsonl"),
    `${JSON.stringify(entry)}\n`,
  );
  console.log(`[progress] ${message}`);
}

// -----------------------------------------------------------------------------
// OpenClaw browser commands
// -----------------------------------------------------------------------------

/** Run one OpenClaw browser CLI command and return its stdout. */
function runBrowserCommand(command, args = []) {
  return new Promise((resolve, reject) => {
    const cliArgs = [
      "--no-color",
      "browser",
      "--browser-profile",
      browserProfile,
      "--json",
      command,
      ...args,
    ];

    const child = spawn(openclaw, cliArgs, {
      cwd: root,
      env: process.env,
      stdio: ["ignore", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });

    // OpenClaw diagnostics are useful while the run is in progress, so show
    // them immediately instead of waiting for the command to finish.
    child.stderr.on("data", (chunk) => {
      const text = chunk.toString();
      stderr += text;

      for (const line of text
        .split(/\r?\n/)
        .map((value) => value.trim())
        .filter(Boolean)) {
        console.log(`[openclaw] ${line}`);
      }
    });

    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) {
        resolve(stdout);
        return;
      }

      reject(
        new Error(
          `OpenClaw browser ${command} failed (${code}): ${stderr || stdout}`,
        ),
      );
    });
  });
}

// -----------------------------------------------------------------------------
// Snapshot parsing
// -----------------------------------------------------------------------------

/**
 * OpenClaw --json wraps the actual AI snapshot in a `snapshot` property.
 * Plain-text snapshots are accepted too, which makes this helper easier to
 * reuse when debugging commands manually.
 */
function snapshotPayload(rawSnapshot) {
  try {
    const payload = JSON.parse(rawSnapshot);
    if (payload && typeof payload.snapshot === "string") {
      return payload;
    }
  } catch {
    // The CLI may return a plain-text snapshot.
  }

  return { snapshot: rawSnapshot };
}

/** Return a compact list of Gmail rows suitable for the small Ollama context. */
function compactGmailRows(rawSnapshot) {
  const { snapshot } = snapshotPayload(rawSnapshot);

  // Gmail includes invisible Unicode spacing characters in some previews.
  const cleanSnapshot = snapshot.replace(/[\u200B-\u200D\uFEFF]/g, "");

  let rows = [
    ...cleanSnapshot.matchAll(/^\s*-\s*row\s+"([\s\S]*?)"\s*$/gm),
  ]
    .map((match) => match[1].replace(/\s+/g, " ").trim())
    .filter(Boolean);

  // Fallback for snapshots whose row entries are serialized on one line.
  if (rows.length === 0) {
    rows = cleanSnapshot
      .split(/\r?\n/)
      .filter((line) => /-\s*row\s+"/.test(line))
      .map((line) =>
        line
          .replace(/^.*?-\s*row\s+"/, "")
          .replace(/"\s*[,}]?\s*$/, "")
          .replace(/\s+/g, " ")
          .trim(),
      );
  }

  // Keep each row bounded so 50 rows fit comfortably in qwen3:4b-instruct's
  // context window, while retaining sender, subject, preview, and date.
  return rows
    .slice(0, 50)
    .map((row, index) => `${index + 1}. ${row.slice(0, 500)}`)
    .join("\n");
}

/** Find Gmail's Older button ref in the latest OpenClaw snapshot. */
function findOlderButtonRef(rawSnapshot) {
  const payload = snapshotPayload(rawSnapshot);
  const refs = payload.refs || {};
  const match = Object.entries(refs).find(
    ([, value]) =>
      value?.role === "button" && /^Older$/i.test(value?.name || ""),
  );

  return match?.[0] || null;
}

// -----------------------------------------------------------------------------
// Ollama summary
// -----------------------------------------------------------------------------

async function askOllama(prompt) {
  const baseUrl = process.env.OLLAMA_BASE_URL || "http://127.0.0.1:11434";
  const response = await fetch(`${baseUrl}/api/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      model,
      stream: false,
      format: "json",
      messages: [{ role: "user", content: prompt }],
    }),
  });

  if (!response.ok) {
    throw new Error(
      `Ollama returned ${response.status}: ${(await response.text()).slice(
        0,
        300,
      )}`,
    );
  }

  const body = await response.json();
  return JSON.parse(body.message.content);
}

// -----------------------------------------------------------------------------
// Main workflow
// -----------------------------------------------------------------------------

async function main() {
  await fs.mkdir(runDir, { recursive: true });
  await saveJson("emails.json", []);
  await saveJson("summary.json", {});

  await report(`Starting OpenClaw browser profile '${browserProfile}'`, {
    openclaw,
    model,
  });
  await saveState();

  try {
    await report("Starting the visible OpenClaw Chrome browser");
    await runBrowserCommand("start");

    await report("Opening Gmail inbox");
    await runBrowserCommand("open", ["https://mail.google.com/mail/u/0/#inbox"]);

    await report("Waiting for Gmail to render");
    await new Promise((resolve) => setTimeout(resolve, 3000));

    await report("Capturing Gmail pages until 50 rows are collected");

    const snapshots = [];
    const uniqueRows = new Map();
    let latestSnapshot = "";

    // Gmail may expose only the currently rendered rows. Scroll through each
    // page first, then use the Older button to move to the next page.
    for (let page = 1; page <= 6 && uniqueRows.size < 50; page += 1) {
      let unchangedScrolls = 0;

      for (
        let scroll = 0;
        scroll <= 10 && uniqueRows.size < 50;
        scroll += 1
      ) {
        latestSnapshot = await runBrowserCommand("snapshot", [
          "--format",
          "ai",
          "--limit",
          "1000",
        ]);
        snapshots.push(latestSnapshot);

        const beforeCount = uniqueRows.size;
        const compactPage = compactGmailRows(latestSnapshot);

        for (const row of compactPage.split("\n").filter(Boolean)) {
          const value = row.replace(/^\d+\.\s*/, "");
          uniqueRows.set(value, value);
        }

        const action =
          scroll === 0
            ? `Gmail page ${page}`
            : `Scrolled Gmail page ${page} (${scroll}/10)`;
        await report(`${action}: collected ${uniqueRows.size} unique rows`);

        unchangedScrolls =
          uniqueRows.size === beforeCount ? unchangedScrolls + 1 : 0;

        if (unchangedScrolls >= 2 || uniqueRows.size >= 50) break;

        await runBrowserCommand("press", ["PageDown"]);
        await new Promise((resolve) => setTimeout(resolve, 700));
      }

      if (uniqueRows.size >= 50) break;

      const olderRef = findOlderButtonRef(latestSnapshot);
      if (!olderRef) {
        await report("Gmail has no older page control; stopping pagination");
        break;
      }

      await report(`Opening Gmail older page ${page + 1}`);
      await runBrowserCommand("click", [olderRef]);
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }

    const fullSnapshot = snapshots.join("\n\n--- PAGE BREAK ---\n\n");
    await fs.writeFile(path.join(runDir, "gmail-snapshot.txt"), fullSnapshot);

    const compactRows = [...uniqueRows.values()]
      .slice(0, 50)
      .map((row, index) => `${index + 1}. ${row}`)
      .join("\n");
    await fs.writeFile(path.join(runDir, "gmail-rows.txt"), compactRows);
    await report(
      `Compacted ${compactRows ? compactRows.split("\n").length : 0} Gmail rows before sending to Ollama`,
    );

    await report("Asking Ollama to extract the newest 50 subject headers");
    const extracted = await askOllama(
      `Extract the newest email subject headers from these compact Gmail inbox rows. Return JSON with exactly two keys: emails (array of at most 50 objects with position, subject, sender, date) and summary (string). Use only the visible row data; do not invent missing values. Keep emails in newest-first order.\n\nGMAIL ROWS:\n${compactRows}`,
    );

    const emails = Array.isArray(extracted.emails)
      ? extracted.emails.slice(0, 50)
      : [];
    await saveJson("emails.json", emails);
    await saveJson("summary.json", {
      model,
      generatedAt: new Date().toISOString(),
      summary: extracted.summary || "",
      count: emails.length,
    });

    state.status = "completed";
    state.emailCount = emails.length;
    await report(`Saved ${emails.length} email subject headers and summary`);
  } catch (error) {
    state.status = "failed";
    state.error = error.message;
    await report(`Run failed: ${error.message}`);
    process.exitCode = 1;
  }

  state.completedAt = new Date().toISOString();
  await saveState();
  console.log(`\nJSON results saved to: ${runDir}`);
}

main();
