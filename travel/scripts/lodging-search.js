/**
 * Browser-powered lodging search CLI.
 *
 * This is "part 2" of the travel agent project:
 * - Search Reddit-related results first to discover hostel names people mention.
 * - Open lodging/search pages in a real browser with Playwright.
 * - Collect visible names, prices, ratings, distances, cancellation hints, and links.
 * - Save the extracted candidates for human review.
 *
 * This script still does not book anything. It only gathers candidates.
 */

import { chromium } from "playwright";
import fs from "fs/promises";
import { pathToFileURL } from "url";

/**
 * The same lightweight spinner pattern used by the other CLIs.
 */
const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

/**
 * Local project paths used by this script.
 */
const CRITERIA_PATH = "travel/criteria.json";
const REDDIT_SEEDS_PATH = "travel/reddit-seeds.json";
const JSON_OUTPUT_PATH = "travel/outputs/lodging-search.json";
const MARKDOWN_OUTPUT_PATH = "travel/outputs/lodging-search.md";
const BROWSER_PROFILE_PATH = "travel/browser-profile";

/**
 * One browser identity for login and searches.
 */
const BROWSER_USER_AGENT =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36";

/**
 * Run headless by default, but allow a visible browser for debugging.
 *
 * Example:
 * TRAVEL_BROWSER_HEADLESS=0 npm run travel -- lodging Amsterdam
 */
const BROWSER_HEADLESS = process.env.TRAVEL_BROWSER_HEADLESS !== "0";

/**
 * The browser should not run forever if a travel site hangs or blocks us.
 */
const PAGE_TIMEOUT_MS = 30000;

/**
 * Keep the output small enough to review by hand by default.
 *
 * You can override this without editing code:
 * TRAVEL_MAX_CANDIDATES=20 npm run travel -- lodging Amsterdam
 */
const MAX_CANDIDATES_PER_SOURCE = Number.parseInt(
  process.env.TRAVEL_MAX_CANDIDATES || "8",
  10
);

/**
 * Keep Reddit-discovered leads small and reviewable.
 *
 * You can override this without editing code:
 * TRAVEL_MAX_REDDIT_LEADS=10 npm run travel -- lodging Amsterdam
 */
const MAX_REDDIT_LEADS = Number.parseInt(
  process.env.TRAVEL_MAX_REDDIT_LEADS || "5",
  10
);

/**
 * Reddit communities to search for hostel recommendations.
 *
 * We query old.reddit.com search pages because they are simpler to read in a
 * browser automation prototype and do not require Reddit API credentials.
 */
const REDDIT_COMMUNITIES = [
  "hostels",
  "Amsterdam",
  "Europetravel",
  "solotravel",
  "travel",
];

/**
 * Starter Reddit threads to inspect when search pages do not expose results.
 *
 * These are still discovery sources only. Any names found here become lodging
 * search leads that must be verified against Booking/Hostelworld/other sites.
 */
const REDDIT_SEED_THREADS = [
  {
    community: "hostels",
    url: "https://old.reddit.com/r/hostels/comments/1qw3hy5/best_hostels_in_amsterdam/",
  },
  {
    community: "hostels",
    url: "https://old.reddit.com/r/hostels/comments/1irkews/amsterdam_hostel_recommendations/",
  },
  {
    community: "Europetravel",
    url: "https://old.reddit.com/r/Europetravel/comments/18m7k93/hostel_recommendations_amsterdam/",
  },
  {
    community: "solotravel",
    url: "https://old.reddit.com/r/solotravel/comments/3bo28w/amsterdam_hostel_recommendations/",
  },
  {
    community: "travel",
    url: "https://old.reddit.com/r/travel/comments/fytkm/can_anyone_recommend_any_good_hostels_in_amsterdam/",
  },
  {
    community: "hostels",
    url: "https://old.reddit.com/r/hostels/comments/1fl1a7b/hostels_recommendations_for_amsterdam_and_brussels/",
  },
];

/**
 * Create a terminal progress list that writes to stderr.
 *
 * Each completed step stays visible, and only the current step animates. stderr
 * keeps status text separate from stdout, where final command output normally
 * goes.
 */
