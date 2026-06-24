# Travel Research Workspace

This folder holds the simple "part 1" travel planning files.

The goal for this step is intentionally small:

- Keep your trip criteria in one readable JSON file.
- Ask a local Ollama model to turn a travel question into a practical research plan.
- Save the model's response as Markdown so you can review it later.

This version does not browse the web, check live prices, book anything, or call travel APIs. It is only a local planning assistant.

## Files

- `criteria.json` stores your trip preferences and constraints.
- `outputs/` stores generated research notes.

## Run

From the project root:

```bash
npm run travel:research -- "make me a lodging research plan for Amsterdam during SDF"
```

You can also run the file directly:

```bash
node travel-research.js "compare hostel vs budget hotel for this trip"
```

Make sure Ollama is running before using the CLI:

```bash
ollama serve
```

