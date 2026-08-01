import { spawn } from "child_process";
import fs from "fs/promises";
import fsSync from "fs";
import os from "os";
import path from "path";
import { fileURLToPath } from "url";
import { chromium, firefox } from "playwright";
import { envConfig } from "./config.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * Extra Chromium args for Playwright launch mode only.
 * Do NOT pass --disable-blink-features=AutomationControlled — modern Chrome
 * shows a yellow "unsupported command-line flag" bar for it.
 */
const CHROMIUM_HEADED_ARGS = [
  "--window-size=1440,1000",
  "--window-position=40,40",
];

const CDP_READY_TIMEOUT_MS = 15000;
const CDP_POLL_MS = 250;

/**
 * Candidate paths for branded Google Chrome (macOS / Linux / Windows).
 */
export function resolveChromeExecutablePath() {
  const fromEnv = (process.env.CV_AGENT_CHROME_EXECUTABLE || "").trim();
  if (fromEnv && fsSync.existsSync(fromEnv)) return fromEnv;

  const home = os.homedir();
  const candidates = [];
  if (process.platform === "darwin") {
    candidates.push(
      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
      path.join(
        home,
        "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
      )
    );
  } else if (process.platform === "win32") {
    candidates.push(
      "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
      "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
      path.join(
        process.env.LOCALAPPDATA || "",
        "Google\\Chrome\\Application\\chrome.exe"
      )
    );
  } else {
    candidates.push(
      "/usr/bin/google-chrome-stable",
      "/usr/bin/google-chrome",
      "/usr/bin/chromium-browser",
      "/usr/bin/chromium"
    );
  }

  for (const p of candidates) {
    if (p && fsSync.existsSync(p)) return p;
  }
  return null;
}

/**
 * Browser engine: firefox | chromium
 */
export function resolveBrowserEngine() {
  const browser = (process.env.CV_AGENT_BROWSER || "").trim().toLowerCase();
  if (browser === "firefox" || browser === "ff") return "firefox";
  if (browser === "chromium" || browser === "chrome") return "chromium";

  const channel = (process.env.CV_AGENT_BROWSER_CHANNEL || "")
    .trim()
    .toLowerCase();
  if (channel === "firefox" || channel === "ff") return "firefox";

  return "firefox";
}

/**
 * Launch strategy: cdp (system Chrome + connectOverCDP) | launch (Playwright persistent).
 * Default: cdp for chromium, launch for firefox.
 */
export function resolveBrowserMode(engine = resolveBrowserEngine()) {
  const raw = (process.env.CV_AGENT_BROWSER_MODE || "").trim().toLowerCase();
  if (raw === "cdp" || raw === "connect" || raw === "attach") return "cdp";
  if (raw === "launch" || raw === "persistent" || raw === "playwright") {
    return "launch";
  }
  return engine === "chromium" ? "cdp" : "launch";
}

export function resolveCdpPort() {
  const n = Number.parseInt(process.env.CV_AGENT_CDP_PORT || "9222", 10);
  return Number.isFinite(n) && n > 0 ? n : 9222;
}

/**
 * Full CDP HTTP endpoint, e.g. http://127.0.0.1:9222
 */
export function resolveCdpEndpoint() {
  const fromEnv = (process.env.CV_AGENT_CDP_URL || "").trim().replace(/\/$/, "");
  if (fromEnv) return fromEnv;
  return `http://127.0.0.1:${resolveCdpPort()}`;
}

/**
 * Legacy escape hatch: spawn a dedicated Chrome profile for CDP.
 * Default off — attach to the user's existing Chrome session instead.
 */
export function resolveCdpSpawnEnabled() {
  const raw = (process.env.CV_AGENT_CDP_SPAWN || "").trim().toLowerCase();
  return raw === "1" || raw === "true" || raw === "on" || raw === "yes";
}

const CDP_ATTACH_HELP =
  "Chrome DevTools is not listening. Relaunch your normal Chrome with remote debugging " +
  "(dtp-os → Apply Copilot tool, or: cv/services/agent/scripts/relaunch-chrome-cdp.sh), " +
  "then set CV_AGENT_CDP_URL=http://127.0.0.1:9222 and retry.";

export function resolveCdpProfileDir(baseProfileDir) {
  const fromEnv = (process.env.CV_AGENT_CDP_PROFILE_DIR || "").trim();
  if (fromEnv) return fromEnv;
  const base =
    baseProfileDir ||
    envConfig().profileDir ||
    path.join(__dirname, "..", "browser-profile");
  if (base.endsWith("-cdp") || base.endsWith(`${path.sep}cdp`)) return base;
  // Prefer sibling browser-profile-cdp next to browser-profile
  if (path.basename(base) === "browser-profile") {
    return path.join(path.dirname(base), "browser-profile-cdp");
  }
  return `${base}-cdp`;
}

