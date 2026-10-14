import {
  humanDelay,
  resolveSearchUrl,
  normalizeApplyMode,
  APPLY_MODE_META,
  isEasyApplyMode,
} from "../config.js";
import { sanitizePageText } from "../policy.js";

/**
 * Open Glassdoor search results from applyMode / searchUrls.
 */
export async function openGlassdoorSearch(page, cfg, events) {
  const searchUrl = resolveSearchUrl(cfg);
  const applyMode = normalizeApplyMode(cfg.applyMode);
  const modeLabel = APPLY_MODE_META[applyMode]?.shortLabel || applyMode;

  await events.emit("ACTION_STARTED", {
    action: "NAVIGATE",
    target: "glassdoor_search",
    message: `Opening Glassdoor search (${modeLabel})`,
  });

  if (searchUrl) {
    await page.goto(searchUrl, { waitUntil: "domcontentloaded", timeout: 60000 });
  } else {
    const q = encodeURIComponent(cfg.query || "software engineer");
    const loc = encodeURIComponent(
      applyMode === "easyApplyRemote" || applyMode === "companyApplyRemote"
        ? "Remote"
        : cfg.location || "Oakland, CA"
    );
    const url = `https://www.glassdoor.com/Job/jobs.htm?sc.keyword=${q}&locT=C&locKeyword=${loc}`;
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
  }

  await humanDelay(cfg);
  await events.emit("ACTION_COMPLETED", {
    action: "NAVIGATE",
    message: `Glassdoor search results loaded (${modeLabel})`,
    pageUrl: page.url(),
    applyMode,
  });
}

/**
 * Collect job result card handles / metadata from the results list.
 * When Easy Apply mode, prefer cards that show an Easy Apply badge.
 */
export async function listResultCards(page, max = 10, cfg = {}) {
  const preferEasy = isEasyApplyMode(cfg.applyMode);
  const fetchLimit = preferEasy ? Math.max(max * 2, 20) : max;

  const selectors = [
    'li[data-test="jobListing"]',
    "li.react-job-listing",
    "li[data-id]",
    'article[data-test="jobListing"]',
    ".JobsList_jobListItem__lqYVv",
  ];

  let cards = [];
  for (const sel of selectors) {
    const loc = page.locator(sel);
    const count = await loc.count();
    if (count > 0) {
      cards = [];
      for (let i = 0; i < Math.min(count, fetchLimit); i += 1) {
        cards.push(loc.nth(i));
      }
      break;
    }
  }

  if (cards.length === 0) {
    const hrefs = await page.$$eval(
      'a[href*="/job-listing/"], a[href*="/Job/"]',
      (anchors) => {
        const seen = new Set();
        const out = [];
        for (const a of anchors) {
          const href = a.href;
          if (!href || seen.has(href)) continue;
          if (/job-listing|JL\d+/i.test(href) || /\/Job\//.test(href)) {
            seen.add(href);
            out.push({
              href,
              title: (a.textContent || "").trim().slice(0, 200),
            });
          }
        }
        return out.slice(0, 30);
      }
    );
    return hrefs.map((h) => ({ type: "link", ...h }));
  }

  const meta = [];
  for (let i = 0; i < cards.length; i += 1) {
    const card = cards[i];
    const title =
      (await card
        .locator('[data-test="job-title"], a[data-test="job-link"], a')
        .first()
        .textContent()
        .catch(() => "")) || "";
    const company =
      (await card
        .locator(
          '[data-test="employer-name"], .EmployerProfile_compactEmployerName__9MGcV'
        )
        .first()
        .textContent()
        .catch(() => "")) || "";
    const location =
      (await card
        .locator('[data-test="emp-location"], [data-test="job-location"]')
        .first()
        .textContent()
        .catch(() => "")) || "";
    const cardText = (await card.innerText().catch(() => "")) || "";
    const easyApply = /easy apply/i.test(cardText);
    let href = null;
    try {
      href = await card.locator("a").first().getAttribute("href");
      if (href && href.startsWith("/")) {
        href = new URL(href, page.url()).toString();
      }
    } catch {
      href = null;
    }
    meta.push({
      type: "card",
      index: i,
      title: title.trim(),
      company: company.trim(),
      location: location.trim(),
      href,
      easyApply,
      locator: card,
    });
  }

  if (preferEasy) {
    meta.sort((a, b) => Number(b.easyApply) - Number(a.easyApply));
  }
  return meta.slice(0, max);
}

export async function openResultCard(page, card, cfg) {
  if (card.type === "link" && card.href) {
    await page.goto(card.href, { waitUntil: "domcontentloaded", timeout: 60000 });
    await humanDelay(cfg);
    return page;
  }
  if (card.href) {
    await page.goto(card.href, { waitUntil: "domcontentloaded", timeout: 60000 });
    await humanDelay(cfg);
    return page;
  }
  if (card.locator) {
    await card.locator.click({ timeout: 15000 });
    await humanDelay(cfg);
    return page;
  }
  throw new Error("Unable to open result card");
}

/**
 * Scroll the job description pane so the full JD is in the DOM for extraction.
 */
