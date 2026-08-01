import http from "http";
import { WebSocketServer } from "ws";
import { createApiClient } from "./apiClient.js";
import { canUseHeadedDisplay } from "./browser.js";
import { createEventBus } from "./eventBus.js";
import { createInputBroker } from "./inputBroker.js";
import { createPreviewController } from "./preview.js";
import { createRunner } from "./runner.js";
import { envConfig, loadAgentConfig, loadDotEnv } from "./config.js";

await loadDotEnv();

const env = envConfig();
const api = createApiClient(env.apiBase);
const events = createEventBus({ api });
const inputBroker = createInputBroker();
const preview = createPreviewController();
const runner = createRunner({ api, events, inputBroker, preview });

const sseClients = new Set();
const wsClients = new Set();

events.on("event", (event) => {
  if (event.type === "PREVIEW_FRAME") return;
  const payload = `data: ${JSON.stringify(event)}\n\n`;
  for (const res of sseClients) {
    try {
      res.write(payload);
    } catch {
      sseClients.delete(res);
    }
  }
  const msg = JSON.stringify(event);
  for (const ws of wsClients) {
    if (ws.readyState === 1) {
      try {
        ws.send(msg);
      } catch {
        wsClients.delete(ws);
      }
    }
  }
});

preview.on("frame", (meta) => {
  const msg = JSON.stringify(meta);
  for (const ws of wsClients) {
    if (ws.readyState === 1) {
      try {
        ws.send(msg);
      } catch {
        wsClients.delete(ws);
      }
    }
  }
});

function readJson(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      if (!chunks.length) return resolve({});
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString("utf8")));
      } catch (err) {
        reject(err);
      }
    });
    req.on("error", reject);
  });
}

function sendJson(res, status, body) {
  const data = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  });
  res.end(data);
}