/**
 * Prefer installed Google Chrome over Playwright's "Chrome for Testing"
 * when engine is chromium (launch mode).
 */
export function resolveBrowserChannel(engine = resolveBrowserEngine()) {
  if (engine !== "chromium") return null;

  const raw = (process.env.CV_AGENT_BROWSER_CHANNEL || "").trim().toLowerCase();
  if (
    !raw ||
    raw === "firefox" ||
    raw === "ff" ||
    raw === "chromium" ||
    raw === "bundled" ||
    raw === "0"
  ) {
    if (!raw || raw === "firefox" || raw === "ff") {
      if (process.platform === "darwin" || process.platform === "win32") {
        return "chrome";
      }
      return null;
    }
    return null;
  }
  if (raw === "chrome" || raw === "msedge" || raw === "chrome-beta") {
    return raw === "chrome-beta" ? "chrome-beta" : raw;
  }
  return null;
}

export function resolveChromiumSandbox(channel) {
  const raw = (process.env.CV_AGENT_CHROMIUM_SANDBOX || "").trim().toLowerCase();
  if (raw === "0" || raw === "false" || raw === "off") return false;
  if (raw === "1" || raw === "true" || raw === "on") return true;
  if (process.platform === "linux" && (!channel || process.getuid?.() === 0)) {
    return false;
  }
  return true;
}

export function canUseHeadedDisplay() {
  if (process.platform === "linux" && !process.env.DISPLAY) {
    return false;
  }
  return true;
}

function profileDirForEngine(baseDir, engine) {
  if (engine === "firefox") {
    if (baseDir.endsWith("-firefox") || baseDir.endsWith("/firefox")) {
      return baseDir;
    }
    return `${baseDir}-firefox`;
  }
  return baseDir;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Probe Chrome DevTools HTTP endpoint until ready or timeout.
 */
export async function waitForCdpReady(endpoint, timeoutMs = CDP_READY_TIMEOUT_MS) {
  const base = String(endpoint || "").replace(/\/$/, "");
  const url = `${base}/json/version`;
  const deadline = Date.now() + timeoutMs;
  let lastErr = null;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(2000) });
      if (res.ok) {
        const body = await res.json().catch(() => ({}));
        return body;
      }
      lastErr = new Error(`CDP HTTP ${res.status}`);
    } catch (err) {
      lastErr = err;
    }
    await sleep(CDP_POLL_MS);
  }
  throw new Error(
    `Chrome DevTools not ready at ${url} within ${timeoutMs}ms: ${
      lastErr?.message || lastErr
    }`
  );
}

/**
 * Spawn branded Chrome with remote debugging (no Playwright launch flags).
 */
