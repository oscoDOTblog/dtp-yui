"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiDelete, apiGet, apiPatch, apiPost } from "../../lib/api";
import LoadingGif from "../components/LoadingGif";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, FieldLabel } from "@/components/ui/field";
import { Tabs, TabsList, TabsTab, TabsPanel } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

const STATUS_VARIANT = {
  pending: "secondary",
  processing: "info",
  done: "success",
  failed: "error",
  needsPaste: "warning",
};

const QUEUE_BANDS = [
  {
    id: "action",
    title: "Needs you",
    hint: "Blocked pages — paste the description to continue",
    match: (s) => s === "needsPaste",
  },
  {
    id: "inflight",
    title: "In the pipeline",
    hint: "Waiting or actively fetching and scoring",
    match: (s) => s === "pending" || s === "processing",
  },
  {
    id: "settled",
    title: "Finished",
    hint: "Done or failed — open jobs in Inbox",
    match: (s) => s === "done" || s === "failed",
  },
];

function statusLabel(status) {
  if (status === "needsPaste") return "needs paste";
  return status || "unknown";
}

function shortUrl(url) {
  if (!url) return "—";
  try {
    const u = new URL(url);
    const path =
      u.pathname.length > 40 ? `${u.pathname.slice(0, 40)}…` : u.pathname;
    return `${u.host}${path}`;
  } catch {
    return url.length > 60 ? `${url.slice(0, 60)}…` : url;
  }
}

function parseUrls(text) {
  return text
    .split(/\r?\n|,/)
    .map((line) => line.trim())
    .filter(Boolean);
}

