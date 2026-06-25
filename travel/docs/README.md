# Travel Planning Toolset

This folder documents the travel planning toolset we are building inside `dtp-yui`.

The long-term goal is a local travel research assistant that can help plan trips, compare options, and eventually expose those abilities as MCP tools. The project should stay practical and reviewable at each step.

## Current Scope

This is still part 1: a manual travel research planner.

Today, the tool can:

- Read trip preferences from `travel/criteria.json`.
- Send a travel research request to local Ollama.
- Use the `qwen3:8b` model by default.
- Show a loading animation while Ollama is responding.
- Search Reddit-related results for hostel recommendation signals before querying lodging sites.
- Open browser pages with Playwright for lodging research.
- Extract visible lodging names, prices, distances, cancellation hints, ratings, and links when pages expose them.
- Save the generated research plan to `travel/outputs/research.md`.
- Save lodging search results to `travel/outputs/lodging-search.md` and `travel/outputs/lodging-search.json`.

Today, the tool does not:

- Guarantee live prices or availability.
- Bypass bot checks, consent pages, or site layout changes.
- Book flights, trains, lodging, or events.
- Make decisions without user review.

## Project Shape

- `travel/index.js` is the generic travel CLI entry point.
- `travel/scripts/` contains individual scripts that the CLI can route to.
- `travel/scripts/lodging-search.js` opens browser pages and extracts lodging candidates.
- `travel/scripts/research.js` creates a local Ollama-powered research plan.
- `travel/config.json` stores feature toggles for experimental steps.
- `travel/criteria.json` stores trip criteria and preferences.
- `travel/reddit-seeds.json` stores editable hostel leads from community research.
- `travel/outputs/` stores generated Markdown notes.
- `travel/docs/` stores design notes and high-level documentation.

## Commands

Run the generic travel CLI:

```bash
npm run travel
```

Run the research command through the generic entry point:

```bash
npm run travel -- research "make me a lodging research plan for Amsterdam during SDF"
```

Run the lodging browser search:

```bash
npm run travel -- lodging Amsterdam
```

Log into Reddit once for authenticated Reddit discovery:

```bash
npm run travel -- reddit-login
```

The login command opens a visible Playwright browser using the persistent profile at `travel/browser-profile/`. After you log in and press Enter in the terminal, future lodging searches reuse that browser session. The profile folder is ignored by git because it can contain cookies and local browser state.

Reddit discovery is off by default. Enable it in `travel/config.json`:

```json
{
  "features": {
    "redditDiscovery": true
  }
}
```

The lodging command extracts up to 8 candidates per source and up to 5 Reddit hostel leads by default. To inspect more:

```bash
TRAVEL_MAX_CANDIDATES=20 TRAVEL_MAX_REDDIT_LEADS=10 npm run travel -- lodging Amsterdam
```

## Browser Setup

The lodging command uses Playwright.

Install Node dependencies:

```bash
npm install
```

Install Playwright's Chromium browser:

```bash
npx playwright install chromium
```

Run the research script directly while learning:

```bash
node travel/scripts/research.js "what neighborhoods should I research for late-night dance events?"
```

## Design Principles

- Keep each step small enough to review and understand.
- Prefer local files for memory before adding databases.
- Keep generated outputs human-readable.
- Be honest about what the tool did and did not verify.
- Do not book anything automatically.
- Ask the user before changing direction or treating an option as preferred.

## Path Toward MCP

The current CLI is a learning-friendly foundation. Later, the scripts can become MCP tool handlers.

Possible future tools:

- `create_research_plan`
- `compare_options`
- `save_shortlist_item`
- `list_shortlist`
- `generate_itinerary_report`
- `search_lodging`
- `search_transport`

The likely next step is still local and simple: add a saved shortlist file so the assistant can remember options marked as `maybe`, `approved`, or `rejected`.