function createSpinner(label) {
  let frame = 0;
  let timer;
  let currentLabel = label;

  return {
    /**
     * Render the current in-progress line.
     */
    render() {
      process.stderr.write(
        `\r${SPINNER_FRAMES[frame++ % SPINNER_FRAMES.length]} ${currentLabel}`
      );
    },

    start() {
      if (!process.stderr.isTTY) {
        process.stderr.write(`[doing] ${currentLabel}\n`);
        return;
      }

      timer = setInterval(() => {
        this.render();
      }, 80);
    },

    /**
     * Mark the current step as complete and move to the next one.
     */
    update(nextLabel) {
      if (!process.stderr.isTTY) {
        process.stderr.write(`[done] ${currentLabel}\n`);
        process.stderr.write(`[doing] ${nextLabel}\n`);
        currentLabel = nextLabel;
        return;
      }

      process.stderr.write(`\r\x1b[K[done] ${currentLabel}\n`);
      currentLabel = nextLabel;
      frame = 0;
      this.render();
    },

    /**
     * Stop the animation and mark the final step as complete.
     */
    stop(doneLabel) {
      if (timer) {
        clearInterval(timer);
        timer = undefined;
      }

      if (!process.stderr.isTTY) {
        process.stderr.write(`[done] ${currentLabel}\n`);

        if (doneLabel && doneLabel !== currentLabel) {
          process.stderr.write(`[done] ${doneLabel}\n`);
        }

        return;
      }

      process.stderr.write(`\r\x1b[K[done] ${currentLabel}\n`);

      if (doneLabel && doneLabel !== currentLabel) {
        process.stderr.write(`[done] ${doneLabel}\n`);
      }
    },
  };
}

/**
 * Read the trip criteria so this script can use the same dates and home base
 * as the research planner.
 */
async function readCriteria() {
  const criteriaRaw = await fs.readFile(CRITERIA_PATH, "utf8");
  return JSON.parse(criteriaRaw);
}

/**
 * Launch a persistent browser profile.
 *
 * Persistent profiles save cookies and login state under travel/browser-profile.
 * That lets you log into Reddit once and reuse that session in later searches.
 */
async function launchTravelBrowserContext({ headless = BROWSER_HEADLESS } = {}) {
  return await chromium.launchPersistentContext(BROWSER_PROFILE_PATH, {
    headless,
    userAgent: BROWSER_USER_AGENT,
  });
}

/**
 * Wait until the user presses Enter in the terminal.
 */
async function waitForEnter() {
  return await new Promise((resolve) => {
    process.stdin.resume();
    process.stdin.once("data", () => {
      process.stdin.pause();
      resolve();
    });
  });
}

/**
 * Open Reddit in a visible persistent browser so the user can log in manually.
 *
 * We do not collect or store credentials. Playwright stores normal browser
 * session data in travel/browser-profile, which is ignored by git.
 */
export async function redditLoginMain() {
  const context = await launchTravelBrowserContext({ headless: false });
  const page = await context.newPage();

  try {
    await page.goto("https://www.reddit.com/login/", {
      waitUntil: "domcontentloaded",
      timeout: PAGE_TIMEOUT_MS,
    });

    console.log("A browser window is open at Reddit login.");
    console.log("Log in there, then return here and press Enter.");

    await waitForEnter();

    console.log(`Saved browser session in ${BROWSER_PROFILE_PATH}`);
  } finally {
    await context.close();
  }
}

/**
 * Read local Reddit/community seed leads.
 *
 * These are useful when Reddit blocks browser automation. Keeping them in JSON
 * makes the seed list easy to review and edit without touching code.
 */
async function readRedditSeedLeads() {
  try {
    const seedRaw = await fs.readFile(REDDIT_SEEDS_PATH, "utf8");
    const seedData = JSON.parse(seedRaw);

    return (seedData.leads || []).map((lead) => ({
      ...lead,
      source: "reddit-seed-file",
      seeded: true,
    }));
  } catch (error) {
    if (error.code === "ENOENT") {
      return [];
    }

    throw error;
  }
}

/**
 * Convert the friendly criteria date text into search-friendly defaults.
 *
 * This is intentionally simple for part 2. Later, criteria.json can store
 * machine-readable ISO dates directly.
 */
function getTripDefaults(criteria) {
  const checkin = "2026-08-25";
  const checkout = "2026-08-31";

  return {
    destination: criteria.home_base || "Amsterdam",
    checkin,
    checkout,
    nights: calculateNightCount({ checkin, checkout }),
    maxPerNight: criteria.budget?.lodging_max_per_night_eur || 70,
    budgetText: `under ${criteria.budget?.lodging_max_per_night_eur || 70} EUR per night`,
  };
}

/**
 * Count lodging nights from check-in and check-out dates.
 *
 * Example: Aug 25 check-in to Aug 31 check-out is 6 nights.
 */