export function spawnChromeForCdp({
  executablePath,
  userDataDir,
  port,
  headless = false,
}) {
  if (!executablePath) {
    throw new Error(
      "No Google Chrome executable found — set CV_AGENT_CHROME_EXECUTABLE"
    );
  }
  const args = [
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${userDataDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-sync",
  ];
  if (headless) {
    args.push("--headless=new");
  } else {
    args.push(...CHROMIUM_HEADED_ARGS);
  }
  // Open a blank tab so CDP has a page immediately
  args.push("about:blank");

  const child = spawn(executablePath, args, {
    stdio: "ignore",
    detached: false,
  });

  child.on("error", (err) => {
    console.error("cv-agent: Chrome spawn error:", err.message || err);
  });

  console.log(
    `cv-agent: spawned Chrome pid=${child.pid} port=${port} profile=${userDataDir}`
  );
  return child;
}

async function connectCdpBrowser(endpoint) {
  const browser = await chromium.connectOverCDP(endpoint);
  const contexts = browser.contexts();
  const context = contexts[0] || (await browser.newContext());
  let page = context.pages().find((p) => !p.isClosed()) || null;
  if (!page) {
    page = await context.newPage();
  }
  return { browser, context, page };
}

function makeLaunchHandle({ context, page, mode, meta = {} }) {
  return {
    context,
    page,
    mode,
    browser: null,
    ownedProcess: null,
    cdpEndpoint: meta.cdpEndpoint || null,
    spawned: false,
    ...meta,
    async close() {
      try {
        await context?.close?.().catch(() => {});
      } catch {
        /* ignore */
      }
    },
  };
}

function makeCdpHandle({
  browser,
  context,
  page,
  endpoint,
  ownedProcess = null,
}) {
  let closed = false;
  return {
    context,
    page,
    mode: "cdp",
    browser,
    ownedProcess,
    cdpEndpoint: endpoint,
    spawned: Boolean(ownedProcess),
    async close() {
      if (closed) return;
      closed = true;
      // connectOverCDP: browser.close() quits Chrome. Only do that when we spawned it.
      // Attach-only: leave Chrome running (drop the Playwright connection).
      if (ownedProcess) {
        try {
          await browser?.close?.();
        } catch {
          /* ignore */
        }
        if (!ownedProcess.killed) {
          try {
            ownedProcess.kill("SIGTERM");
          } catch {
            /* ignore */
          }
          await sleep(500);
          if (!ownedProcess.killed) {
            try {
              ownedProcess.kill("SIGKILL");
            } catch {
              /* ignore */
            }
          }
        }
      } else {
        try {
          browser?.removeAllListeners?.();
        } catch {
          /* ignore */
        }
        // No public disconnect that keeps Chrome alive — do not call browser.close().
        console.log(
          `cv-agent: CDP attach-only disconnect (Chrome left running at ${endpoint})`
        );
      }
    },
  };
}

async function launchViaCdp({ useHeadless, profileDir }) {
  const endpoint = resolveCdpEndpoint();
  const port = resolveCdpPort();
  const allowSpawn = resolveCdpSpawnEnabled();

  let alreadyUp = false;
  try {
    await waitForCdpReady(endpoint, 800);
    alreadyUp = true;
  } catch {
    alreadyUp = false;
  }

  let ownedProcess = null;
  if (!alreadyUp) {
    if (!allowSpawn) {
      try {
        await waitForCdpReady(endpoint, CDP_READY_TIMEOUT_MS);
      } catch (err) {
        throw new Error(
          `${CDP_ATTACH_HELP} (endpoint=${endpoint}; ${err.message || err})`
        );
      }
    } else {
      // Legacy: spawn dedicated browser-profile-cdp
      const executablePath = resolveChromeExecutablePath();
      const userDataDir = resolveCdpProfileDir(profileDir);
      await fs.mkdir(userDataDir, { recursive: true });
      ownedProcess = spawnChromeForCdp({
        executablePath,
        userDataDir,
        port,
        headless: useHeadless,
      });
      try {
        await waitForCdpReady(endpoint, CDP_READY_TIMEOUT_MS);
      } catch (err) {
        try {
          ownedProcess.kill("SIGKILL");
        } catch {
          /* ignore */
        }
        throw err;
      }
    }
  } else {
    console.log(`cv-agent: CDP ready at ${endpoint} (attach-only)`);
  }

  const { browser, context, page } = await connectCdpBrowser(endpoint);
  console.log(
    `cv-agent browser: CDP ${endpoint} (spawned=${Boolean(ownedProcess)}, attachOnly=${!ownedProcess})`
  );
  return makeCdpHandle({
    browser,
    context,
    page,
    endpoint,
    ownedProcess,
  });
}

async function launchFirefox({ userDataDir, useHeadless, slowMoMs }) {
  /** @type {import('playwright').LaunchPersistentContextOptions} */
  const options = {
    headless: useHeadless,
    slowMo: slowMoMs ?? 0,
    firefoxUserPrefs: {
      "dom.webdriver.enabled": false,
      useAutomationExtension: false,
      "media.navigator.permission.disabled": true,
    },
  };

  if (useHeadless) {
    options.viewport = { width: 1440, height: 1000 };
  } else {
    options.viewport = null;
  }

  const context = await firefox.launchPersistentContext(userDataDir, options);
  console.log("cv-agent browser: Firefox (persistent profile)");
  const page = context.pages()[0] || (await context.newPage());
  return makeLaunchHandle({
    context,
    page,
    mode: "launch",
    meta: { engine: "firefox" },
  });
}

async function launchChromiumPersistent({ userDataDir, useHeadless, slowMoMs }) {
  const channel = resolveBrowserChannel("chromium");
  const chromiumSandbox = resolveChromiumSandbox(channel);
  const executablePath = resolveChromeExecutablePath();
  const args = useHeadless ? [] : [...CHROMIUM_HEADED_ARGS];

  /** @type {import('playwright').LaunchPersistentContextOptions} */
  const options = {
    headless: useHeadless,
    slowMo: slowMoMs ?? 0,
    args,
    chromiumSandbox,
    ignoreDefaultArgs: ["--enable-automation"],
  };

  if (useHeadless) {
    options.viewport = { width: 1440, height: 1000 };
  } else {
    options.viewport = null;
  }

  if (executablePath) {
    options.executablePath = executablePath;
  } else if (channel) {
    options.channel = channel;
  }

  let context;
  try {
    context = await chromium.launchPersistentContext(userDataDir, options);
    if (executablePath) {
      console.log(
        `cv-agent browser: ${executablePath} (profile=${userDataDir}, sandbox=${chromiumSandbox})`
      );
    } else if (channel) {
      console.log(
        `cv-agent browser: system ${channel} (profile=${userDataDir}, sandbox=${chromiumSandbox})`
      );
    } else {
      console.log(
        `cv-agent browser: bundled Chromium (profile=${userDataDir}, sandbox=${chromiumSandbox})`
      );
    }
  } catch (err) {
    if (!executablePath && !channel) throw err;
    console.warn(
      `cv-agent: system Chrome failed (${err.message || err}); falling back to bundled Chromium`
    );
    delete options.executablePath;
    delete options.channel;
    if (process.platform === "linux") {
      options.chromiumSandbox = false;
    }
    context = await chromium.launchPersistentContext(userDataDir, options);
  }

  const page = context.pages()[0] || (await context.newPage());
  return makeLaunchHandle({
    context,
    page,
    mode: "launch",
    meta: { engine: "chromium" },
  });
}

/**
 * Open a browser session for Glassdoor + ATS.
 * @returns {Promise<{
 *   context: import('playwright').BrowserContext,
 *   page: import('playwright').Page,
 *   mode: 'cdp'|'launch',
 *   cdpEndpoint: string|null,
 *   spawned: boolean,
 *   close: () => Promise<void>
 * }>}
 */
export async function launchBrowser({ headless, slowMoMs, profileDir } = {}) {
  const env = envConfig();
  const engine = resolveBrowserEngine();
  const mode = resolveBrowserMode(engine);
  const baseProfile = profileDir || env.profileDir;
  await fs.mkdir(env.screenshotDir, { recursive: true });

  const wantHeadless = headless ?? env.headless;
  const useHeadless = wantHeadless || !canUseHeadedDisplay();

  if (engine === "chromium" && mode === "cdp") {
    // Attach-only by default — do not fall back to Playwright launch (wrong profile).
    return launchViaCdp({
      useHeadless,
      profileDir: baseProfile,
    });
  }

  if (engine === "firefox") {
    const userDataDir = profileDirForEngine(baseProfile, "firefox");
    await fs.mkdir(userDataDir, { recursive: true });
    try {
      return await launchFirefox({ userDataDir, useHeadless, slowMoMs });
    } catch (err) {
      console.warn(
        `cv-agent: Firefox launch failed (${err.message || err}); falling back to Chromium`
      );
      if (resolveBrowserMode("chromium") === "cdp") {
        try {
          return await launchViaCdp({
            useHeadless,
            profileDir: baseProfile,
          });
        } catch {
          /* fall through */
        }
      }
      const chromeDir = profileDirForEngine(baseProfile, "chromium");
      await fs.mkdir(chromeDir, { recursive: true });
      return launchChromiumPersistent({
        userDataDir: chromeDir,
        useHeadless,
        slowMoMs,
      });
    }
  }

  const userDataDir = profileDirForEngine(baseProfile, "chromium");
  await fs.mkdir(userDataDir, { recursive: true });
  return launchChromiumPersistent({ userDataDir, useHeadless, slowMoMs });
}

export async function screenshot(page, label = "step") {
  const env = envConfig();
  await fs.mkdir(env.screenshotDir, { recursive: true });
  const safe = String(label).replace(/[^a-zA-Z0-9_-]+/g, "_").slice(0, 60);
  const file = path.join(env.screenshotDir, `${Date.now()}_${safe}.png`);
  await page.screenshot({ path: file, fullPage: false });
  return file;
}

export async function closeExtraPages(context, keepPage) {
  for (const page of context.pages()) {
    if (page !== keepPage && !page.isClosed()) {
      try {
        await page.close();
      } catch {
        /* ignore */
      }
    }
  }
}

/**
 * Cloudflare / bot interstitial (Glassdoor "Humans only", Turnstile, etc.).
 */
export async function pageLooksLikeBotChallenge(page) {
  if (!page || page.isClosed?.()) return false;
  const title = await page.title().catch(() => "");
  const text = (await page.locator("body").innerText().catch(() => "")).slice(
    0,
    8000
  );
  const blob = `${title}\n${text}`;
  return /humans only|verify you are human|just a moment|attention required|cf-browser-verification|challenge-platform|unusual traffic|captcha|checking your browser/i.test(
    blob
  );
}
