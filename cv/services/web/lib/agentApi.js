/**
 * Client helpers for the Stage 6 apply agent control plane.
 * Browser uses same-origin `/agent-api` proxy (works on localhost + LAN).
 */

export function getAgentApiBase() {
  if (typeof window !== "undefined") {
    return "/agent-api";
  }
  return (
    process.env.AGENT_BASE_INTERNAL ||
    "http://127.0.0.1:8010"
  ).replace(/\/$/, "");
}

async function agentFetch(path, { method = "GET", body } = {}) {
  const url = `${getAgentApiBase()}${path}`;
  let res;
  try {
    res = await fetch(url, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      cache: "no-store",
    });
  } catch (err) {
    throw new Error(`agent fetch failed (${url}): ${err.message || err}`);
  }
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { raw: text };
  }
  if (!res.ok) {
    const detail = data?.detail || text || res.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

export function agentGet(path) {
  return agentFetch(path, { method: "GET" });
}

export function agentPost(path, body) {
  return agentFetch(path, { method: "POST", body });
}

export function agentEventSource() {
  if (typeof window === "undefined") return null;
  return new EventSource(`${getAgentApiBase()}/events/stream`);
}
