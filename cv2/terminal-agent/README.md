# CV2 Single-Job Terminal Agent

Run this agent from a terminal. It uses OpenClaw’s browser plugin with the `user` profile to open visible Chrome, find the newest Gmail message with an external job link, inspect one listing, score it with Ollama, and generate text-only application documents. The application page is opened for review, but no fields are edited and nothing is submitted.

## Setup

```bash
cd cv2/terminal-agent
ollama pull qwen3:8b
```

Make sure OpenClaw is configured and its `user` browser profile is already logged into Gmail.

## Run

```bash
npm start
```

Optional environment variables:

```bash
OLLAMA_MODEL=qwen3:8b
OPENCLAW_BIN=/home/argo/.openclaw/bin/openclaw
```

Each run writes `emails.json`, `summary.json`, `gmail-snapshot.txt`, `events.jsonl`, and `run.json` to `cv2/runs/<run-id>/`.
