---
name: Copilot browser preview
overview: Stream the Playwright browser viewport into Apply Copilot as a live preview panel (with fullscreen expand), so you can follow the run in one UI instead of juggling a separate Chrome window.
todos:
  - id: preview-stream-agent
    content: Add CDP/JPEG preview stream on agent (active page, /preview/latest + optional WS)
    status: completed
  - id: wire-runner-pages
    content: Start/switch/stop preview from runner as pages change
    status: completed
  - id: copilot-preview-ui
    content: BrowserPreview panel + Expand dialog on /copilot
    status: completed
  - id: docs-headless-preview
    content: Document Copilot-first headless + preview vs headed login
    status: completed
isProject: false
---

# Embed live browser preview in Apply Copilot

## Why nothing shows in Copilot today

The agent only writes occasional PNGs to disk ([`browser.js`](cv/services/agent/src/browser.js) `screenshot()`). The dashboard has no preview surface. Chrome is a separate OS window when `CV_AGENT_HEADLESS=0`.

## Approach

**CDP screencast → WebSocket frames → Copilot `<img>` panel + expand dialog.**

Works with **headless** (recommended for Copilot-first use) or headed. No noVNC for MVP.

```text
Playwright page
  → CDP Page.startScreencast (jpeg)
  → agent WS /ws  { type: "PREVIEW_FRAME", data: base64, … }
  → Copilot BrowserPreview (img) + Expand → Dialog
```

## Agent changes ([`cv/services/agent`](cv/services/agent))

1. Add [`src/preview.js`](cv/services/agent/src/preview.js):
   - `startPreview(page)` / `stopPreview()` / `setActivePage(page)`
   - Use Playwright CDP: `page.context().newCDPSession(page)` → `Page.startScreencast` with modest quality (~50–60) and max width ~960 for bandwidth
   - On `Page.screencastFrame`, emit to event bus / WS clients, then `Page.screencastFrameAck`
   - Stop screencast when run ends or page closes

2. Wire from [`runner.js`](cv/services/agent/src/runner.js):
   - After `launchBrowser`, start preview on the main page
   - On Apply tab switch (`clickApply` new page), call `setActivePage(applyPage)`
   - On return to results / run finally, stop preview

3. [`index.js`](cv/services/agent/src/index.js): broadcast `PREVIEW_FRAME` on existing WS (and skip stuffing huge base64 into Mongo event log / SSE — preview is ephemeral live-only)

4. Optional: `GET /preview/latest` JPEG fallback for poll if WS drops

5. Env knobs in [`.env.example`](cv/services/agent/.env.example):
   - `CV_AGENT_PREVIEW=1` (default on)
   - `CV_AGENT_PREVIEW_MAX_WIDTH=960`
   - Docs: for Copilot-first, set `CV_AGENT_HEADLESS=1` and watch the dashboard; use headed only for first Glassdoor login / CAPTCHA / Take control

## Web changes ([`cv/services/web/app/copilot`](cv/services/web/app/copilot))

1. New [`BrowserPreview.js`](cv/services/web/app/components/BrowserPreview.js):
   - Connect to agent WS (via existing path or add `/agent-api` upgrade note — today WS is direct `:8010/ws`; use `ws://host:8010/ws` from browser when on localhost, or add a small polling JPEG path through `/agent-api/preview/latest` so LAN/Docker works without WS proxy)
   - **Concrete choice for reliability through the Next proxy:** poll `GET /agent-api/preview/latest` every ~400ms while run is active (proxy already streams HTTP). Keep WS frames as enhancement when connecting to host agent directly; primary path = HTTP JPEG so Docker web → host agent works without WS proxy work.

2. Layout on [`copilot/page.js`](cv/services/web/app/copilot/page.js):
   - Top or left: live preview card (16:10 aspect, dark frame)
   - **Expand** opens a coss Dialog with a larger image
   - Show page URL / uiMode caption under the preview when available from `/status`

3. Idle state: placeholder (“Start a run to see the browser”)

## Docs

Update [`AGENT_SETUP.md`](cv/docs/AGENT_SETUP.md): Copilot-first = headless + in-dashboard preview; headed Chrome still available for login/CAPTCHA.

## Out of scope (later)

- Click/type inside the preview (coordinate → Playwright)
- noVNC full remote desktop
- Persisting every frame to Mongo
