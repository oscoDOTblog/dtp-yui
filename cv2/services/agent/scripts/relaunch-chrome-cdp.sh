#!/usr/bin/env bash
# Relaunch your normal Google Chrome with remote debugging so Apply Copilot
# can attach via CDP (same daily profile — cookies / Glassdoor login).
#
# WARNING: This quits ALL Google Chrome windows, then restarts Chrome.
# Only run when you are ready to restart the browser.
#
# Usage:
#   ./relaunch-chrome-cdp.sh
#   CDP_PORT=9222 ./relaunch-chrome-cdp.sh

set -euo pipefail

CDP_PORT="${CDP_PORT:-9222}"
CDP_URL="http://127.0.0.1:${CDP_PORT}"
CHROME_BIN="${CHROME_BIN:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script is macOS-first. On Linux, quit Chrome then start google-chrome with --remote-debugging-port=${CDP_PORT}" >&2
  exit 1
fi

if [[ ! -x "$CHROME_BIN" ]]; then
  echo "Chrome not found at: $CHROME_BIN" >&2
  echo "Set CHROME_BIN to your Google Chrome executable." >&2
  exit 1
fi

echo "Quitting Google Chrome (all windows)…"
osascript -e 'tell application "Google Chrome" to quit' >/dev/null 2>&1 || true

# Wait until Chrome processes using the default app are gone
for _ in $(seq 1 40); do
  if ! pgrep -xq "Google Chrome"; then
    break
  fi
  sleep 0.25
done

if pgrep -xq "Google Chrome"; then
  echo "Chrome is still running — force-quit and retry." >&2
  exit 1
fi

echo "Starting Chrome with --remote-debugging-port=${CDP_PORT} (default profile)…"
# Intentionally NO --user-data-dir so the daily session is reused.
"$CHROME_BIN" \
  --remote-debugging-port="${CDP_PORT}" \
  --no-first-run \
  --no-default-browser-check \
  >/dev/null 2>&1 &

echo "Waiting for DevTools at ${CDP_URL}/json/version …"
ready=0
for _ in $(seq 1 60); do
  if curl -fsS "${CDP_URL}/json/version" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 0.25
done

if [[ "$ready" -ne 1 ]]; then
  echo "DevTools did not become ready at ${CDP_URL}" >&2
  exit 1
fi

echo "OK — Chrome CDP ready at ${CDP_URL}"
echo "Keep this Chrome window open. Start the Apply Copilot agent with:"
echo "  CV_AGENT_BROWSER_MODE=cdp"
echo "  CV_AGENT_CDP_URL=${CDP_URL}"
curl -fsS "${CDP_URL}/json/version" | head -c 400
echo
