"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "../lib/api";
import LoadingGif from "./components/LoadingGif";
import styles from "./ui.module.css";

function badgeClass(recommendation) {
  if (recommendation === "apply") return `${styles.badge} ${styles.badgeApply}`;
  if (recommendation === "consider") return `${styles.badge} ${styles.badgeConsider}`;
  if (recommendation === "reject") return `${styles.badge} ${styles.badgeReject}`;
  return `${styles.badge} ${styles.badgeSkip}`;
}

function sourceLabel(job) {
  const src = job.source || "manual";
  const discovered = job.discoveredBy?.source;
  if (src === "gmail" && discovered) return discovered.replace(/-email$/, "");
  return src;
}

function listingUrl(job) {
  return job.canonicalApplyUrl || job.url || job.sourceUrl || "";
}

function locationChip(job) {
  const la = job.locationAssessment;
  if (!la) return null;
  if (la.bayAreaEligible === false) {
    return { label: "Out of area", className: styles.pillBad };
  }
  const arr = la.workArrangement || job.workMode || "unknown";
  if (arr === "remote") return { label: "Remote", className: styles.pillGood };
  if (arr === "hybrid") return { label: "Hybrid", className: styles.pillWarn };
  if (arr === "onsite") return { label: "Onsite", className: styles.pillNeutral };
  if (la.geographicEligibility === "bay_area") {
    return { label: "Bay Area", className: styles.pillGood };
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

  const ingesting = ingestStatus?.status === "running";

  const loadJobs = useCallback(async () => {
    try {
      let path = "/jobs";
      if (eligibleFilter === "eligible") path = "/jobs?eligible=true";
      if (eligibleFilter === "out") path = "/jobs?eligible=false";
      const data = await apiGet(path);
      setJobs(Array.isArray(data) ? data : []);
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

  return (
    <div>
      <div className={styles.row}>
        <div>
          <h1 className={styles.pageTitle}>Inbox</h1>
          <p className={styles.subtitle}>
            Digests split into per-listing jobs. Ingest runs in the background — browse
            and Open while scoring continues.
          </p>
        </div>
        <div className={styles.actionRow}>
          <button
            type="button"
            className={`${styles.btn} ${styles.btnSecondary}`}
            onClick={() => runIngest(false)}
            disabled={ingesting}
            title="Fetch only new JobAlerts mail that has not been ingested yet"
          >
            {ingesting ? "Ingesting…" : "Fetch new alerts"}
          </button>
          <button
            type="button"
            className={`${styles.btn} ${styles.btnSecondary}`}
            onClick={() => {
              if (
                window.confirm(
                  "Re-read recent JobAlerts from the start?\n\n" +
                    "Use this after a failed run or parser changes. " +
                    "Already-saved jobs are still deduped (not duplicated)."
                )
              ) {
                runIngest(true);
              }
            }}
            disabled={ingesting}
            title="Clear processed markers and re-read recent JobAlerts (dedupes existing jobs)"
          >
            Re-read all recent
          </button>
        </div>
      </div>

      {error ? <div className={styles.error}>{error}</div> : null}
      {info && !ingesting ? <div className={styles.info}>{info}</div> : null}

      {ingesting ? (
        <div
          className={`${styles.statusPanel} ${styles.statusPanelIngestLive}`}
          role="status"
          aria-live="polite"
        >
          <LoadingGif
            message="Background ingest"
            alt="Ingest loading animation"
          />
          <div className={styles.statusPanelBody}>
            <p className={styles.statusTitle}>Ingesting JobAlerts</p>
            <p className={styles.statusText}>{statusBannerText(ingestStatus)}</p>
            <p className={styles.meta}>
              Splitting digests · fetching listing pages · Bay Area gate · scoring one
              by one. You can Open finished jobs below while this runs.
            </p>
          </div>
        </div>
      ) : null}

      <div className={styles.filterBar}>
        <div className={styles.filterGroup}>
          {[
            { id: "eligible", label: "Bay Area eligible" },
            { id: "all", label: "All" },
            { id: "out", label: "Out of area" },
          ].map((f) => (
            <button
              key={f.id}
              type="button"
              className={`${styles.filterChip} ${eligibleFilter === f.id ? styles.filterChipActive : ""}`}
              onClick={() => setEligibleFilter(f.id)}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {loading ? <p className={styles.empty}>Loading…</p> : null}

      {!loading && jobs.length === 0 ? (
        <p className={styles.empty}>
          No jobs yet.{" "}
          <a href="/analyze">Analyze a job description</a>
          {" "}or configure Gmail alerts (<code>docs/GMAIL_SETUP.md</code>) then Run
          ingest.
        </p>
      ) : null}

      <div className={styles.grid}>
        {jobs.map((job) => {
          const match = job.match;
          const loc = locationChip(job);
          const openHref = listingUrl(job);
          return (
            <div key={job._id} className={styles.card}>
              <div className={styles.row}>
                <a href={`/jobs/${job._id}`} className={styles.cardLinkTitle}>
                  <h2 className={styles.title}>
                    {job.title} — {job.company}
                  </h2>
                </a>
                {match ? (
                  <span className={styles.score}>{match.score}/100</span>
                ) : (
                  <span className={styles.meta}>
                    {job.status === "out_of_area" ? "Out of area" : "Not analyzed"}
                  </span>
                )}
              </div>
              <p className={styles.meta}>
                {job.location || "Location n/a"} · {job.workMode || "unknown"} ·{" "}
                {job.status}
              </p>
              <div className={styles.pillRow}>
                <span className={`${styles.pill} ${styles.pillNeutral}`}>
                  {sourceLabel(job)}
                </span>
                {loc ? (
                  <span className={`${styles.pill} ${loc.className}`}>{loc.label}</span>
                ) : null}
                {match ? (
                  <span className={badgeClass(match.recommendation)}>
                    {match.recommendation}
                  </span>
                ) : null}
                {match?.roleFamily ? (
                  <span className={`${styles.pill} ${styles.pillNeutral}`}>
                    {match.roleFamily}
                  </span>
                ) : null}
              </div>
              <div className={styles.actionRow}>
                <a
                  className={`${styles.btn} ${styles.btnSecondary} ${styles.btnSmall}`}
                  href={`/jobs/${job._id}`}
                >
                  Details
                </a>
                {openHref ? (
                  <a
                    className={`${styles.btn} ${styles.btnSmall}`}
                    href={openHref}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Open
                  </a>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
