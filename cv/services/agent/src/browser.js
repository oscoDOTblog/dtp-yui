import fs from "fs/promises";
import path from "path";
import { chromium } from "playwright";
import { envConfig } from "./config.js";

const ANTI_THROTTLE_ARGS = [
  "--disable-blink-features=AutomationControlled",
  "--disable-backgrounding-occluded-windows",
  "--disable-renderer-backgrounding",
  "--disable-features=CalculateNativeWinOcclusion",
];

/**
 * Prefer installed Google Chrome over Playwright's "Chrome for Testing"
 * (Cloudflare / Glassdoor challenge pages fingerprint the testing build).
 * Set CV_AGENT_BROWSER_CHANNEL=chromium to force the bundled browser.
 */
export function resolveBrowserChannel() {
  const raw = (process.env.CV_AGENT_BROWSER_CHANNEL || "").trim().toLowerCase();
  if (raw === "chromium" || raw === "bundled" || raw === "0") {
    return null;
  }
  if (raw === "chrome" || raw === "msedge" || raw === "chrome-beta") {
    return raw === "chrome-beta" ? "chrome-beta" : raw;
  }
  // Default: system Chrome on macOS/Windows where users have it installed.
  if (process.platform === "darwin" || process.platform === "win32") {
    return "chrome";
  }
  return null;
}

/**
 * Headed Chromium needs a real display. Linux containers without DISPLAY
 * cannot show a window — callers should fall back to headless.
 */
export function canUseHeadedDisplay() {
  if (process.platform === "linux" && !process.env.DISPLAY) {
    return false;
  }
  return true;
}

/**
 * Persistent Chromium context for Glassdoor + ATS sessions.
 * Uses system Chrome when available (no spoofed User-Agent).
 * @param {{ headless?: boolean, slowMoMs?: number, profileDir?: string }} [opts]
 */
export async function launchBrowser({ headless, slowMoMs, profileDir } = {}) {
  const env = envConfig();
  const userDataDir = profileDir || env.profileDir;
  await fs.mkdir(userDataDir, { recursive: true });
  await fs.mkdir(env.screenshotDir, { recursive: true });

  const wantHeadless = headless ?? env.headless;
  const useHeadless = wantHeadless || !canUseHeadedDisplay();
  const channel = resolveBrowserChannel();

  const args = [...ANTI_THROTTLE_ARGS];
  /** @type {import('playwright').LaunchPersistentContextOptions} */
  const options = {
    headless: useHeadless,
    slowMo: slowMoMs ?? 0,
    args,
    // Do not set userAgent — spoofed UA vs real Chrome binary triggers bot checks.
  };

  if (useHeadless) {
    options.viewport = { width: 1440, height: 1000 };
  } else {
    options.viewport = null;
    args.push("--window-size=1440,1000", "--window-position=40,40");
  }

  if (channel) {
    options.channel = channel;
  }

  try {
    const context = await chromium.launchPersistentContext(userDataDir, options);
    if (channel) {
      console.log(`cv-agent browser: system ${channel} (persistent profile)`);
    } else {
      console.log("cv-agent browser: bundled Chromium (persistent profile)");
    }
    return context;
  } catch (err) {
    if (!channel) throw err;
    console.warn(
      `cv-agent: channel=${channel} failed (${err.message || err}); falling back to bundled Chromium`
    );
    delete options.channel;
    return chromium.launchPersistentContext(userDataDir, options);
  }
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
