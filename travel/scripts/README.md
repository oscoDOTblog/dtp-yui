# Travel Scripts

This folder holds the individual scripts used by the generic travel CLI.

The top-level entry point is `travel/index.js`. It routes commands to files in this folder.

Current scripts:

- `lodging-search.js` opens browser pages and extracts lodging candidates.
- `research.js` creates a local Ollama-powered research plan from `travel/criteria.json`.

Run the lodging command from the project root:

```bash
npm run travel -- lodging Amsterdam
```

Log into Reddit once:

```bash
npm run travel -- reddit-login
```

Discovery/search sources are off by default. Enable only the ones you want in `travel/config.json`:

```json
{
  "features": {
    "redditDiscovery": true,
    "googlePlacesDiscovery": true,
    "bookingBrowserSearch": true,
    "hostelworldBrowserSearch": true,
    "googleBookingBrowserSearch": true,
    "googleHostelworldBrowserSearch": true
  },
  "googlePlaces": {
    "anchorText": "Summer Dance Forever Amsterdam venue",
    "radiusMiles": 1.5,
    "includedTypes": ["lodging"],
    "maxResultCount": 10,
    "minRating": 0
  }
}
```

Google Places also needs an API key in your shell:

```bash
export GOOGLE_MAPS_API_KEY="your-key"
```

Or put it in `.env.local` at the project root:

```bash
GOOGLE_MAPS_API_KEY=your-key
```

`.env.local` is ignored by git.

Change the per-source result limit and Reddit lead limit:

```bash
TRAVEL_MAX_CANDIDATES=20 TRAVEL_MAX_REDDIT_LEADS=10 npm run travel -- lodging Amsterdam
```

If Playwright cannot find Chromium, run:

```bash
npx playwright install chromium
```

Run the research command from the project root:

```bash
npm run travel -- research "make me a lodging research plan for Amsterdam during SDF"
```

You can also run the script directly while learning:

```bash
node travel/scripts/research.js "compare hostel vs budget hotel for this trip"
```
