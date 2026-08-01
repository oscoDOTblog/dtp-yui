import fs from "fs/promises";
import path from "path";
import { chromium } from "playwright";
import { envConfig } from "./config.js";

const USER_AGENT =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36";

const ANTI_THROTTLE_ARGS = [
  "--disable-blink-features=AutomationControlled",
  "--disable-backgrounding-occluded-windows",
  "--disable-renderer-backgrounding",
  "--disable-features=CalculateNativeWinOcclusion",
];

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
 * @param {{ headless?: boolean, slowMoMs?: number, profileDir?: string }} [opts]
 */
export async function launchBrowser({ headless, slowMoMs, profileDir } = {}) {
  const env = envConfig();
  const userDataDir = profileDir || env.profileDir;
  await fs.mkdir(userDataDir, { recursive: true });
  await fs.mkdir(env.screenshotDir, { recursive: true });

  const wantHeadless = headless ?? env.headless;
  const useHeadless = wantHeadless || !canUseHeadedDisplay();

  const args = [...ANTI_THROTTLE_ARGS];
  /** @type {import('playwright').LaunchPersistentContextOptions} */
  const options = {
    headless: useHeadless,
    slowMo: slowMoMs ?? 0,
    userAgent: USER_AGENT,
    args,
  };

  if (useHeadless) {
    options.viewport = { width: 1440, height: 1000 };
  } else {
    // Fill the real OS window so clicks land where the user expects.
    options.viewport = null;
    args.push("--window-size=1440,1000", "--window-position=40,40");
  }

  const context = await chromium.launchPersistentContext(userDataDir, options);
  return context;
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