function calculateNightCount({ checkin, checkout }) {
  const checkinDate = new Date(`${checkin}T00:00:00Z`);
  const checkoutDate = new Date(`${checkout}T00:00:00Z`);
  const millisecondsPerNight = 24 * 60 * 60 * 1000;
  const nights = Math.round((checkoutDate - checkinDate) / millisecondsPerNight);

  return Number.isFinite(nights) && nights > 0 ? nights : 1;
}

/**
 * Build the browser URLs this script will visit.
 *
 * We use a mix of direct site search pages and Google search result pages.
 * Direct travel pages can provide richer details, while Google can discover
 * pages when the travel site layout changes.
 */
function buildSearchTargets({
  destination,
  checkin,
  checkout,
  budgetText,
  redditLeads = [],
}) {
  const lodgingQuery = `${destination} lodging ${checkin} to ${checkout} ${budgetText} hostel budget hotel`;
  const leadTargets = redditLeads.flatMap((lead) =>
    buildTargetsForRedditLead({ lead, destination, checkin, checkout })
  );

  return [
    ...leadTargets,
    {
      source: "booking",
      url:
        "https://www.booking.com/searchresults.html?" +
        new URLSearchParams({
          ss: destination,
          checkin,
          checkout,
          group_adults: "1",
          no_rooms: "1",
          group_children: "0",
          selected_currency: "EUR",
        }).toString(),
    },
    {
      source: "hostelworld",
      url:
        "https://www.hostelworld.com/s?" +
        new URLSearchParams({
          q: destination,
          city: destination,
          type: "city",
          from: checkin,
          to: checkout,
          guests: "1",
        }).toString(),
    },
    {
      source: "google-booking",
      url:
        "https://www.google.com/search?" +
        new URLSearchParams({
          q: `site:booking.com ${lodgingQuery}`,
        }).toString(),
    },
    {
      source: "google-hostelworld",
      url:
        "https://www.google.com/search?" +
        new URLSearchParams({
          q: `site:hostelworld.com ${lodgingQuery}`,
        }).toString(),
    },
  ];
}

/**
 * Build Google searches for one Reddit-discovered hostel lead.
 *
 * The lead name is searched against Booking and Hostelworld. That lets Reddit
 * influence where we look without trusting Reddit for live price data.
 */
function buildTargetsForRedditLead({ lead, destination, checkin, checkout }) {
  const query = `${lead.name} ${destination} ${checkin} ${checkout}`;
  const sourceSafeName = lead.name.toLowerCase().replace(/[^a-z0-9]+/g, "-");

  return [
    {
      source: `reddit-lead-booking-${sourceSafeName}`,
      url:
        "https://www.google.com/search?" +
        new URLSearchParams({
          q: `site:booking.com ${query}`,
        }).toString(),
    },
    {
      source: `reddit-lead-hostelworld-${sourceSafeName}`,
      url:
        "https://www.google.com/search?" +
        new URLSearchParams({
          q: `site:hostelworld.com ${query}`,
        }).toString(),
    },
  ];
}

/**
 * Build Reddit-focused Google searches.
 *
 * Each query targets a community where travelers often discuss hostel
 * recommendations. The output is used for lead discovery, not price data.
 */
function buildRedditResearchTargets({ destination }) {
  const searchTargets = REDDIT_COMMUNITIES.map((community) => ({
    kind: "search",
    community,
    source: `reddit-${community}`,
    url:
      `https://old.reddit.com/r/${community}/search?` +
      new URLSearchParams({
        q: `${destination} hostel recommendations`,
        restrict_sr: "on",
        sort: "relevance",
        t: "all",
      }).toString(),
  }));

  const threadTargets = REDDIT_SEED_THREADS.map((thread, index) => ({
    kind: "seed-thread",
    community: thread.community,
    source: `reddit-seed-${index + 1}`,
    url: thread.url,
  }));

  return [...searchTargets, ...threadTargets];
}

/**
 * Extract the first useful regex match from a block of visible text.
 */
function firstMatch(text, patterns) {
  for (const pattern of patterns) {
    const match = text.match(pattern);

    if (match) {
      return match[0].replace(/\s+/g, " ").trim();
    }
  }

  return "";
}

/**
 * Normalize one extracted candidate so the saved JSON stays predictable.
 */
