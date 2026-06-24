# Travel Scripts

This folder holds the individual scripts used by the generic travel CLI.

The top-level entry point is `travel/index.js`. It routes commands to files in this folder.

Current scripts:

- `research.js` creates a local Ollama-powered research plan from `travel/criteria.json`.

Run the research command from the project root:

```bash
npm run travel -- research "make me a lodging research plan for Amsterdam during SDF"
```

You can also run the script directly while learning:

```bash
node travel/scripts/research.js "compare hostel vs budget hotel for this trip"
```

