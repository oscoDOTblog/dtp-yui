import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
// Long Ollama-backed calls (profile update, analyze) need more than the default proxy timeout
export const maxDuration = 300;

const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailers",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-length",
]);

function apiBase() {
  return (
    process.env.API_BASE_INTERNAL ||
    process.env.API_REWRITE_TARGET ||
    "http://localhost:8000"
  ).replace(/\/$/, "");
}

async function proxyRequest(request, context) {
  const params = await context.params;
  const parts = params?.path;
  const suffix = Array.isArray(parts) ? parts.join("/") : String(parts || "");
  const incoming = new URL(request.url);
  const target = `${apiBase()}/${suffix}${incoming.search}`;

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) {
      headers.set(key, value);
    }
  });

  const init = {
    method: request.method,
    headers,
    redirect: "manual",
    signal: AbortSignal.timeout(300_000),
  };

  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.arrayBuffer();
  }

  let upstream;
  try {
    upstream = await fetch(target, init);
  } catch (err) {
    const message = err?.message || String(err);
    console.error(`backend proxy failed ${target}:`, message);
    return NextResponse.json(
      { detail: `API proxy failed: ${message}` },
      { status: 502 },
    );
  }

  const outHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) {
      outHeaders.set(key, value);
    }
  });

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: outHeaders,
  });
}

export const GET = proxyRequest;
export const POST = proxyRequest;
export const PUT = proxyRequest;
export const PATCH = proxyRequest;
export const DELETE = proxyRequest;