function normalizeCandidate(candidate, search) {
  const totalPrice = findBestPriceText(candidate);
  const pricePerNightAmount = calculatePricePerNightAmount({
    priceText: totalPrice,
    nights: search.nights,
  });
  const pricePerNight = formatPrice({
    amount: pricePerNightAmount,
    currency: detectCurrency(totalPrice),
  });
  const budget = getBudgetStatus({
    pricePerNightAmount,
    maxPerNight: search.maxPerNight,
  });

  return {
    source: candidate.source,
    name: candidate.name || "Unknown lodging option",
    price: totalPrice,
    totalPrice,
    pricePerNight,
    pricePerNightAmount,
    nights: search.nights,
    budget,
    rating: candidate.rating || "",
    distance: candidate.distance || "",
    cancellation: candidate.cancellation || "",
    link: candidate.link || "",
    notes: candidate.notes || "",
  };
}

/**
 * Decide whether a candidate is within the configured per-night budget.
 *
 * Unknown prices are kept in the results because the extraction may have
 * missed visible page data that a human can still check manually.
 */
function getBudgetStatus({ pricePerNightAmount, maxPerNight }) {
  if (pricePerNightAmount === undefined) {
    return {
      status: "unknown",
      label: "Unknown budget status",
      maxPerNight,
    };
  }

  if (pricePerNightAmount <= maxPerNight) {
    return {
      status: "within_budget",
      label: "Within budget",
      maxPerNight,
      differencePerNight: Number((maxPerNight - pricePerNightAmount).toFixed(2)),
    };
  }

  return {
    status: "over_budget",
    label: "Over budget",
    maxPerNight,
    differencePerNight: Number((pricePerNightAmount - maxPerNight).toFixed(2)),
  };
}

/**
 * Pick the best total-price text from a candidate.
 *
 * Booking sometimes shows a crossed-out original price before the current
 * price. When visible notes include "Current price", prefer that amount.
 */
function findBestPriceText(candidate) {
  const notes = candidate.notes || "";
  const currentPrice = firstMatch(notes, [
    /Current price\s*(?:is\s*)?(?:€|EUR)\s?\d[\d,.]*/i,
    /Current price\s*(?:is\s*)?\d[\d,.]*\s?(?:€|EUR)/i,
  ]).replace(/^Current price\s*(?:is\s*)?/i, "");

  return currentPrice || candidate.price || "";
}

/**
 * Turn price text like "€ 562" into a number we can divide by nights.
 */
function parsePriceAmount(priceText) {
  let numericText = priceText
    .replace(/[^\d,.-]/g, "")
    .replace(/^-/, "");

  const hasComma = numericText.includes(",");
  const hasDot = numericText.includes(".");

  if (hasComma && hasDot) {
    const lastComma = numericText.lastIndexOf(",");
    const lastDot = numericText.lastIndexOf(".");
    const decimalSeparator = lastComma > lastDot ? "," : ".";
    const thousandsSeparator = decimalSeparator === "," ? "." : ",";

    numericText = numericText
      .replaceAll(thousandsSeparator, "")
      .replace(decimalSeparator, ".");
  } else if (hasComma) {
    numericText = /,\d{3}$/.test(numericText)
      ? numericText.replaceAll(",", "")
      : numericText.replace(",", ".");
  } else if (hasDot && /\.\d{3}$/.test(numericText)) {
    numericText = numericText.replaceAll(".", "");
  }

  const amount = Number.parseFloat(numericText);

  return Number.isFinite(amount) ? amount : undefined;
}

/**
 * Preserve the rough currency label from the extracted price text.
 */
function detectCurrency(priceText) {
  if (/EUR/i.test(priceText) || /€/.test(priceText)) {
    return "€";
  }

  return "";
}

/**
 * Estimate the per-night price from a visible total price.
 *
 * This is an estimate because travel sites may include taxes, discounts, or
 * fees differently. The report labels it clearly as per night.
 */
function calculatePricePerNightAmount({ priceText, nights }) {
  const amount = parsePriceAmount(priceText);

  if (amount === undefined) {
    return undefined;
  }

  return amount / nights;
}

/**
 * Format a numeric amount back into display text.
 */
function formatPrice({ amount, currency }) {
  if (amount === undefined) {
    return "";
  }

  return `${currency}${amount.toFixed(2)}`;
}

/**
 * Remove repeated candidates.
 *
 * Search pages often show the same property more than once, especially when
 * Google results and direct travel pages overlap.
 */
function dedupeCandidates(candidates) {
  const seen = new Set();
  const deduped = [];

  for (const candidate of candidates) {
    const key = `${candidate.name.toLowerCase()}|${candidate.link}`;

    if (seen.has(key)) {
      continue;
    }

    seen.add(key);
    deduped.push(candidate);
  }

  return deduped;
}

/**
 * Remove repeated Reddit hostel leads.
 */
