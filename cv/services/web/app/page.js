"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiGet, apiPost } from "../lib/api";
import LoadingGif from "./components/LoadingGif";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardPanel } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";

function recommendationVariant(recommendation) {
  if (recommendation === "apply") return "success";
  if (recommendation === "consider") return "warning";
  if (recommendation === "reject") return "error";
  return "outline";
}

function sourceLabel(job) {
  const src = job.source || "manual";
  const discovered = job.discoveredBy?.source;
  if (src === "gmail" && discovered) return discovered.replace(/-email$/, "");
  if (src === "greenhouse") return "greenhouse";
  return src;
}

function listingUrl(job) {
  return job.canonicalApplyUrl || job.url || job.sourceUrl || "";
}

function locationChip(job) {
  const la = job.locationAssessment;
  if (!la) return null;
  if (la.bayAreaEligible === false) {
    return { label: "Out of area", variant: "error" };
  }
  const arr = la.workArrangement || job.workMode || "unknown";
  if (arr === "remote") return { label: "Remote", variant: "success" };
  if (arr === "hybrid") return { label: "Hybrid", variant: "warning" };
  if (arr === "onsite") return { label: "Onsite", variant: "outline" };
  if (la.geographicEligibility === "bay_area") {
    return { label: "Bay Area", variant: "success" };
  }
  return null;
}

function statusBannerText(status) {
  if (!status || status.status === "idle") return "";
  if (status.status === "running") {
    const processed = status.listingsProcessed || 0;
    const total = status.listingsTotal || 0;
    const current = status.currentTitle || "Working…";
    if (total > 0) {
      return `Ingesting ${processed}/${total} — ${current}`;
    }
    return current || "Starting ingest…";
  }
  if (status.status === "completed") {
    const s = status.summary || status;
    return `Ingest complete: ${s.jobsCreated || 0} new · ${s.analyzed || 0} analyzed · ${s.outOfArea || 0} out of area`;
  }
  if (status.status === "failed") {
    return "Ingest failed — check API logs";
  }
  return "";
}

