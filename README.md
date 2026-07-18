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
npm run travel -- research "make me a lodging research plan for Amsterdam during SDF"
```

Search lodging pages with the browser tool:

```bash
npm run travel -- lodging Amsterdam
```

## CV Job Copilot

Local job-search copilot under [`cv/`](cv/): Next.js + FastAPI + MongoDB + Ollama, Docker Compose on the Legion.

```bash
cd cv
cp .env.example .env
# Requires host Ollama: ollama serve && ollama pull qwen3:8b
docker compose up --build
```

Then open http://localhost:3000 — see [cv/README.md](cv/README.md) and [cv/docs/ROADMAP.md](cv/docs/ROADMAP.md).
