/**
 * CV2 orchestration boundary for OpenClaw.
 * OpenClaw can call this process with a job URL or a Gmail message payload.
 * Browser actions remain in services/agent, where CDP + human approval policy
 * is enforced. This service deliberately never submits an application itself.
 */
import http from "node:http";
import { request } from "node:https";

const port = Number(process.env.OPENCLAW_PORT || 8020);
const apiBase = process.env.CV_API_BASE || "http://127.0.0.1:8000";
const telegramToken = process.env.TELEGRAM_BOT_TOKEN || "";
const telegramChatId = process.env.TELEGRAM_CHAT_ID || "";

async function api(path, init = {}) {
  const res = await fetch(`${apiBase}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init.headers || {}) },
  });
  const body = await res.text();
  if (!res.ok) throw new Error(`CV API ${res.status}: ${body.slice(0, 300)}`);
  return body ? JSON.parse(body) : null;
}

function telegram(path, payload) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify(payload);
    const req = request({
      hostname: "api.telegram.org", path: `/bot${telegramToken}/${path}`,
      method: "POST", headers: { "content-type": "application/json", "content-length": Buffer.byteLength(body) },
    }, (res) => { let data = ""; res.on("data", (chunk) => { data += chunk; }); res.on("end", () => resolve({ status: res.statusCode, data })); });
    req.on("error", reject); req.write(body); req.end();
  });
}

async function sendHourlyReport() {
  if (!telegramToken || !telegramChatId) return { skipped: true, reason: "Telegram is not configured" };
  const jobs = await api("/jobs");
  const applied = jobs.filter((job) => ["pending", "applied", "interview", "round1", "round2"].includes(job.applicationStatus || job.status)).length;
  const considered = jobs.filter((job) => job.matchScore != null).length;
  const text = `CV2 hourly report\nApplied: ${applied}\nTracked and scored: ${considered}\nTotal tracked: ${jobs.length}`;
  await telegram("sendMessage", { chat_id: telegramChatId, text });
  return { applied, considered, total: jobs.length };
}

async function handle(req, res) {
  try {
    if (req.method === "GET" && req.url === "/health") return respond(res, 200, { ok: true, service: "cv2-openclaw" });
    if (req.method === "POST" && req.url === "/report/hourly") return respond(res, 200, await sendHourlyReport());
    if (req.method === "POST" && req.url === "/jobs/intake") {
      let raw = ""; for await (const chunk of req) raw += chunk;
      const payload = JSON.parse(raw || "{}");
      if (!payload.url) return respond(res, 400, { error: "url is required" });
      return respond(res, 202, await api("/ingest/queue", { method: "POST", body: JSON.stringify({ urls: [payload.url] }) }));
    }
    respond(res, 404, { error: "not found" });
  } catch (error) { respond(res, 500, { error: error.message }); }
}
function respond(res, status, body) { res.writeHead(status, { "content-type": "application/json" }); res.end(JSON.stringify(body)); }
http.createServer(handle).listen(port, "127.0.0.1", () => console.log(`CV2 OpenClaw bridge listening on ${port}`));
if (process.env.TELEGRAM_HOURLY_REPORT !== "false") {
  setInterval(() => sendHourlyReport().catch((error) => console.error("hourly report failed:", error.message)), 60 * 60 * 1000);
}
