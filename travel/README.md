# Travel Research Workspace

This folder holds the simple "part 1" travel planning files.

The goal for this step is intentionally small:

- Keep your trip criteria in one readable JSON file.
- Ask a local Ollama model to turn a travel question into a practical research plan.
- Search Reddit-related results first to discover hostel leads.
- Use a browser script to gather lodging candidates for review.
- Save the model's response as Markdown so you can review it later.

This version can open browser pages for lodging research, but it still does not book anything or treat extracted prices as final.

## Files

- `config.json` stores feature toggles for experimental steps.
- `criteria.json` stores your trip preferences and constraints.
- `reddit-seeds.json` stores editable hostel leads from community research.
- `outputs/` stores generated research notes.
- `index.js` routes travel commands to the right script.
- `scripts/` stores individual travel scripts.

## Run

From the project root:

```bash
npm run travel -- research "make me a lodging research plan for Amsterdam during SDF"
```

Search for lodging candidates:

```bash
npm run travel -- lodging Amsterdam
```

Log into Reddit once so the lodging command can reuse your browser session:

```bash
npm run travel -- reddit-login
```

This opens a visible browser. Log into Reddit, return to the terminal, and press Enter. The browser session is stored locally in `travel/browser-profile/` and ignored by git.

Reddit discovery is off by default. Turn it on in `travel/config.json`:

```json
{
  "features": {
    "redditDiscovery": true,
    "bookingBrowserSearch": true,
    "hostelworldBrowserSearch": true,
    "googleBookingBrowserSearch": true,
    "googleHostelworldBrowserSearch": true
  }
}
```

Current config toggles:

- `redditDiscovery`: discover hostel leads from Reddit/community seeds.
- `bookingBrowserSearch`: search Booking.com directly.
- `hostelworldBrowserSearch`: search Hostelworld directly.
- `googleBookingBrowserSearch`: use Google to find Booking.com result pages.
- `googleHostelworldBrowserSearch`: use Google to find Hostelworld result pages.

By default, the lodging command extracts up to 8 candidates per source and up to 5 Reddit hostel leads. You can raise those while experimenting:

```bash
TRAVEL_MAX_CANDIDATES=20 TRAVEL_MAX_REDDIT_LEADS=10 npm run travel -- lodging Amsterdam
```

If the lodging command says the browser executable is missing, install Playwright's Chromium browser:

```bash
npx playwright install chromium
```

You can also run the research script directly while learning:

```bash
node travel/scripts/research.js "compare hostel vs budget hotel for this trip"
```

Make sure Ollama is running before using the CLI:

```bash
ollama serve
```
