import fs from "fs/promises";
import fsSync from "fs";
import os from "os";
import path from "path";
import { chromium, firefox } from "playwright";
import { envConfig } from "./config.js";

/**
 * Extra Chromium args. Do NOT pass --disable-blink-features=AutomationControlled
 * — modern Chrome shows a yellow "unsupported command-line flag" bar for it,
 * which is itself a bot fingerprint.
 */
const CHROMIUM_HEADED_ARGS = [
  "--window-size=1440,1000",
  "--window-position=40,40",
];

/**
 * Candidate paths for branded Google Chrome (macOS / Linux / Windows).
 * Playwright's channel:"chrome" only checks standard system locations;
 * ~/Applications is NOT searched by default.
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
 * Prefer CV_AGENT_BROWSER; also accept channel=firefox as shorthand.
 * Default is Firefox (Cloudflare often blocks Playwright-driven Chrome harder).
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
 * Prefer installed Google Chrome over Playwright's "Chrome for Testing"
 * when engine is chromium.
 * Set CV_AGENT_BROWSER_CHANNEL=chromium to force the bundled browser.
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
    // Default system Chrome on macOS/Windows when channel unset / firefox leftover.
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

/**
 * Playwright adds --no-sandbox unless chromiumSandbox === true.
 * That flag shows the yellow "unsupported command-line flag" bar and is a
 * strong Cloudflare fingerprint. Keep sandbox on for host Chrome; allow
 * opt-out for Linux containers that cannot use a sandbox.
 */
export function resolveChromiumSandbox(channel) {
  const raw = (process.env.CV_AGENT_CHROMIUM_SANDBOX || "").trim().toLowerCase();
  if (raw === "0" || raw === "false" || raw === "off") return false;
  if (raw === "1" || raw === "true" || raw === "on") return true;
  // Docker / root Linux often cannot use the Chromium sandbox.
  if (process.platform === "linux" && (!channel || process.getuid?.() === 0)) {
    return false;
  }
  return true;
}

/**
 * Headed browsers need a real display. Linux containers without DISPLAY
 * cannot show a window — callers should fall back to headless.
 */
export function canUseHeadedDisplay() {
  if (process.platform === "linux" && !process.env.DISPLAY) {
    return false;
  }
  return true;
}

function profileDirForEngine(baseDir, engine) {
  // Chrome and Firefox profiles are incompatible — keep them separate.
  if (engine === "firefox") {
    if (baseDir.endsWith("-firefox") || baseDir.endsWith("/firefox")) {
      return baseDir;
    }
    return `${baseDir}-firefox`;
  }
  return baseDir;
}

async function launchFirefox({ userDataDir, useHeadless, slowMoMs }) {
  /** @type {import('playwright').LaunchPersistentContextOptions} */
  const options = {
    headless: useHeadless,
    slowMo: slowMoMs ?? 0,
    firefoxUserPrefs: {
      // Reduce common automation fingerprints.
      "dom.webdriver.enabled": false,
      "useAutomationExtension": false,
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
  return context;
}

async function launchChromium({ userDataDir, useHeadless, slowMoMs }) {
  const channel = resolveBrowserChannel("chromium");
  const chromiumSandbox = resolveChromiumSandbox(channel);
  const executablePath = resolveChromeExecutablePath();
  // Keep args minimal for system Chrome — custom flags often trigger the
  // yellow "unsupported command-line flag" bar that Cloudflare can see.
  const args = useHeadless ? [] : [...CHROMIUM_HEADED_ARGS];

  /** @type {import('playwright').LaunchPersistentContextOptions} */
  const options = {
    headless: useHeadless,
    slowMo: slowMoMs ?? 0,
    args,
    chromiumSandbox,
    // Drop Playwright's automation banner / navigator.webdriver kickers.
    ignoreDefaultArgs: ["--enable-automation"],
    // Do not set userAgent — spoofed UA vs real Chrome binary triggers bot checks.
  };

  if (useHeadless) {
    options.viewport = { width: 1440, height: 1000 };
  } else {
    options.viewport = null;
  }

  // Prefer an explicit system Chrome binary over Playwright's bundled
  // "Chrome for Testing". channel:"chrome" alone can still confuse which
  // binary opened; executablePath makes it unambiguous.
  if (executablePath) {
    options.executablePath = executablePath;
  } else if (channel) {
    options.channel = channel;
  }

  try {
    const context = await chromium.launchPersistentContext(userDataDir, options);
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
    return context;
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
    return chromium.launchPersistentContext(userDataDir, options);
  }
}

/**
 * Persistent browser context for Glassdoor + ATS sessions.
 * @param {{ headless?: boolean, slowMoMs?: number, profileDir?: string }} [opts]
 */
export async function launchBrowser({ headless, slowMoMs, profileDir } = {}) {
  const env = envConfig();
  const engine = resolveBrowserEngine();
  const baseProfile = profileDir || env.profileDir;
  const userDataDir = profileDirForEngine(baseProfile, engine);
  await fs.mkdir(userDataDir, { recursive: true });
  await fs.mkdir(env.screenshotDir, { recursive: true });

  const wantHeadless = headless ?? env.headless;
  const useHeadless = wantHeadless || !canUseHeadedDisplay();

  if (engine === "firefox") {
    try {
      return await launchFirefox({ userDataDir, useHeadless, slowMoMs });
    } catch (err) {
      console.warn(
        `cv-agent: Firefox launch failed (${err.message || err}); falling back to Chromium`
      );
      const chromeDir = profileDirForEngine(baseProfile, "chromium");
      await fs.mkdir(chromeDir, { recursive: true });
      return launchChromium({
        userDataDir: chromeDir,
        useHeadless,
        slowMoMs,
      });
    }
  }

  return launchChromium({ userDataDir, useHeadless, slowMoMs });
}

export async function screenshot(page, label = "step") {
  const env = envConfig();
  await fs.mkdir(env.screenshotDir, { recursive: true });
  const safe = String(label).replace(/[^a-zA-Z0-9_-]+/g, "_").slice(0, 60);
  const file = path.join(
    env.screenshotDir,
    `${Date.now()}_${safe}.png`
  );
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