async function handleRequest(req, res) {
  const url = new URL(req.url || "/", `http://127.0.0.1:${env.port}`);
  const { pathname } = url;

  if (req.method === "OPTIONS") {
    res.writeHead(204, {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    });
    res.end();
    return;
  }

  try {
    if (req.method === "GET" && pathname === "/health") {
      let apiOk = false;
      try {
        await api.health();
        apiOk = true;
      } catch {
        apiOk = false;
      }
      return sendJson(res, 200, {
        ok: true,
        service: "cv-agent",
        apiOk,
        headless: env.headless,
        headedDefault: !env.headless,
        canUseHeadedDisplay: canUseHeadedDisplay(),
        preview: preview.getMeta(),
        status: runner.getStatus(),
      });
    }

    if (req.method === "GET" && pathname === "/config") {
      const cfg = await loadAgentConfig();
      return sendJson(res, 200, cfg);
    }

    if (req.method === "GET" && pathname === "/status") {
      return sendJson(res, 200, runner.getStatus());
    }

    if (req.method === "GET" && pathname === "/preview/latest") {
      const jpeg = preview.getLatestJpeg();
      if (!jpeg) {
        res.writeHead(404, {
          "Content-Type": "application/json",
          "Access-Control-Allow-Origin": "*",
          "Cache-Control": "no-store",
        });
        res.end(JSON.stringify({ detail: "No preview frame yet" }));
        return;
      }
      const meta = preview.getMeta();
      res.writeHead(200, {
        "Content-Type": "image/jpeg",
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "X-Preview-At": meta.latestAt || "",
        "X-Preview-Url": meta.pageUrl || "",
      });
      res.end(jpeg);
      return;
    }

    if (req.method === "GET" && pathname === "/preview/meta") {
      return sendJson(res, 200, preview.getMeta());
    }

    if (req.method === "GET" && pathname === "/events/stream") {
      res.writeHead(200, {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
        "Access-Control-Allow-Origin": "*",
      });
      res.write(
        `data: ${JSON.stringify({ type: "CONNECTED", createdAt: new Date().toISOString() })}\n\n`
      );
      sseClients.add(res);
      req.on("close", () => sseClients.delete(res));
      return;
    }

    if (req.method === "POST" && pathname === "/runs/start") {
      if (runner.getStatus().running) {
        return sendJson(res, 409, { detail: "Run already in progress" });
      }
      const body = await readJson(req);
      runner.start(body).catch((err) => {
        console.error("run failed:", err);
      });
      return sendJson(res, 202, { accepted: true, status: runner.getStatus() });
    }

    if (req.method === "POST" && pathname === "/control/pause") {
      await runner.controls.pauseNow();
      return sendJson(res, 200, runner.getStatus());
    }
    if (req.method === "POST" && pathname === "/control/pause-after") {
      runner.controls.pauseAfterAction();
      return sendJson(res, 200, runner.getStatus());
    }
    if (req.method === "POST" && pathname === "/control/resume") {
      await runner.controls.resume();
      return sendJson(res, 200, runner.getStatus());
    }
    if (req.method === "POST" && pathname === "/control/take-control") {
      await runner.controls.takeControl();
      return sendJson(res, 200, runner.getStatus());
    }
    if (req.method === "POST" && pathname === "/control/return-control") {
      await runner.controls.returnControl();
      return sendJson(res, 200, runner.getStatus());
    }
    if (req.method === "POST" && pathname === "/control/focus-window") {
      try {
        await runner.controls.focusWindow();
        return sendJson(res, 200, runner.getStatus());
      } catch (err) {
        return sendJson(res, 409, {
          detail: err.message || String(err),
          status: runner.getStatus(),
        });
      }
    }
    if (req.method === "POST" && pathname === "/control/abort") {
      await runner.controls.abort();
      return sendJson(res, 200, runner.getStatus());
    }
    if (req.method === "POST" && pathname === "/control/skip") {
      await runner.controls.skipJob();
      return sendJson(res, 200, runner.getStatus());
    }
    if (req.method === "POST" && pathname === "/control/approve-submit") {
      await runner.controls.approveSubmit();
      return sendJson(res, 200, runner.getStatus());
    }
    if (req.method === "POST" && pathname === "/control/reject-submit") {
      await runner.controls.rejectSubmit();
      return sendJson(res, 200, runner.getStatus());
    }

    if (req.method === "POST" && pathname === "/input/resolve") {
      const body = await readJson(req);
      if (!body.requestId) {
        return sendJson(res, 400, { detail: "requestId required" });
      }
      const ok = runner.resolveInput(body.requestId, body);
      return sendJson(res, 200, { ok, status: runner.getStatus() });
    }

    sendJson(res, 404, { detail: "Not found" });
  } catch (err) {
    console.error(err);
    sendJson(res, 500, { detail: err.message || String(err) });
  }
}

const server = http.createServer(handleRequest);
const wss = new WebSocketServer({ server, path: "/ws" });

wss.on("connection", (ws) => {
  wsClients.add(ws);
  ws.send(
    JSON.stringify({
      type: "CONNECTED",
      createdAt: new Date().toISOString(),
      status: runner.getStatus(),
      preview: preview.getMeta(),
    })
  );
  ws.on("close", () => wsClients.delete(ws));
  ws.on("message", async (raw) => {
    try {
      const msg = JSON.parse(String(raw));
      if (msg.type === "RESOLVE_INPUT" && msg.requestId) {
        if (msg.action === "SUBMIT") await runner.controls.approveSubmit();
        if (msg.action === "SKIP") await runner.controls.skipJob();
        runner.resolveInput(msg.requestId, msg);
      }
    } catch (err) {
      console.error("ws message error:", err.message);
    }
  });
});

server.listen(env.port, "0.0.0.0", () => {
  console.log(
    `cv-agent listening on :${env.port} (headless=${env.headless}, headedDefault=${!env.headless}, preview=${env.preview}, api=${env.apiBase})`
  );
});
