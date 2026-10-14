# CV2 Minimal Terminal Agent

Run this agent from a terminal. It delegates desktop/browser work directly to the installed OpenClaw runtime. OpenClaw uses the visible browser, searches Gmail, reviews one listing at a time with Ollama, writes tailored documents, fills application fields, and stops for terminal approval before submission.

## Setup

```bash
cd cv2/terminal-agent
ollama pull qwen3:8b
```

Make sure OpenClaw is configured and its desktop browser is logged into Gmail.

## Run

```bash
npm start
```

Optional environment variables:

```bash
OLLAMA_MODEL=qwen3:8b
OPENCLAW_BIN=/home/argo/.openclaw/bin/openclaw
```

Each run writes JSON checkpoints to `cv2/runs/<run-id>/` and generated Markdown documents to `cv2/generated-applications/<job-id>/`.