function dedupeRedditLeads(leads) {
  const seen = new Set();
  const deduped = [];

  for (const lead of leads) {
    const key = lead.name.toLowerCase();

    if (seen.has(key)) {
      continue;
    }

    seen.add(key);
    deduped.push(lead);
  }

  return deduped;
}

/**
 * Try to find likely hostel names in Reddit search result text.
 *
 * This is intentionally heuristic. It gives us leads to verify on lodging
 * sites, not final facts. Later, Ollama can help extract names more flexibly.
 */
function extractLikelyHostelNames(text) {
  const names = new Set();
  const patterns = [
    /\b(?:ClinkNOORD|Clink\s+NOORD)\b/gi,
    /\b(?:Flying Pig Downtown|Flying Pig Uptown|The Flying Pig)\b/gi,
    /\b(?:Stayokay Amsterdam Vondelpark|Stayokay Vondelpark|Stayokay Amsterdam)\b/gi,
    /\b(?:Cocomama|Ecomama)\b/gi,
    /\b(?:MEININGER Hotel Amsterdam City West|MEININGER Amsterdam)\b/gi,
    /\b(?:Generator Amsterdam)\b/gi,
    /\b(?:Hans Brinker Hostel|Hans Brinker)\b/gi,
    /\b(?:The Bulldog|Bulldog Hostel)\b/gi,
    /\b(?:St Christopher'?s at The Winston|St Christopher'?s)\b/gi,
    /\b(?:This Ho\(s\)tel|This Hostel)\b/gi,
    /\b(?:Shelter Jordan|Shelter City)\b/gi,
    /\b(?:Durty Nelly'?s Inn|Durty Nelly'?s)\b/gi,
    /\b(?:The Bee Hostel|Bee Hostel)\b/gi,
    /\b(?:CityHub Amsterdam|CityHub)\b/gi,
  ];

  for (const pattern of patterns) {
    for (const match of text.matchAll(pattern)) {
      names.add(match[0].replace(/\s+/g, " ").trim());
    }
  }

  return [...names];
}

/**
 * Extract Reddit search result snippets from Google.
 */
