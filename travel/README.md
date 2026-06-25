# Travel Research Workspace

This folder holds the simple "part 1" travel planning files.

The goal for this step is intentionally small:

- Keep your trip criteria in one readable JSON file.
- Ask a local Ollama model to turn a travel question into a practical research plan.
- Use a browser script to gather lodging candidates for review.
- Save the model's response as Markdown so you can review it later.

This version can open browser pages for lodging research, but it still does not book anything or treat extracted prices as final.

## Files

- `criteria.json` stores your trip preferences and constraints.
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
