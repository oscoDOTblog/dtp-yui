# CV2 Minimal Terminal Agent

Run this agent from a terminal. It uses OpenClaw’s browser plugin with the `user` profile to open visible Chrome, capture Gmail’s latest inbox subject headers using an AI snapshot, and summarize them with Ollama.

## Setup

```bash
cd cv2/terminal-agent
ollama pull qwen3:4b-instruct
```

Make sure OpenClaw is configured and its `user` browser profile is already logged into Gmail.

## Run

```bash
npm start
```

Optional environment variables:

```bash
OLLAMA_MODEL=qwen3:4b-instruct
OPENCLAW_BIN=/home/argo/.openclaw/bin/openclaw
```

Each run writes `emails.json`, `summary.json`, `gmail-snapshot.txt`, `events.jsonl`, and `run.json` to `cv2/runs/<run-id>/`.
