/**
 * Live browser preview for Apply Copilot.
 * CDP screencast when available; otherwise periodic JPEG screenshots.
 * Watchdog falls back to poll when screencast stalls (occluded/minimized window).
 * Frames are ephemeral (not written to Mongo).
 */

import { EventEmitter } from "events";

function previewEnabled() {
  return process.env.CV_AGENT_PREVIEW !== "0";
}

function maxWidth() {
  return Number.parseInt(process.env.CV_AGENT_PREVIEW_MAX_WIDTH || "960", 10);
}

function jpegQuality() {
  return Number.parseInt(process.env.CV_AGENT_PREVIEW_QUALITY || "55", 10);
}

const STALE_FRAME_MS = 1500;
const WATCHDOG_INTERVAL_MS = 1000;

export function createPreviewController() {
  const bus = new EventEmitter();
  bus.setMaxListeners(40);

  let activePage = null;
  let cdp = null;
  let pollTimer = null;
  let watchdogTimer = null;
  let latestJpeg = null;
  let latestAt = null;
  let latestUrl = null;
  let lastFrameAt = 0;
  let running = false;
  let mode = "idle"; // screencast | poll | idle
  let preferScreencast = true;

  function publishFrame(buffer, meta = {}) {
    if (!Buffer.isBuffer(buffer) || buffer.length === 0) return;
    latestJpeg = buffer;
    latestAt = new Date().toISOString();
    lastFrameAt = Date.now();
    latestUrl = meta.pageUrl || latestUrl;
    bus.emit("frame", {
      type: "PREVIEW_FRAME",
      mimeType: "image/jpeg",
      byteLength: buffer.length,
      createdAt: latestAt,
      pageUrl: latestUrl,
      mode,
    });
  }

  async function captureOnce(page) {
    if (!page || page.isClosed()) return null;
    try {
      const buf = await page.screenshot({
        type: "jpeg",
        quality: jpegQuality(),
        fullPage: false,
      });
      const url = page.url();
      publishFrame(Buffer.from(buf), { pageUrl: url });
      return buf;
    } catch (err) {
      console.error("preview capture failed:", err.message || err);
      return null;
    }
  }

  async function stopCdp() {
    if (!cdp) return;
    try {
      await cdp.send("Page.stopScreencast").catch(() => {});
      cdp.off("Page.screencastFrame");
      await cdp.detach().catch(() => {});
    } catch {
      /* ignore */
    }
    cdp = null;
  }

  function stopPoll() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function stopWatchdog() {
    if (watchdogTimer) {
      clearInterval(watchdogTimer);
      watchdogTimer = null;
    }
  }

  async function startCdp(page) {
    const session = await page.context().newCDPSession(page);
    session.on("Page.screencastFrame", async (frame) => {
      try {
        if (pollTimer) {
          stopPoll();
          mode = "screencast";
        }
        const buf = Buffer.from(frame.data, "base64");
        mode = "screencast";
        publishFrame(buf, { pageUrl: page.url() });
        await session
          .send("Page.screencastFrameAck", { sessionId: frame.sessionId })
          .catch(() => {});
      } catch (err) {
        console.error("screencast frame error:", err.message || err);
      }
    });
    await session.send("Page.startScreencast", {
      format: "jpeg",
      quality: jpegQuality(),
      maxWidth: maxWidth(),
      maxHeight: Math.round((maxWidth() * 10) / 16),
      everyNthFrame: 1,
    });
    cdp = session;
    mode = "screencast";
    preferScreencast = true;
  }

  function startPoll(page) {
    if (pollTimer) return;
    mode = "poll";
    pollTimer = setInterval(() => {
      captureOnce(page);
    }, 450);
    captureOnce(page);
  }

  function startWatchdog() {
    stopWatchdog();
    watchdogTimer = setInterval(() => {
      if (!running || !activePage || activePage.isClosed?.()) return;
      const stale = Date.now() - lastFrameAt > STALE_FRAME_MS;
      if (stale && !pollTimer) {
        startPoll(activePage);
      }
    }, WATCHDOG_INTERVAL_MS);
  }

  async function setActivePage(page) {
    if (!previewEnabled() || !running) {
      activePage = page;
      return;
    }
    await stopCdp();
    stopPoll();
    activePage = page;
    if (!page || page.isClosed()) {
      mode = "idle";
      return;
    }

    lastFrameAt = Date.now();
    if (preferScreencast) {
      try {
        await startCdp(page);
      } catch (err) {
        console.warn(
          "CDP screencast unavailable, falling back to poll:",
          err.message || err
        );
        preferScreencast = false;
        startPoll(page);
      }
    } else {
      startPoll(page);
    }
  }

  async function start(page) {
    if (!previewEnabled()) {
      running = false;
      mode = "idle";
      return;
    }
    running = true;
    lastFrameAt = Date.now();
    await setActivePage(page);
    startWatchdog();
  }

  async function stop() {
    running = false;
    stopWatchdog();
    await stopCdp();
    stopPoll();
    activePage = null;
    mode = "idle";
  }

  function getLatestJpeg() {
    return latestJpeg;
  }

  function getMeta() {
    return {
      enabled: previewEnabled(),
      active: Boolean(running && activePage && !activePage.isClosed?.()),
      latestAt,
      pageUrl: latestUrl,
      hasFrame: Boolean(latestJpeg),
      mode,
    };
  }

  return {
    start,
    stop,
    setActivePage,
    getLatestJpeg,
    getMeta,
    on: (...args) => bus.on(...args),
    off: (...args) => bus.off(...args),
  };
}
