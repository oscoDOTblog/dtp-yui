import { humanDelay } from "../config.js";
import { sanitizePageText } from "../policy.js";

/**
 * Open Glassdoor search results from config (saved URL preferred).
 */
export async function openGlassdoorSearch(page, cfg, events) {
  await events.emit("ACTION_STARTED", {
    action: "NAVIGATE",
    target: "glassdoor_search",
    message: "Opening Glassdoor search",
  });

  if (cfg.searchUrl) {
    await page.goto(cfg.searchUrl, { waitUntil: "domcontentloaded", timeout: 60000 });
  } else {
    const q = encodeURIComponent(cfg.query || "software engineer");
    const loc = encodeURIComponent(cfg.location || "Oakland, CA");
    const url = `https://www.glassdoor.com/Job/jobs.htm?sc.keyword=${q}&locT=C&locKeyword=${loc}`;
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
  }

  await humanDelay(cfg);
  await events.emit("ACTION_COMPLETED", {
    action: "NAVIGATE",
    message: "Glassdoor search results loaded",
    pageUrl: page.url(),
  });
}

/**
 * Collect job result card handles / metadata from the results list.
 */
export async function listResultCards(page, max = 10) {
  // Glassdoor markup varies; try several known patterns.
  const selectors = [
    'li[data-test="jobListing"]',
    "li.react-job-listing",
    'li[data-id]',
    'article[data-test="jobListing"]',
    ".JobsList_jobListItem__lqYVv",
  ];

  let cards = [];
  for (const sel of selectors) {
    const loc = page.locator(sel);
    const count = await loc.count();
    if (count > 0) {
      cards = [];
      for (let i = 0; i < Math.min(count, max); i += 1) {
        cards.push(loc.nth(i));
      }
      break;
    }
  }

  if (cards.length === 0) {
    // Fallback: collect job links from the page.
    const hrefs = await page.$$eval('a[href*="/job-listing/"], a[href*="/Job/"]', (anchors) => {
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
    });
    return hrefs.map((h) => ({ type: "link", ...h }));
  }

  const meta = [];
  for (let i = 0; i < cards.length; i += 1) {
    const card = cards[i];
    const title =
      (await card.locator('[data-test="job-title"], a[data-test="job-link"], a').first().textContent().catch(() => "")) ||
      "";
    const company =
      (await card.locator('[data-test="employer-name"], .EmployerProfile_compactEmployerName__9MGcV').first().textContent().catch(() => "")) ||
      "";
    const location =
      (await card.locator('[data-test="emp-location"], [data-test="job-location"]').first().textContent().catch(() => "")) ||
      "";
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
      locator: card,
    });
  }
  return meta;
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

  // Prefer employer apply URL when present.
  let applicationUrl = null;
  const applyCandidates = await page
    .$$eval(
      'a[data-test="applyButton"], button[data-test="applyButton"], a[href*="greenhouse"], a[href*="lever"], a[href*="ashby"], a[href*="jobs."]',
      (els) =>
        els.map((el) => ({
          href: el.href || null,
          text: (el.textContent || "").trim(),
          tag: el.tagName,
        }))
    )
    .catch(() => []);

  for (const c of applyCandidates) {
    if (c.href && /greenhouse|lever\.co|ashbyhq|myworkdayjobs|smartrecruiters/i.test(c.href)) {
      applicationUrl = c.href;
      break;
    }
  }

  const sourceJobIdMatch = url.match(/(JL_\d+|jobListingId=(\d+)|jl=(\d+))/i);
  const sourceJobId =
    sourceJobIdMatch?.[2] ||
    sourceJobIdMatch?.[3] ||
    sourceJobIdMatch?.[1] ||
    null;

  return {
    title,
    company,
    location,
    salary,
    description,
    sourceUrl: url,
    applicationUrl,
    sourceJobId: sourceJobId ? String(sourceJobId) : null,
    easyApply: /glassdoor\.com/i.test(applicationUrl || url),
  };
}

/**
 * Click Apply and return the page that should be filled (may be a new tab).
 */
export async function clickApply(page, context, cfg, events) {
  await events.emit("ACTION_STARTED", {
    action: "CLICK",
    target: "apply",
    message: "Clicking Apply",
  });

  const applySelectors = [
    '[data-test="applyButton"]',
    'button:has-text("Apply Now")',
    'a:has-text("Apply Now")',
    'button:has-text("Easy Apply")',
    'a:has-text("Apply")',
    'button:has-text("Apply")',
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

  // New tab?
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