export default function AnalyzePage() {
  const [mode, setMode] = useState("links");
  const [urlsText, setUrlsText] = useState("");
  const [descriptionRaw, setDescriptionRaw] = useState("");
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
        const status = await apiGet(
          `/ingest/status?runId=${encodeURIComponent(runId)}`,
        );
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

  const parsedUrls = useMemo(() => parseUrls(urlsText), [urlsText]);
  const counts = useMemo(() => {
    const next = { needsPaste: 0, pending: 0, processing: 0, done: 0, failed: 0 };
    for (const item of queue) {
      if (next[item.status] !== undefined) next[item.status] += 1;
    }
    return next;
  }, [queue]);
  const pendingCount = counts.pending + counts.processing + counts.needsPaste;
  const canSubmit =
    parsedUrls.length > 0 &&
    (mode === "links" || Boolean(descriptionRaw.trim()));

  async function onSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setInfo("");

    if (!parsedUrls.length) {
      setError("Add at least one job URL.");
      setBusy(false);
      return;
    }
    if (mode === "paste" && !descriptionRaw.trim()) {
      setError("Paste the full job description to continue.");
      setBusy(false);
      return;
    }

    try {
      const result = await apiPost("/ingest/queue", {
        urls: parsedUrls,
        descriptionRaw: mode === "paste" ? descriptionRaw.trim() : null,
      });
      setUrlsText("");
      setDescriptionRaw("");
      setMode("links");
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
          "Queued — ingest is already running. Items process when it finishes or on the next hourly run.",
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

  async function clearQueue() {
    if (busy || rowBusy) return;
    const removable = queue.filter((item) => item.status !== "processing");
    if (removable.length === 0) return;
    const ok = window.confirm(
      `Clear ${removable.length} queue item${removable.length === 1 ? "" : "s"}?\n\n` +
        "Removes pending, failed, needs-paste, and done rows. " +
        "Items currently processing are kept.",
    );
    if (!ok) return;

    setError("");
    setInfo("");
    setRowBusy("clear");
    try {
      const result = await apiDelete("/ingest/queue");
      const deleted = result.deletedCount || 0;
      const skipped = result.skippedProcessing || 0;
      await loadQueue();
      let msg = `Cleared ${deleted} queue item${deleted === 1 ? "" : "s"}.`;
      if (skipped) msg += ` Left ${skipped} processing.`;
      setInfo(msg);
    } catch (err) {
      setError(err.message || "Failed to clear queue");
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

  return (
    <div className="w-full min-w-0">
      <header className="mb-8">
        <p className="m-0 mb-2 font-mono text-[11px] uppercase tracking-[0.22em] text-primary">
          Manual intake
        </p>
        <h1 className="m-0 mb-2 text-3xl font-semibold tracking-tight max-sm:text-2xl">
          Drop listings into the pipeline
        </h1>
        <p className="m-0 max-w-2xl text-muted-foreground">
          Paste Greenhouse or other job URLs. They score through the same path
          as Gmail and ATS alerts. If ingest is busy, they wait their turn.
        </p>

        <div className="mt-5 flex flex-wrap gap-2">
          <StatusChip
            label="Needs paste"
            value={counts.needsPaste}
            tone="warning"
          />
          <StatusChip label="Pending" value={counts.pending} tone="muted" />
          <StatusChip
            label="Processing"
            value={counts.processing}
            tone="info"
          />
          <StatusChip label="Done" value={counts.done} tone="success" />
        </div>
      </header>

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
          className="mb-6 flex items-center gap-5 rounded-xl border border-primary/35 bg-primary/8 p-5 max-md:flex-col max-md:items-stretch"
          role="status"
          aria-live="polite"
        >
          <LoadingGif
            message="Processing queue"
            alt="Queue processing loading animation"
          />
          <div className="min-w-0 flex-1">
            <p className="m-0 mb-1 font-semibold text-foreground">
              Pipeline running
            </p>
            <p className="m-0 text-sm text-foreground/90">
              {ingestStatus?.currentTitle ||
                ingestStatus?.summary?.currentTitle ||
                "Working…"}
            </p>
            <p className="mt-1.5 text-sm text-muted-foreground">
              Fetching listings · Bay Area gate · scoring. Finished jobs land
              in Inbox.
            </p>
          </div>
        </div>
      ) : null}

      <section
        className={cn(
          "relative w-full min-w-0 overflow-x-clip rounded-2xl border border-border",
          "bg-[linear-gradient(180deg,rgba(255,20,147,0.08)_0%,rgba(26,26,26,0.92)_38%)]",
          "shadow-[inset_3px_0_0_var(--hot-pink)]",
        )}
      >
        <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-primary/60 to-transparent" />

        <form className="grid w-full min-w-0 gap-4 p-5 sm:p-6" onSubmit={onSubmit}>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div className="min-w-0 flex-1">
              <h2 className="m-0 text-lg font-semibold tracking-tight">
                Intake
              </h2>
              <p className="mt-1 mb-0 text-sm text-muted-foreground">
                {mode === "links"
                  ? "One URL per line. Duplicates already in the queue are reused."
                  : "Description attaches to the first URL only."}
              </p>
            </div>
            <p className="m-0 shrink-0 font-mono text-xs text-primary tabular-nums">
              {parsedUrls.length} link{parsedUrls.length === 1 ? "" : "s"} ready
            </p>
          </div>

          <Tabs
            className="w-full min-w-0"
            value={mode}
            onValueChange={(value) => {
              setMode(value);
              setError("");
              setInfo("");
              if (value === "links") setDescriptionRaw("");
            }}
          >
            <TabsList variant="default" className="w-full sm:max-w-md">
              <TabsTab value="links" className="flex-1">
                Job links
              </TabsTab>
              <TabsTab value="paste" className="flex-1">
                URL + description
              </TabsTab>
            </TabsList>

            <TabsPanel value="links" className="mt-4 w-full min-w-0 outline-none">
              <Field>
                <FieldLabel className="sr-only">Job URLs</FieldLabel>
                <Textarea
                  className="min-h-[148px] border-primary/20 bg-black/25 font-mono text-sm leading-relaxed [&_textarea]:break-all"
                  value={urlsText}
                  onChange={(e) => setUrlsText(e.target.value)}
                  placeholder={
                    "https://boards.greenhouse.io/…/jobs/…\nhttps://…"
                  }
                  disabled={busy}
                  autoFocus
                />
              </Field>
            </TabsPanel>

            <TabsPanel value="paste" className="mt-4 grid w-full min-w-0 gap-3 outline-none">
              <Field>
                <FieldLabel>Job URL</FieldLabel>
                <Textarea
                  className="min-h-[72px] border-primary/20 bg-black/25 font-mono text-sm [&_textarea]:break-all"
                  value={urlsText}
                  onChange={(e) => setUrlsText(e.target.value)}
                  placeholder="https://boards.greenhouse.io/…/jobs/…"
                  disabled={busy}
                />
              </Field>
              <Field>
                <FieldLabel>Full job description</FieldLabel>
                <Textarea
                  className="min-h-[200px] border-primary/20 bg-black/25 text-sm"
                  value={descriptionRaw}
                  onChange={(e) => setDescriptionRaw(e.target.value)}
                  placeholder="Paste the full listing text here…"
                  disabled={busy}
                  autoFocus
                />
              </Field>
            </TabsPanel>
          </Tabs>

          <div className="flex flex-wrap items-center gap-2.5 pt-1">
            <Button
              type="submit"
              disabled={busy || !canSubmit}
              loading={busy && !runId}
            >
              Queue into pipeline
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={busy || pendingCount === 0}
              onClick={processQueue}
            >
              Process queue
              {counts.pending > 0 ? ` (${counts.pending})` : ""}
            </Button>
          </div>
        </form>
      </section>

      <section className="mt-10">
        <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="m-0 text-xl font-semibold tracking-tight">
              Live queue
            </h2>
            <p className="mt-1 mb-0 text-sm text-muted-foreground">
              Action-needed first, then in-flight, then finished.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {loadingQueue ? (
              <span className="text-sm text-muted-foreground">Loading…</span>
            ) : (
              <span className="font-mono text-xs text-muted-foreground">
                {queue.length} recent
              </span>
            )}
            {!loadingQueue &&
            queue.some((item) => item.status !== "processing") ? (
              <Button
                type="button"
                size="sm"
                variant="destructive-outline"
                disabled={busy || Boolean(rowBusy)}
                onClick={clearQueue}
              >
                {rowBusy === "clear" ? "Clearing…" : "Clear queue"}
              </Button>
            ) : null}
          </div>
        </div>

        {!loadingQueue && queue.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border/80 px-5 py-10 text-center">
            <p className="m-0 font-medium text-foreground">Queue is empty</p>
            <p className="mt-1.5 mb-0 text-sm text-muted-foreground">
              Paste a job URL above to start an intake run.
            </p>
          </div>
        ) : null}

        <div className="grid gap-8">
          {QUEUE_BANDS.map((band) => {
            const items = queue.filter((item) => band.match(item.status));
            if (!items.length) return null;
            return (
              <div key={band.id}>
                <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
                  <h3 className="m-0 text-sm font-semibold tracking-wide text-foreground">
                    {band.title}
                    <span className="ml-2 font-mono text-xs font-normal text-muted-foreground">
                      {items.length}
                    </span>
                  </h3>
                  <p className="m-0 text-xs text-muted-foreground">{band.hint}</p>
                </div>
                <ul className="m-0 flex list-none flex-col gap-2.5 p-0">
                  {items.map((item) => (
                    <QueueRow
                      key={item._id}
                      item={item}
                      pasteForId={pasteForId}
                      pasteText={pasteText}
                      rowBusy={rowBusy}
                      onPasteToggle={() => {
                        setPasteForId(
                          pasteForId === item._id ? null : item._id,
                        );
                        setPasteText("");
                      }}
                      onPasteText={setPasteText}
                      onSubmitPaste={() => submitPaste(item)}
                      onCancelPaste={() => {
                        setPasteForId(null);
                        setPasteText("");
                      }}
                      onRemove={() => removeItem(item)}
                    />
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}

function StatusChip({ label, value, tone }) {
  const toneClass = {
    warning: "border-warning/40 text-warning-foreground",
    info: "border-info/40 text-info-foreground",
    success: "border-success/40 text-success-foreground",
    muted: "border-border text-muted-foreground",
  }[tone];

  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-full border bg-card/40 px-3 py-1",
        "font-mono text-[11px] uppercase tracking-[0.14em]",
        toneClass,
      )}
    >
      <span>{label}</span>
      <span className="tabular-nums text-foreground">{value}</span>
    </span>
  );
}

function QueueRow({
  item,
  pasteForId,
  pasteText,
  rowBusy,
  onPasteToggle,
  onPasteText,
  onSubmitPaste,
  onCancelPaste,
  onRemove,
}) {
  const openPaste = pasteForId === item._id;
  const title = String(item.jobTitle || "").trim();
  const company = String(item.jobCompany || "").trim();
  const hasRealTitle =
    title &&
    !["untitled", "untitled role", "unknown", "n/a"].includes(
      title.toLowerCase(),
    );
  const hasRealCompany =
    company &&
    !["unknown", "n/a", "untitled"].includes(company.toLowerCase());
  const headline = hasRealTitle
    ? hasRealCompany
      ? `${title} — ${company}`
      : title
    : hasRealCompany
      ? company
      : null;

  return (
    <li
      className={cn(
        "rounded-xl border border-border bg-card/40 px-3.5 py-3",
        item.status === "needsPaste" && "border-warning/45",
        item.status === "processing" && "border-primary/35",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <Badge variant={STATUS_VARIANT[item.status] || "outline"}>
              {statusLabel(item.status)}
            </Badge>
          </div>
          {headline ? (
            <p className="m-0 mb-1 text-base font-semibold tracking-tight text-foreground">
              {headline}
            </p>
          ) : item.status === "processing" || item.status === "pending" ? (
            <p className="m-0 mb-1 text-sm text-muted-foreground">
              Title filling in…
            </p>
          ) : null}
          <a
            href={item.url}
            target="_blank"
            rel="noreferrer"
            className="break-all font-mono text-sm text-foreground/90 underline-offset-2 hover:underline"
            title={item.url}
          >
            {shortUrl(item.url)}
          </a>
          {item.error ? (
            <p className="mt-1 mb-0 text-sm text-destructive">{item.error}</p>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {item.jobId ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              render={<Link href={`/jobs/${item.jobId}`} />}
            >
              {hasRealTitle
                ? `Open · ${title.length > 42 ? `${title.slice(0, 42)}…` : title}`
                : "Open job"}
            </Button>
          ) : null}
          {item.status === "needsPaste" ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={Boolean(rowBusy)}
              onClick={onPasteToggle}
            >
              {openPaste ? "Hide" : "Paste description"}
            </Button>
          ) : null}
          {item.status !== "processing" ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={rowBusy === item._id}
              onClick={onRemove}
            >
              Remove
            </Button>
          ) : null}
        </div>
      </div>

      {openPaste ? (
        <div className="mt-3 grid gap-2 border-t border-border/70 pt-3">
          <Textarea
            className="min-h-[160px] bg-black/20"
            value={pasteText}
            onChange={(e) => onPasteText(e.target.value)}
            placeholder="Paste the full job description…"
            autoFocus
          />
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              disabled={rowBusy === item._id || !pasteText.trim()}
              loading={rowBusy === item._id}
              onClick={onSubmitPaste}
            >
              Save & re-queue
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={rowBusy === item._id}
              onClick={onCancelPaste}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : null}
    </li>
  );
}