export default function HomePage() {
  const [eligibleFilter, setEligibleFilter] = useState("eligible");
  const [jobs, setJobs] = useState([]);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(true);
  const [ingestStatus, setIngestStatus] = useState(null);
  const [runId, setRunId] = useState(null);
  const [selectedIds, setSelectedIds] = useState(() => new Set());
  const [deleting, setDeleting] = useState(false);

  const ingesting = ingestStatus?.status === "running";

  const loadJobs = useCallback(async () => {
    try {
      let path = "/jobs";
      if (eligibleFilter === "eligible") path = "/jobs?eligible=true";
      if (eligibleFilter === "out") path = "/jobs?eligible=false";
      const data = await apiGet(path);
      const list = Array.isArray(data) ? data : [];
      setJobs(list);
      setSelectedIds((prev) => {
        if (prev.size === 0) return prev;
        const visible = new Set(list.map((j) => j._id));
        const next = new Set([...prev].filter((id) => visible.has(id)));
        return next.size === prev.size ? prev : next;
      });
    } catch (err) {
      setError(err.message || "Failed to load jobs");
      setJobs([]);
    }
  }, [eligibleFilter]);

  const refreshStatus = useCallback(async () => {
    try {
      const path = runId
        ? `/ingest/status?runId=${encodeURIComponent(runId)}`
        : "/ingest/status";
      const data = await apiGet(path);
      setIngestStatus(data);
      return data;
    } catch {
      return null;
    }
  }, [runId]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError("");
      await loadJobs();
      if (!cancelled) {
        const status = await refreshStatus();
        if (status?.status === "running" && status._id) {
          setRunId(status._id);
        }
        setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadJobs, refreshStatus]);

  useEffect(() => {
    if (!ingesting) return undefined;
    const id = setInterval(async () => {
      const status = await refreshStatus();
      await loadJobs();
      if (status && status.status !== "running") {
        setInfo(statusBannerText(status));
      }
    }, 3000);
    return () => clearInterval(id);
  }, [ingesting, refreshStatus, loadJobs]);

  const allVisibleSelected = useMemo(
    () => jobs.length > 0 && jobs.every((j) => selectedIds.has(j._id)),
    [jobs, selectedIds],
  );
  const selectedCount = selectedIds.size;

  function toggleJob(jobId) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(jobId)) next.delete(jobId);
      else next.add(jobId);
      return next;
    });
  }

  function toggleSelectAll() {
    if (allVisibleSelected) {
      setSelectedIds(new Set());
      return;
    }
    setSelectedIds(new Set(jobs.map((j) => j._id)));
  }

  async function deleteSelected() {
    const ids = [...selectedIds];
    if (ids.length === 0) return;
    const ok = window.confirm(
      `Delete ${ids.length} job${ids.length === 1 ? "" : "s"}?\n\n` +
        "This permanently removes matches, decisions, application packages, " +
        "generated documents, and related gap insight data.",
    );
    if (!ok) return;

    setDeleting(true);
    setError("");
    setInfo("");
    try {
      const result = await apiPost("/jobs/bulk-delete", { jobIds: ids });
      const deleted = result.deletedCount || 0;
      const missing = (result.missing || []).length;
      const errors = (result.errors || []).length;
      setSelectedIds(new Set());
      await loadJobs();
      let msg = `Deleted ${deleted} job${deleted === 1 ? "" : "s"}.`;
      if (missing) msg += ` ${missing} already gone.`;
      if (errors) msg += ` ${errors} failed — check API logs.`;
      setInfo(msg);
    } catch (err) {
      setError(err.message || "Bulk delete failed");
    } finally {
      setDeleting(false);
    }
  }

  async function runIngest(reprocess = false) {
    setInfo("");
    setError("");
    try {
      const path = reprocess ? "/ingest/run?reprocess=true" : "/ingest/run";
      const result = await apiPost(path);
      setRunId(result.runId);
      setIngestStatus({
        status: "running",
        _id: result.runId,
        currentTitle: reprocess
          ? "Clearing markers… then reading JobAlerts"
          : "Starting…",
        listingsProcessed: 0,
        listingsTotal: 0,
      });
    } catch (err) {
      if (err.status === 409 || (err.detail && err.detail.runId)) {
        const detail = err.detail || {};
        setRunId(detail.runId);
        setIngestStatus({
          status: "running",
          _id: detail.runId,
          currentTitle: "Ingest already running…",
        });
        setInfo("Ingest already running — browsing while it finishes.");
        return;
      }
      setError(err.message || "Ingest failed to start");
    }
  }

  const filters = [
    { id: "eligible", label: "Bay Area eligible" },
    { id: "all", label: "All" },
    { id: "out", label: "Out of area" },
  ];

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-baseline justify-between gap-4">
        <div>
          <h1 className="m-0 mb-1.5 text-3xl font-semibold tracking-tight max-sm:text-2xl">
            Inbox
          </h1>
          <p className="m-0 text-muted-foreground">
            Digests split into per-listing jobs. Ingest runs in the background —
            browse and Open while scoring continues.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => runIngest(false)}
            disabled={ingesting || deleting}
            title="Fetch only new JobAlerts mail that has not been ingested yet"
          >
            {ingesting ? "Ingesting…" : "Fetch new alerts"}
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              if (
                window.confirm(
                  "Re-read recent JobAlerts from the start?\n\n" +
                    "Use this after a failed run or parser changes. " +
                    "Already-saved jobs are still deduped (not duplicated).",
                )
              ) {
                runIngest(true);
              }
            }}
            disabled={ingesting || deleting}
            title="Clear processed markers and re-read recent JobAlerts (dedupes existing jobs)"
          >
            Re-read all recent
          </Button>
        </div>
      </div>

      {error ? (
        <Alert variant="error" className="mb-4">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      {info && !ingesting ? (
        <Alert variant="warning" className="mb-4">
          <AlertDescription>{info}</AlertDescription>
        </Alert>
      ) : null}

      {ingesting ? (
        <div
          className="mb-5 flex items-center gap-5 rounded-xl border border-primary/35 bg-primary/8 p-5 max-md:flex-col max-md:items-stretch"
          role="status"
          aria-live="polite"
        >
          <LoadingGif
            message="Background ingest"
            alt="Ingest loading animation"
          />
          <div className="min-w-0 flex-1">
            <p className="m-0 mb-1 font-semibold text-foreground">
              Ingesting JobAlerts
            </p>
            <p className="m-0 text-sm text-foreground/90">
              {statusBannerText(ingestStatus)}
            </p>
            <p className="mt-1.5 text-sm text-muted-foreground">
              Splitting digests · fetching listing pages · Bay Area gate ·
              scoring one by one. You can Open finished jobs below while this
              runs.
            </p>
          </div>
        </div>
      ) : null}

      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-1.5">
          {filters.map((f) => (
            <Button
              key={f.id}
              type="button"
              size="sm"
              variant={eligibleFilter === f.id ? "default" : "outline"}
              className="rounded-full"
              onClick={() => {
                setEligibleFilter(f.id);
                setSelectedIds(new Set());
              }}
            >
              {f.label}
            </Button>
          ))}
        </div>

        {!loading && jobs.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={toggleSelectAll}
              disabled={deleting}
            >
              {allVisibleSelected ? "Clear selection" : "Select all"}
            </Button>
            {selectedCount > 0 ? (
              <>
                <span className="text-xs text-muted-foreground">
                  {selectedCount} selected
                </span>
                <Button
                  type="button"
                  variant="destructive-outline"
                  size="sm"
                  onClick={deleteSelected}
                  disabled={deleting}
                  title="Cascade-delete selected jobs and related data"
                >
                  {deleting
                    ? "Deleting…"
                    : `Delete selected (${selectedCount})`}
                </Button>
              </>
            ) : null}
          </div>
        ) : null}
      </div>

      {loading ? (
        <p className="py-8 text-muted-foreground">Loading…</p>
      ) : null}

      {!loading && jobs.length === 0 ? (
        <p className="py-8 text-muted-foreground">
          No jobs yet. <a href="/analyze">Analyze a job description</a> or
          configure Gmail alerts (<code>docs/GMAIL_SETUP.md</code>) then Fetch
          new alerts.
        </p>
      ) : null}

      <div className="grid gap-3.5">
        {jobs.map((job) => {
          const match = job.match;
          const loc = locationChip(job);
          const openHref = listingUrl(job);
          const selected = selectedIds.has(job._id);
          return (
            <Card
              key={job._id}
              className={cn(
                "transition-colors hover:border-primary/50",
                selected && "border-primary shadow-[0_0_0_1px_rgba(255,20,147,0.25)]",
              )}
            >
              <CardPanel className="p-4">
                <div className="flex items-start gap-3">
                  <Checkbox
                    checked={selected}
                    onCheckedChange={() => toggleJob(job._id)}
                    disabled={deleting}
                    aria-label={`Select ${job.title} at ${job.company}`}
                    className="mt-1"
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <a
                        href={`/jobs/${job._id}`}
                        className="min-w-0 flex-1 text-inherit no-underline hover:no-underline"
                      >
                        <h2 className="m-0 text-base font-semibold hover:text-primary">
                          {job.title} — {job.company}
                        </h2>
                      </a>
                      {match ? (
                        <span className="text-xl font-bold text-primary">
                          {match.score}/100
                        </span>
                      ) : (
                        <span className="text-sm text-muted-foreground">
                          {job.status === "out_of_area"
                            ? "Out of area"
                            : "Not analyzed"}
                        </span>
                      )}
                    </div>
                    <p className="mt-1.5 m-0 text-sm text-muted-foreground">
                      {job.location || "Location n/a"} ·{" "}
                      {job.workMode || "unknown"} · {job.status}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      <Badge variant="outline">{sourceLabel(job)}</Badge>
                      {loc ? (
                        <Badge variant={loc.variant}>{loc.label}</Badge>
                      ) : null}
                      {match ? (
                        <Badge
                          variant={recommendationVariant(match.recommendation)}
                          className="uppercase tracking-wide"
                        >
                          {match.recommendation}
                        </Badge>
                      ) : null}
                      {match?.roleFamily ? (
                        <Badge variant="outline">{match.roleFamily}</Badge>
                      ) : null}
                    </div>
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      <Button
                        size="sm"
                        variant="outline"
                        render={<a href={`/jobs/${job._id}`} />}
                      >
                        Details
                      </Button>
                      {openHref ? (
                        <Button
                          size="sm"
                          render={
                            <a
                              href={openHref}
                              target="_blank"
                              rel="noopener noreferrer"
                            />
                          }
                        >
                          Open
                        </Button>
                      ) : null}
                    </div>
                  </div>
                </div>
              </CardPanel>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
