/**
 * Browser-powered lodging search CLI.
 *
 * This is "part 2" of the travel agent project:
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
const JSON_OUTPUT_PATH = "travel/outputs/lodging-search.json";
const MARKDOWN_OUTPUT_PATH = "travel/outputs/lodging-search.md";

/**
 * The browser should not run forever if a travel site hangs or blocks us.
 */
const PAGE_TIMEOUT_MS = 30000;

/**
 * Keep the output small enough to review by hand.
 */
const MAX_CANDIDATES_PER_SOURCE = 8;

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
function buildSearchTargets({ destination, checkin, checkout, budgetText }) {
  const lodgingQuery = `${destination} lodging ${checkin} to ${checkout} ${budgetText} hostel budget hotel`;

  return [
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
function normalizeCandidate(candidate, nights) {
  const totalPrice = findBestPriceText(candidate);
  const pricePerNight = calculatePricePerNight({ priceText: totalPrice, nights });

  return {
    source: candidate.source,
    name: candidate.name || "Unknown lodging option",
    price: totalPrice,
    totalPrice,
    pricePerNight,
    nights,
    rating: candidate.rating || "",
    distance: candidate.distance || "",
    cancellation: candidate.cancellation || "",
    link: candidate.link || "",
    notes: candidate.notes || "",
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
function calculatePricePerNight({ priceText, nights }) {
  const amount = parsePriceAmount(priceText);

  if (amount === undefined) {
    return "";
  }

  const currency = detectCurrency(priceText);
  const perNight = amount / nights;

  return `${currency}${perNight.toFixed(2)}`;
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
  const page = await browser.newPage({
    userAgent:
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36",
  });

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
        normalizeCandidate(candidate, search.nights)
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
function formatMarkdown({ search, results, candidates }) {
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
    "",
    "## Notes",
    "",
    "- Results are extracted from visible browser pages.",
    "- Total prices are extracted from visible page text.",
    "- Per-night prices are estimated by dividing total price by nights.",
    "- Prices and availability can change quickly.",
    "- Review each source link manually before treating an option as real.",
    "- This tool does not book anything.",
    "",
    "## Candidates",
    "",
  ];

  if (candidates.length === 0) {
    lines.push("No candidates were extracted. The sites may have blocked automation or changed layout.");
  }

  for (const candidate of candidates) {
    lines.push(`### ${candidate.name}`);
    lines.push("");
    lines.push(`- Source: ${candidate.source}`);
    lines.push(`- Total cost: ${candidate.totalPrice || "Not found"}`);
    lines.push(`- Per night: ${candidate.pricePerNight || "Not found"}`);
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

  return `${lines.join("\n")}\n`;
}

/**
 * Save raw JSON and readable Markdown outputs.
 */
async function saveOutputs({ search, results, candidates }) {
  await fs.mkdir("travel/outputs", { recursive: true });

  await fs.writeFile(
    JSON_OUTPUT_PATH,
    JSON.stringify({ search, results, candidates }, null, 2)
  );

  await fs.writeFile(
    MARKDOWN_OUTPUT_PATH,
    formatMarkdown({ search, results, candidates })
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
  const targets = buildSearchTargets(search);

  const spinner = createSpinner("Opening browser");
  spinner.start();

  const browser = await chromium.launch({ headless: true });

  try {
    const results = [];

    for (const target of targets) {
      spinner.update(`Searching ${target.source}`);
      results.push(await searchOneTarget(browser, target, search));
    }

    const candidates = dedupeCandidates(
      results.flatMap((result) => result.candidates)
    );

    spinner.stop("Browser search complete");

    await saveOutputs({ search, results, candidates });

    console.log(`Found ${candidates.length} lodging candidates.`);
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
