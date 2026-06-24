# dtp-yui
Run it:
```js
node index.js "Inspect ./sample.mov and tell me the codec, duration, and resolution."
```

## Travel Research CLI

Part 1 of the travel planning toolset is a simple local research planner.

It reads `travel/criteria.json`, asks Ollama for a practical research plan, and saves the result to `travel/outputs/research.md`.

Run it:

```bash
npm run travel:research -- "make me a lodging research plan for Amsterdam during SDF"
```

Or use the generic travel entry point:

```bash
npm run travel -- research "compare hostel vs budget hotel for this trip"
```