async function extractRedditSignals(page, target) {
  return await page.evaluate(
    ({ target }) => {
      if (target.kind === "seed-thread") {
        return [
          {
            source: target.source,
            community: target.community,
            title: document.title || target.url,
            snippet: (document.body?.innerText || "").replace(/\s+/g, " ").slice(0, 5000),
            link: target.url,
          },
        ];
      }

      const searchResults = Array.from(
        document.querySelectorAll(".search-result, .thing")
      );

      if (searchResults.length) {
        return searchResults
          .map((result) => {
            const anchor =
              result.querySelector("a.search-title") ||
              result.querySelector("a.title") ||
              result.querySelector("a[href]");
            const href = anchor?.href || "";
            const title = anchor?.textContent?.trim() || "";
            const text = (result.innerText || "")
              .replace(/\s+/g, " ")
              .trim();

            return {
              source: target.source,
              community: target.community,
              title,
              snippet: text.slice(0, 500),
              link: href,
            };
          })
          .filter((signal) => signal.title && /reddit\.com\/r\//i.test(signal.link))
          .slice(0, 5);
      }

      const links = Array.from(document.querySelectorAll("a[href]"));

      return links
        .map((anchor) => {
          const href = anchor.href || "";
          const container = anchor.closest("div") || anchor;
          const text = (container.innerText || anchor.innerText || "")
            .replace(/\s+/g, " ")
            .trim();

          return {
            source: target.source,
            community: target.community,
            title: (anchor.innerText || "").split("\n")[0]?.trim() || "",
            snippet: text.slice(0, 500),
            link: href,
          };
        })
        .filter((signal) => {
          return (
            signal.title &&
            /reddit\.com\/r\//i.test(signal.link) &&
            !/\/search\?/i.test(signal.link)
          );
        })
        .slice(0, 5);
    },
    { target }
  );
}

/**
 * Open one Reddit-focused search page and extract recommendation signals.
 */
async function researchOneRedditTarget(browser, target) {
  const page = await browser.newPage();

  page.setDefaultTimeout(PAGE_TIMEOUT_MS);

  try {
    await page.goto(target.url, {
      waitUntil: "domcontentloaded",
      timeout: PAGE_TIMEOUT_MS,
    });

    await page.waitForTimeout(1500);

    const signals = await extractRedditSignals(page, target);
    const leads = signals.flatMap((signal) => {
      return extractLikelyHostelNames(`${signal.title} ${signal.snippet}`).map(
        (name) => ({
          name,
          source: target.source,
          community: target.community,
          evidenceTitle: signal.title,
          evidenceLink: signal.link,
        })
      );
    });

    return {
      ...target,
      ok: true,
      signals,
      leads,
    };
  } catch (error) {
    return {
      ...target,
      ok: false,
      error: error.message,
      signals: [],
      leads: [],
    };
  } finally {
    await page.close();
  }
}

/**
 * Search Reddit-related results before lodging sites.
 */
async function researchRedditLeads(browser, search) {
  const targets = buildRedditResearchTargets(search);
  const results = [];
  const seedLeads = await readRedditSeedLeads();

  for (const target of targets) {
    results.push(await researchOneRedditTarget(browser, target));
  }

  const leads = dedupeRedditLeads(
    [...results.flatMap((result) => result.leads), ...seedLeads]
  ).slice(0, MAX_REDDIT_LEADS);

  return {
    targets,
    results,
    seedLeads,
    leads,
  };
}

/**
 * Extract Booking.com-style property cards from the current page.
 *
 * The selectors are intentionally based on visible page structure. If Booking
 * changes its markup or blocks automation, this function may return no items.
 */
async function extractBookingCandidates(page, source) {
  return await page.evaluate(
    ({ source, maxCandidates }) => {
      const cards = Array.from(
        document.querySelectorAll('[data-testid="property-card"]')
      ).slice(0, maxCandidates);

      return cards.map((card) => {
        const text = card.innerText || "";
        const anchor = card.querySelector('a[href*="/hotel/"], a[href]');
        const name =
          card.querySelector('[data-testid="title"]')?.textContent?.trim() ||
          anchor?.textContent?.trim() ||
          "";

        return {
          source,
          name,
          price:
            text.match(/(?:€|EUR)\s?\d[\d,.]*/)?.[0] ||
            text.match(/\d[\d,.]*\s?(?:€|EUR)/)?.[0] ||
            "",
          rating:
            text.match(/\b\d(?:\.\d)?\b(?=\s*(?:Scored|Very good|Good|Pleasant|Superb|Wonderful|Exceptional))/i)?.[0] ||
            "",
          distance:
            text.match(/\b\d+(?:\.\d+)?\s?(?:km|miles?|mi)\s+from\b[^.\n]*/i)?.[0] ||
            "",
          cancellation: /free cancellation|flexible cancellation|refundable/i.test(text)
            ? text.match(/[^.\n]*(?:free cancellation|flexible cancellation|refundable)[^.\n]*/i)?.[0] || "Cancellation mentioned"
            : "",
          link: anchor?.href || "",
          notes: text.slice(0, 500),
        };
      });
    },
    { source, maxCandidates: MAX_CANDIDATES_PER_SOURCE }
  );
}

/**
 * Extract Hostelworld-style property cards from the current page.
 *
 * Hostelworld markup changes over time, so this uses several broad selectors
 * and then keeps cards that have visible lodging-like text.
 */
async function extractHostelworldCandidates(page, source) {
  return await page.evaluate(
    ({ source, maxCandidates }) => {
      const possibleCards = Array.from(
        document.querySelectorAll(
          '[data-testid*="property"], .property-card, .property-listing, a[href*="/hosteldetails.php"], a[href*="/p/"]'
        )
      );

      return possibleCards
        .map((card) => {
          const container = card.closest("article, section, div") || card;
          const text = container.innerText || card.textContent || "";
          const anchor = container.querySelector("a[href]") || card.closest("a[href]");
          const heading = container.querySelector("h2, h3, [class*='name']");

          return {
            source,
            name: heading?.textContent?.trim() || card.textContent?.trim() || "",
            price:
              text.match(/(?:€|EUR)\s?\d[\d,.]*/)?.[0] ||
              text.match(/\d[\d,.]*\s?(?:€|EUR)/)?.[0] ||
              "",
            rating: text.match(/\b\d(?:\.\d)?\b(?=\s*(?:\/10|rating|Rated))/i)?.[0] || "",
            distance:
              text.match(/\b\d+(?:\.\d+)?\s?(?:km|miles?|mi)\b[^.\n]*/i)?.[0] || "",
            cancellation: /free cancellation|flexible|refundable/i.test(text)
              ? text.match(/[^.\n]*(?:free cancellation|flexible|refundable)[^.\n]*/i)?.[0] || "Cancellation mentioned"
              : "",
            link: anchor?.href || "",
            notes: text.slice(0, 500),
          };
        })
        .filter((candidate) => candidate.name || candidate.price || candidate.rating)
        .slice(0, maxCandidates);
    },
    { source, maxCandidates: MAX_CANDIDATES_PER_SOURCE }
  );
}

/**
 * Extract Google result links that point at Booking or Hostelworld.
 *
 * Google may show consent pages or bot checks. When that happens, this returns
 * no candidates and the saved report will make that visible.
 */
async function extractGoogleCandidates(page, source) {
  return await page.evaluate(
    ({ source, maxCandidates }) => {
      const links = Array.from(document.querySelectorAll("a[href]"));

      return links
        .map((anchor) => {
          const href = anchor.href || "";
          const text = anchor.innerText || "";

          return {
            source,
            name: text.split("\n")[0]?.trim() || "",
            price:
              text.match(/(?:€|EUR)\s?\d[\d,.]*/)?.[0] ||
              text.match(/\d[\d,.]*\s?(?:€|EUR)/)?.[0] ||
              "",
            rating: text.match(/\b\d(?:\.\d)?\b(?=\s*(?:\/10|stars?|rating|reviews?))/i)?.[0] || "",
            distance:
              text.match(/\b\d+(?:\.\d+)?\s?(?:km|miles?|mi)\b[^.\n]*/i)?.[0] || "",
            cancellation: /free cancellation|flexible|refundable/i.test(text)
              ? text.match(/[^.\n]*(?:free cancellation|flexible|refundable)[^.\n]*/i)?.[0] || "Cancellation mentioned"
              : "",
            link: href,
            notes: text.slice(0, 500),
          };
        })
        .filter((candidate) => {
          return (
            candidate.name &&
            /booking\.com|hostelworld\.com/i.test(candidate.link) &&
            !/google\.com\/search/i.test(candidate.link)
          );
        })
        .slice(0, maxCandidates);
    },
    { source, maxCandidates: MAX_CANDIDATES_PER_SOURCE }
  );
}

/**
 * Choose the extraction strategy based on which page we opened.
 */
async function extractCandidatesForSource(page, source) {
  if (source === "booking") {
    return await extractBookingCandidates(page, source);
  }

  if (source === "hostelworld") {
    return await extractHostelworldCandidates(page, source);
  }

  return await extractGoogleCandidates(page, source);
}

/**
 * Open one browser page and extract lodging candidates from it.
 */
async function searchOneTarget(browser, target, search) {
  const page = await browser.newPage();

  page.setDefaultTimeout(PAGE_TIMEOUT_MS);

  try {
    await page.goto(target.url, {
      waitUntil: "domcontentloaded",
      timeout: PAGE_TIMEOUT_MS,
    });

    /**
     * Give client-side pages a short moment to render cards.
     */
    await page.waitForTimeout(2500);

    const candidates = await extractCandidatesForSource(page, target.source);

    return {
      source: target.source,
      url: target.url,
      ok: true,
      candidates: candidates.map((candidate) =>
        normalizeCandidate(candidate, search)
      ),
    };
  } catch (error) {
    return {
      source: target.source,
      url: target.url,
      ok: false,
      error: error.message,
      candidates: [],
    };
  } finally {
    await page.close();
  }
}

/**
 * Format candidates as Markdown so the output is easy to read.
 */
function formatMarkdown({ search, redditResearch, results, candidates }) {
  const lines = [
    "# Lodging Search",
    "",
    "## Search",
    "",
    `- Destination: ${search.destination}`,
    `- Check-in: ${search.checkin}`,
    `- Check-out: ${search.checkout}`,
    `- Nights: ${search.nights}`,
    `- Budget: ${search.budgetText}`,
    `- Candidate limit per source: ${MAX_CANDIDATES_PER_SOURCE}`,
    `- Reddit lead limit: ${MAX_REDDIT_LEADS}`,
    "",
    "## Notes",
    "",
    "- Results are extracted from visible browser pages.",
    "- Total prices are extracted from visible page text.",
    "- Per-night prices are estimated by dividing total price by nights.",
    "- Prices and availability can change quickly.",
    "- Reddit leads are discovery hints only; lodging pages are used for prices.",
    "- Review each source link manually before treating an option as real.",
    "- This tool does not book anything.",
    "",
  ];

  lines.push("## Reddit Discovery");
  lines.push("");

  if (!redditResearch?.leads?.length) {
    lines.push("No notable hostel leads were extracted from Reddit search results.");
    lines.push("");
  } else {
    for (const lead of redditResearch.leads) {
      lines.push(`- ${lead.name} from r/${lead.community}`);
      lines.push(`  Evidence: ${lead.evidenceTitle}`);
      lines.push(`  Link: ${lead.evidenceLink}`);
    }

    lines.push("");
  }

  lines.push("## Candidates");
  lines.push("");

  if (candidates.length === 0) {
    lines.push("No candidates were extracted. The sites may have blocked automation or changed layout.");
  }

  for (const candidate of candidates) {
    lines.push(`### ${candidate.name}`);
    lines.push("");
    lines.push(`- Source: ${candidate.source}`);
    lines.push(`- Total cost: ${candidate.totalPrice || "Not found"}`);
    lines.push(`- Per night: ${candidate.pricePerNight || "Not found"}`);
    lines.push(`- Budget status: ${formatBudgetStatus(candidate.budget)}`);
    lines.push(`- Rating: ${candidate.rating || "Not found"}`);
    lines.push(`- Distance: ${candidate.distance || "Not found"}`);
    lines.push(`- Cancellation: ${candidate.cancellation || "Not found"}`);
    lines.push(`- Link: ${candidate.link || "Not found"}`);
    lines.push("");
  }

  lines.push("## Source Status");
  lines.push("");

  for (const result of results) {
    if (!result.ok) {
      lines.push(`- ${result.source}: failed - ${result.error}`);
      continue;
    }

    lines.push(
      `- ${result.source}: ok, ${result.candidates.length} candidates extracted`
    );
  }

  lines.push("");
  lines.push("## Reddit Source Status");
  lines.push("");

  for (const result of redditResearch?.results || []) {
    if (!result.ok) {
      lines.push(`- r/${result.community}: failed - ${result.error}`);
      continue;
    }

    lines.push(
      `- r/${result.community}: ok, ${result.signals.length} signals, ${result.leads.length} leads`
    );
  }

  return `${lines.join("\n")}\n`;
}

/**
 * Turn the structured budget status into a readable Markdown line.
 */
function formatBudgetStatus(budget) {
  if (!budget || budget.status === "unknown") {
    return "Unknown";
  }

  if (budget.status === "within_budget") {
    return `Within budget (${budget.differencePerNight.toFixed(2)} EUR/night under max)`;
  }

  return `Over budget (${budget.differencePerNight.toFixed(2)} EUR/night over max)`;
}

/**
 * Save raw JSON and readable Markdown outputs.
 */
async function saveOutputs({ search, redditResearch, results, candidates }) {
  await fs.mkdir("travel/outputs", { recursive: true });

  await fs.writeFile(
    JSON_OUTPUT_PATH,
    JSON.stringify({ search, redditResearch, results, candidates }, null, 2)
  );

  await fs.writeFile(
    MARKDOWN_OUTPUT_PATH,
    formatMarkdown({ search, redditResearch, results, candidates })
  );
}

/**
 * Main command-line entry point.
 *
 * For now the argument is optional. If omitted, the script uses criteria.json.
 * If provided, the argument becomes the destination text.
 */
export async function main(args = process.argv.slice(2)) {
  const criteria = await readCriteria();
  const defaults = getTripDefaults(criteria);
  const destination = args.join(" ").trim() || defaults.destination;
  const search = { ...defaults, destination };

  const spinner = createSpinner("Opening browser");
  spinner.start();

  const browser = await launchTravelBrowserContext();

  try {
    spinner.update("Researching Reddit leads");
    const redditResearch = await researchRedditLeads(browser, search);
    const targets = buildSearchTargets({
      ...search,
      redditLeads: redditResearch.leads,
    });
    const results = [];

    for (const target of targets) {
      spinner.update(`Searching ${target.source}`);
      results.push(await searchOneTarget(browser, target, search));
    }

    const candidates = dedupeCandidates(
      results.flatMap((result) => result.candidates)
    );

    spinner.stop("Browser search complete");

    await saveOutputs({ search, redditResearch, results, candidates });

    console.log(`Found ${candidates.length} lodging candidates.`);
    console.log(`Found ${redditResearch.leads.length} Reddit hostel leads.`);
    console.log(`Saved JSON to ${JSON_OUTPUT_PATH}`);
    console.log(`Saved Markdown to ${MARKDOWN_OUTPUT_PATH}`);
  } finally {
    await browser.close();
  }
}

/**
 * Keep direct script errors readable.
 */
function handleError(error) {
  console.error("\nLodging search failed:");
  console.error(error.message);
  console.error("");
  console.error("If Playwright browsers are missing, run:");
  console.error("npx playwright install chromium");
  process.exitCode = 1;
}

/**
 * Run only when this script is executed directly.
 */
if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(handleError);
}
