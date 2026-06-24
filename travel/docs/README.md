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
- Save the generated research plan to `travel/outputs/research.md`.

Today, the tool does not:

- Browse travel websites.
- Check live prices.
- Scrape booking pages.
- Book flights, trains, lodging, or events.
- Make decisions without user review.

## Project Shape

- `travel/index.js` is the generic travel CLI entry point.
- `travel/scripts/` contains individual scripts that the CLI can route to.
- `travel/scripts/research.js` creates a local Ollama-powered research plan.
- `travel/criteria.json` stores trip criteria and preferences.
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
