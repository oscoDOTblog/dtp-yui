import fs from "fs/promises";
import path from "path";
import { chromium } from "playwright";
import { envConfig } from "./config.js";

const USER_AGENT =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36";

/**
 * Persistent Chromium context for Glassdoor + ATS sessions.
 */
export async function launchBrowser({ headless, slowMoMs, profileDir } = {}) {
  const env = envConfig();
  const userDataDir = profileDir || env.profileDir;
  await fs.mkdir(userDataDir, { recursive: true });
  await fs.mkdir(env.screenshotDir, { recursive: true });

  const context = await chromium.launchPersistentContext(userDataDir, {
    headless: headless ?? env.headless,
    slowMo: slowMoMs ?? 0,
    viewport: { width: 1440, height: 1000 },
    userAgent: USER_AGENT,
    args: ["--disable-blink-features=AutomationControlled"],
  });

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
