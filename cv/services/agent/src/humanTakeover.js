/**
 * Detect human interaction in the headed Chromium window and pause the agent.
 * Playwright's synthetic events are also isTrusted, so we combine:
 * - behavioral signals (mousemove bursts, keydown, wheel, pointerdown)
 * - uiMode gating (ignore while ACTING + short tail after)
 */

import { AgentUiMode } from "./states.js";

const ACTING_TAIL_MS = 400;
const DEBOUNCE_MS = 3000;
const MOVE_BURST_WINDOW_MS = 400;
const MOVE_BURST_MIN = 4;

/**
 * @param {object} opts
 * @param {() => string} opts.getUiMode
 * @param {() => boolean} opts.getUserControl
 * @param {() => Promise<void>} opts.onTakeover
 */
export function createHumanTakeover({ getUiMode, getUserControl, onTakeover }) {
  let lastActingAt = 0;
  let lastTriggerAt = 0;
  let installed = false;

  function noteUiMode(mode) {
    if (mode === AgentUiMode.ACTING) {
      lastActingAt = Date.now();
    }
  }

  function shouldIgnore() {
    if (getUserControl()) return true;
    if (getUiMode() === AgentUiMode.ACTING) return true;
    if (Date.now() - lastActingAt < ACTING_TAIL_MS) return true;
    if (Date.now() - lastTriggerAt < DEBOUNCE_MS) return true;
    return false;
  }

  async function handleActivity(payload) {
    if (shouldIgnore()) return;
    lastTriggerAt = Date.now();
    try {
      await onTakeover(payload);
    } catch (err) {
      console.error("human takeover failed:", err.message || err);
    }
  }

  /**
   * Install once per browser context (covers new pages + iframes via init script).
   * @param {import('playwright').BrowserContext} context
   */
  async function install(context) {
    if (installed || !context) return;
    installed = true;

    await context.exposeBinding("__cvHumanActivity", async (_source, payload) => {
      await handleActivity(payload || {});
    });

    await context.addInitScript(
      ({ moveWindowMs, moveMin }) => {
        if (window.__cvHumanTakeoverInstalled) return;
        window.__cvHumanTakeoverInstalled = true;

        const positions = [];
        let lastReport = 0;

        function report(kind, extra = {}) {
          const now = Date.now();
          if (now - lastReport < 250 && kind === "mousemove") return;
          lastReport = now;
          try {
            window.__cvHumanActivity?.({ kind, t: now, ...extra });
          } catch {
            /* binding may not exist yet on about:blank */
          }
        }

        document.addEventListener(
          "mousemove",
          (e) => {
            const now = Date.now();
            positions.push({ x: e.clientX, y: e.clientY, t: now });
            while (positions.length && now - positions[0].t > moveWindowMs) {
              positions.shift();
            }
            const unique = new Set(
              positions.map((p) => `${Math.round(p.x / 4)},${Math.round(p.y / 4)}`)
            );
            if (unique.size >= moveMin) {
              report("mousemove", { points: unique.size });
              positions.length = 0;
            }
          },
          { passive: true, capture: true }
        );

        for (const kind of ["keydown", "wheel", "pointerdown"]) {
          document.addEventListener(
            kind,
            () => report(kind),
            { passive: true, capture: true }
          );
        }
      },
      { moveWindowMs: MOVE_BURST_WINDOW_MS, moveMin: MOVE_BURST_MIN }
    );
  }

  function reset() {
    installed = false;
    lastActingAt = 0;
    lastTriggerAt = 0;
  }

  return { install, noteUiMode, reset };
}