export async function scrollJobDescription(page) {
  const descSelectors = [
    '[data-test="description"]',
    "#JobDescriptionContainer",
    ".JobDetails_jobDescription__",
    '[class*="JobDetails_jobDescription"]',
    '[class*="JobDetails"]',
    "article",
  ];
  for (const sel of descSelectors) {
    const loc = page.locator(sel).first();
    if ((await loc.count()) === 0) continue;
    try {
      await loc.evaluate(async (el) => {
        el.scrollTop = 0;
        const step = Math.max(200, Math.floor(el.clientHeight * 0.8));
        let guard = 0;
        while (el.scrollTop + el.clientHeight < el.scrollHeight - 20 && guard < 25) {
          el.scrollTop += step;
          guard += 1;
          await new Promise((r) => setTimeout(r, 80));
        }
        // Also scroll window in case description is not independently scrollable
        window.scrollBy(0, 400);
      });
      return true;
    } catch {
      /* try next */
    }
  }
  await page.evaluate(() => window.scrollBy(0, 800)).catch(() => {});
  return false;
}

/**
 * Extract structured job fields from an open Glassdoor listing page.
 */
export async function extractJobFromPage(page) {
  const url = page.url();
  const title =
    (
      await page
        .locator('h1[data-test="job-title"], h1.heading, h1')
        .first()
        .textContent()
        .catch(() => "")
    )?.trim() || "Untitled";

  const company =
    (
      await page
        .locator(
          '[data-test="employer-name"], [data-test="employerName"], a[data-test="employer"]'
        )
        .first()
        .textContent()
        .catch(() => "")
    )?.trim() || "Unknown";

  const location =
    (
      await page
        .locator('[data-test="location"], [data-test="job-location"]')
        .first()
        .textContent()
        .catch(() => "")
    )?.trim() || "";

  const salary =
    (
      await page
        .locator('[data-test="detailSalary"], [data-test="salary-estimate"]')
        .first()
        .textContent()
        .catch(() => "")
    )?.trim() || null;

  let description = "";
  const descSelectors = [
    '[data-test="description"]',
    "#JobDescriptionContainer",
    ".JobDetails_jobDescription__",
    '[class*="JobDetails_jobDescription"]',
    "article",
  ];
  for (const sel of descSelectors) {
    const text = await page.locator(sel).first().innerText().catch(() => "");
    if (text && text.length > description.length) description = text;
  }
  description = sanitizePageText(description);

  let applicationUrl = null;
  let easyApplyButton = false;
  const applyCandidates = await page
    .$$eval(
      'a[data-test="applyButton"], button[data-test="applyButton"], button, a[href*="greenhouse"], a[href*="lever"], a[href*="ashby"], a[href*="jobs."], a[href*="smartapply"]',
      (els) =>
        els.map((el) => ({
          href: el.href || null,
          text: (el.textContent || "").trim(),
          tag: el.tagName,
        }))
    )
    .catch(() => []);

  for (const c of applyCandidates) {
    if (/easy apply/i.test(c.text)) {
      easyApplyButton = true;
    }
    if (
      c.href &&
      /greenhouse|lever\.co|ashbyhq|myworkdayjobs|smartrecruiters|smartapply\.indeed/i.test(
        c.href
      )
    ) {
      applicationUrl = c.href;
      if (/smartapply\.indeed/i.test(c.href)) easyApplyButton = true;
      break;
    }
  }

  const sourceJobIdMatch = url.match(/(JL_\d+|jobListingId=(\d+)|jl=(\d+))/i);
  const sourceJobId =
    sourceJobIdMatch?.[2] ||
    sourceJobIdMatch?.[3] ||
    sourceJobIdMatch?.[1] ||
    null;

  const easyApply =
    easyApplyButton ||
    /smartapply\.indeed\.com/i.test(applicationUrl || "") ||
    (/glassdoor\.com/i.test(url) && !applicationUrl);

  return {
    title,
    company,
    location,
    salary,
    description,
    sourceUrl: url,
    applicationUrl,
    sourceJobId: sourceJobId ? String(sourceJobId) : null,
    easyApply,
  };
}

/**
 * Click Easy Apply / Apply and return the page that should be filled (may be a new tab).
 */
export async function clickApply(page, context, cfg, events) {
  await events.emit("ACTION_STARTED", {
    action: "CLICK",
    target: "apply",
    message: "Clicking Easy Apply / Apply",
  });

  // Prefer Easy Apply first (Glassdoor Easy Apply → Indeed Smart Apply).
  const applySelectors = [
    'button:has-text("Easy Apply")',
    'a:has-text("Easy Apply")',
    '[data-test="applyButton"]:has-text("Easy Apply")',
    '[data-test="applyButton"]',
    'button:has-text("Apply Now")',
    'a:has-text("Apply Now")',
    'button:has-text("Apply")',
    'a:has-text("Apply")',
  ];

  const pagesBefore = new Set(context.pages());
  let clicked = false;
  for (const sel of applySelectors) {
    const loc = page.locator(sel).first();
    if ((await loc.count()) > 0) {
      try {
        await loc.click({ timeout: 8000 });
        clicked = true;
        break;
      } catch {
        /* try next */
      }
    }
  }
  if (!clicked) {
    throw new Error("Apply button not found");
  }

  await humanDelay(cfg);

  const fresh = context.pages().find((p) => !pagesBefore.has(p));
  if (fresh) {
    await fresh.waitForLoadState("domcontentloaded").catch(() => {});
    await events.emit("ACTION_COMPLETED", {
      action: "CLICK",
      message: "Apply opened new tab",
      pageUrl: fresh.url(),
    });
    return fresh;
  }

  await page.waitForLoadState("domcontentloaded").catch(() => {});
  await events.emit("ACTION_COMPLETED", {
    action: "CLICK",
    message: "Apply navigated current tab",
    pageUrl: page.url(),
  });
  return page;
}
