/**
 * Live browser preview for Apply Copilot.
 * CDP screencast when available; otherwise periodic JPEG screenshots.
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

export function createPreviewController() {
  const bus = new EventEmitter();
  bus.setMaxListeners(40);

  let activePage = null;
  let cdp = null;
  let pollTimer = null;
  let latestJpeg = null;
  let latestAt = null;
  let latestUrl = null;
  let running = false;

  function publishFrame(buffer, meta = {}) {
    if (!Buffer.isBuffer(buffer) || buffer.length === 0) return;
    latestJpeg = buffer;
    latestAt = new Date().toISOString();
    latestUrl = meta.pageUrl || latestUrl;
    bus.emit("frame", {
      type: "PREVIEW_FRAME",
      mimeType: "image/jpeg",
      byteLength: buffer.length,
      createdAt: latestAt,
      pageUrl: latestUrl,
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

  async function startCdp(page) {
    const session = await page.context().newCDPSession(page);
    session.on("Page.screencastFrame", async (frame) => {
      try {
        const buf = Buffer.from(frame.data, "base64");
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
  }

  function startPoll(page) {
    stopPoll();
    pollTimer = setInterval(() => {
      captureOnce(page);
    }, 450);
    captureOnce(page);
  }

  async function setActivePage(page) {
    if (!previewEnabled() || !running) {
      activePage = page;
      return;
    }
    await stopCdp();
    stopPoll();
    activePage = page;
    if (!page || page.isClosed()) return;

    try {
      await startCdp(page);
    } catch (err) {
      console.warn(
        "CDP screencast unavailable, falling back to poll:",
        err.message || err
      );
      startPoll(page);
    }
  }

  async function start(page) {
    if (!previewEnabled()) {
      running = false;
      return;
    }
    running = true;
    await setActivePage(page);
  }

  async function stop() {
    running = false;
    await stopCdp();
    stopPoll();
    activePage = null;
    // Keep last frame briefly so UI can show final state; clear after stop
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
