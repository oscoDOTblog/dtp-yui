/**
 * Browser talks to the API on the host (localhost:8000).
 * Next.js server components (inside the web container) must use the Docker
 * service name (api:8000) via API_BASE_INTERNAL.
 */
export function getApiBase() {
  if (typeof window !== "undefined") {
    return process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";
  }
  return (
    process.env.API_BASE_INTERNAL ||
    process.env.NEXT_PUBLIC_API_BASE ||
    "http://localhost:8000"
  );
}

export async function apiGet(path) {
  const url = `${getApiBase()}${path}`;
  let res;
  try {
    res = await fetch(url, { cache: "no-store" });
  } catch (err) {
    throw new Error(`fetch failed (${url}): ${err.message || err}`);
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json();
}

export async function apiPost(path, body) {
  const url = `${getApiBase()}${path}`;
  let res;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    throw new Error(`fetch failed (${url}): ${err.message || err}`);
  }
  if (!res.ok) {
    const text = await res.text();
    let detail = text || res.statusText;
    try {
      const parsed = JSON.parse(text);
      if (parsed?.detail) {
        const err = new Error(
          typeof parsed.detail === "string"
            ? parsed.detail
            : parsed.detail.message || text
        );
        err.status = res.status;
        err.detail = parsed.detail;
        throw err;
      }
    } catch (e) {
      if (e.detail || e.status) throw e;
    }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return res.json();
}
