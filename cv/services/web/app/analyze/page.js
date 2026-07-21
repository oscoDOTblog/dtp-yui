"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { apiDelete, apiGet, apiPatch, apiPost } from "../../lib/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, FieldLabel } from "@/components/ui/field";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";

const STATUS_VARIANT = {
  pending: "secondary",
  processing: "info",
  done: "success",
  failed: "error",
  needsPaste: "warning",
};

function statusLabel(status) {
  if (status === "needsPaste") return "needs paste";
  return status || "unknown";
}

function shortUrl(url) {
  if (!url) return "—";
  try {
    const u = new URL(url);
    const path = u.pathname.length > 40 ? `${u.pathname.slice(0, 40)}…` : u.pathname;
    return `${u.host}${path}`;
  } catch {
    return url.length > 60 ? `${url.slice(0, 60)}…` : url;
  }
}

export default function AnalyzePage() {
  const [urlsText, setUrlsText] = useState("");
  const [descriptionRaw, setDescriptionRaw] = useState("");
  const [needsPaste, setNeedsPaste] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [queue, setQueue] = useState([]);
  const [loadingQueue, setLoadingQueue] = useState(true);
  const [runId, setRunId] = useState(null);
  const [ingestStatus, setIngestStatus] = useState(null);
  const [pasteForId, setPasteForId] = useState(null);
  const [pasteText, setPasteText] = useState("");
  const [rowBusy, setRowBusy] = useState("");

  const loadQueue = useCallback(async () => {
    try {
      const items = await apiGet("/ingest/queue?limit=50");
      setQueue(Array.isArray(items) ? items : []);
    } catch (err) {
      setError(err.message || "Failed to load queue");
    } finally {
      setLoadingQueue(false);
    }
  }, []);

  useEffect(() => {
    loadQueue();
  }, [loadQueue]);

  useEffect(() => {
    if (!runId) return undefined;
    let cancelled = false;
    const tick = async () => {
      try {
        const status = await apiGet(`/ingest/status?runId=${encodeURIComponent(runId)}`);
        if (cancelled) return;
        setIngestStatus(status);
        await loadQueue();
        if (status?.status && status.status !== "running") {
          setRunId(null);
          setBusy(false);
        }
      } catch {
        /* keep polling */
      }
    };
    tick();
    const id = setInterval(tick, 2000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [runId, loadQueue]);

  function parseUrls(text) {
    return text
      .split(/\r?\n|,/)
      .map((line) => line.trim())
      .filter(Boolean);
  }

  async function onSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setInfo("");

    const urls = parseUrls(urlsText);
    if (!urls.length) {
      setError("Enter at least one job URL (one per line).");
      setBusy(false);
      return;
    }
    if (needsPaste && !descriptionRaw.trim()) {
      setError("Paste the full job description to continue.");
      setBusy(false);
      return;
    }

    try {
      const result = await apiPost("/ingest/queue", {
        urls,
        descriptionRaw: needsPaste ? descriptionRaw.trim() : null,
      });
      setUrlsText("");
      setDescriptionRaw("");
      setNeedsPaste(false);
      setQueue((prev) => {
        const incoming = result.items || [];
        const byId = new Map(prev.map((item) => [item._id, item]));
        for (const item of incoming) {
          byId.set(item._id, item);
        }
        return Array.from(byId.values()).sort((a, b) =>
          String(b.createdAt || "").localeCompare(String(a.createdAt || "")),
        );
      });

      const ingest = result.ingest || {};
      if (ingest.accepted && ingest.runId) {
        setRunId(ingest.runId);
        setInfo("Queued — processing now.");
      } else if (ingest.conflict) {
        setBusy(false);
        setInfo(
          "Queued — ingest is already running. Items will process when it finishes or on the next hourly run.",
        );
      } else {
        setBusy(false);
        setInfo("Queued.");
      }
      await loadQueue();
    } catch (err) {
      setError(err.message || "Failed to queue URLs");
      setBusy(false);
    }
  }

  async function processQueue() {
    setError("");
    setInfo("");
    setBusy(true);
    try {
      const result = await apiPost("/ingest/queue/process");
      if (result?.runId) {
        setRunId(result.runId);
        setInfo("Processing queue…");
      }
    } catch (err) {
      setBusy(false);
      if (err.status === 409) {
        setInfo(
          err.detail?.message ||
            "Ingest already running. Queue will drain when it finishes.",
        );
        if (err.detail?.runId) setRunId(err.detail.runId);
        return;
      }
      setError(err.message || "Failed to start queue processing");
    }
  }

  async function removeItem(item) {
    if (rowBusy) return;
    setRowBusy(item._id);
    setError("");
    try {
      await apiDelete(`/ingest/queue/${item._id}`);
      setQueue((prev) => prev.filter((row) => row._id !== item._id));
    } catch (err) {
      setError(err.message || "Failed to remove queue item");
    } finally {
      setRowBusy("");
    }
  }

  async function submitPaste(item) {
    if (rowBusy) return;
    if (!pasteText.trim()) {
      setError("Paste the full job description.");
      return;
    }
    setRowBusy(item._id);
    setError("");
    setInfo("");
    try {
      const result = await apiPatch(`/ingest/queue/${item._id}`, {
        descriptionRaw: pasteText.trim(),
      });
      setPasteForId(null);
      setPasteText("");
      if (result.item) {
        setQueue((prev) =>
          prev.map((row) => (row._id === item._id ? result.item : row)),
        );
      }
      const ingest = result.ingest || {};
      if (ingest.accepted && ingest.runId) {
        setRunId(ingest.runId);
        setBusy(true);
        setInfo("Description saved — processing now.");
      } else if (ingest.conflict) {
        setInfo(
          "Description saved — will process when the current ingest finishes.",
        );
      } else {
        setInfo("Description saved.");
      }
      await loadQueue();
    } catch (err) {
      setError(err.message || "Failed to save description");
    } finally {
      setRowBusy("");
    }
  }

  const pendingCount = queue.filter((item) =>
    ["pending", "processing", "needsPaste"].includes(item.status),
  ).length;

  return (
    <div>
      <h1 className="m-0 mb-1.5 text-3xl font-semibold tracking-tight max-sm:text-2xl">
        Queue job URLs for intake
      </h1>
      <p className="mb-6 text-muted-foreground">
        Paste one or more job posting URLs (one per line). They go into the
        intake queue and digest through the same pipeline as Gmail and Greenhouse.
        If ingest is busy, they wait for the next run.
      </p>

      {error ? (
        <Alert variant="error" className="mb-4">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      {info ? (
        <Alert variant="info" className="mb-4">
          <AlertDescription>{info}</AlertDescription>
        </Alert>
      ) : null}

      {busy && runId ? (
        <div
          className="mb-5 flex max-w-xl items-start gap-4 rounded-xl border border-primary/35 bg-primary/8 p-4"
          role="status"
          aria-live="polite"
        >
          <Spinner className="mt-0.5 size-6 text-primary" />
          <div>
            <p className="m-0 mb-1 font-semibold">Processing queue</p>
            <p className="m-0 text-sm text-foreground/90">
              {ingestStatus?.currentTitle ||
                ingestStatus?.summary?.currentTitle ||
                "Working…"}
            </p>
          </div>
        </div>
      ) : null}

      <form className="grid max-w-xl gap-3.5" onSubmit={onSubmit}>
        <Field>
          <FieldLabel>Job URLs</FieldLabel>
          <Textarea
            className="min-h-[120px] font-mono text-sm"
            value={urlsText}
            onChange={(e) => setUrlsText(e.target.value)}
            placeholder={"https://boards.greenhouse.io/…/jobs/…\nhttps://…"}
            required={!needsPaste}
            disabled={busy}
          />
        </Field>

        {needsPaste ? (
          <Field>
            <FieldLabel>Job description (attached to first URL)</FieldLabel>
            <Textarea
              className="min-h-[220px]"
              value={descriptionRaw}
              onChange={(e) => setDescriptionRaw(e.target.value)}
              placeholder="Paste the full job description here…"
              required
              disabled={busy}
              autoFocus
            />
          </Field>
        ) : null}

        <div className="mt-2 flex flex-wrap gap-2.5">
          <Button
            type="submit"
            disabled={busy || !urlsText.trim()}
            loading={busy && !runId}
          >
            Queue for intake
          </Button>
          {!needsPaste ? (
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => {
                setNeedsPaste(true);
                setInfo(
                  "Paste the full job description below. It attaches to the first URL.",
                );
              }}
            >
              Paste description instead
            </Button>
          ) : (
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => {
                setNeedsPaste(false);
                setInfo("");
                setError("");
                setDescriptionRaw("");
              }}
            >
              Back to URLs only
            </Button>
          )}
          <Button
            type="button"
            variant="outline"
            disabled={busy || pendingCount === 0}
            onClick={processQueue}
          >
            Process queue
          </Button>
        </div>
      </form>

      <section className="mt-10 max-w-3xl">
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <h2 className="m-0 text-xl font-semibold tracking-tight">Queue</h2>
          {loadingQueue ? (
            <span className="text-sm text-muted-foreground">Loading…</span>
          ) : (
            <span className="text-sm text-muted-foreground">
              {queue.length} recent
            </span>
          )}
        </div>

        {!loadingQueue && queue.length === 0 ? (
          <p className="text-muted-foreground">No queued URLs yet.</p>
        ) : (
          <ul className="m-0 flex list-none flex-col gap-2.5 p-0">
            {queue.map((item) => (
              <li
                key={item._id}
                className="rounded-xl border border-border bg-card/40 px-3.5 py-3"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="mb-1 flex flex-wrap items-center gap-2">
                      <Badge
                        variant={STATUS_VARIANT[item.status] || "outline"}
                      >
                        {statusLabel(item.status)}
                      </Badge>
                      {item.jobId ? (
                        <Link
                          href={`/jobs/${item.jobId}`}
                          className="text-sm font-medium text-primary underline-offset-2 hover:underline"
                        >
                          Open job
                        </Link>
                      ) : null}
                    </div>
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noreferrer"
                      className="break-all text-sm text-foreground/90 underline-offset-2 hover:underline"
                      title={item.url}
                    >
                      {shortUrl(item.url)}
                    </a>
                    {item.error ? (
                      <p className="mt-1 mb-0 text-sm text-destructive">
                        {item.error}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {item.status === "needsPaste" ? (
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={Boolean(rowBusy)}
                        onClick={() => {
                          setPasteForId(
                            pasteForId === item._id ? null : item._id,
                          );
                          setPasteText("");
                        }}
                      >
                        Paste
                      </Button>
                    ) : null}
                    {item.status !== "processing" ? (
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        disabled={rowBusy === item._id}
                        onClick={() => removeItem(item)}
                      >
                        Remove
                      </Button>
                    ) : null}
                  </div>
                </div>

                {pasteForId === item._id ? (
                  <div className="mt-3 grid gap-2">
                    <Textarea
                      className="min-h-[160px]"
                      value={pasteText}
                      onChange={(e) => setPasteText(e.target.value)}
                      placeholder="Paste the full job description…"
                      autoFocus
                    />
                    <div className="flex flex-wrap gap-2">
                      <Button
                        type="button"
                        size="sm"
                        disabled={rowBusy === item._id || !pasteText.trim()}
                        loading={rowBusy === item._id}
                        onClick={() => submitPaste(item)}
                      >
                        Save & re-queue
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={rowBusy === item._id}
                        onClick={() => {
                          setPasteForId(null);
                          setPasteText("");
                        }}
                      >
                        Cancel
                      </Button>
                    </div>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
