"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "../lib/api";
import LoadingGif from "./components/LoadingGif";
import styles from "./ui.module.css";

const INGEST_STEPS = [
  "Connecting to Gmail…",
  "Searching JobAlerts mailbox…",
  "Reading alert emails…",
  "Extracting titles, companies, and links…",
  "Resolving apply URLs…",
  "Checking Bay Area eligibility…",
  "Deduping against existing jobs…",
  "Scoring new matches with Ollama…",
  "Writing gap insights…",
  "Refreshing Inbox…",
];

const REPROCESS_STEPS = [
  "Clearing processed-message markers…",
  ...INGEST_STEPS,
];

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

export default function HomePage() {
  const [eligibleFilter, setEligibleFilter] = useState("eligible");
  const [jobs, setJobs] = useState([]);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(true);
  const [ingesting, setIngesting] = useState(false);
  const [reprocessing, setReprocessing] = useState(false);
  const [statusIndex, setStatusIndex] = useState(0);
  const [statusText, setStatusText] = useState("");

  const statusSteps = reprocessing ? REPROCESS_STEPS : INGEST_STEPS;

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      let path = "/jobs";
      if (eligibleFilter === "eligible") path = "/jobs?eligible=true";
      if (eligibleFilter === "out") path = "/jobs?eligible=false";
      const data = await apiGet(path);
      setJobs(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err.message || "Failed to load jobs");
      setJobs([]);
    } finally {
      setLoading(false);
    }
  }, [eligibleFilter]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!ingesting) return undefined;
    const steps = reprocessing ? REPROCESS_STEPS : INGEST_STEPS;
    setStatusIndex(0);
    setStatusText(steps[0]);
    const id = setInterval(() => {
      setStatusIndex((prev) => {
        const next = Math.min(prev + 1, steps.length - 1);
        setStatusText(steps[next]);
        return next;
      });
    }, 2200);
    return () => clearInterval(id);
  }, [ingesting, reprocessing]);

  async function runIngest(reprocess = false) {
    setIngesting(true);
    setReprocessing(reprocess);
    setInfo("");
    setError("");
    try {
      const path = reprocess ? "/ingest/run?reprocess=true" : "/ingest/run";
      const result = await apiPost(path);
      const parts = [
        `Ingest complete: ${result.jobsCreated || 0} new`,
        `${result.jobsUpdated || 0} updated`,
        `${result.analyzed || 0} analyzed`,
        `${result.outOfArea || 0} out of area`,
        `${result.messagesSeen || 0} messages seen`,
      ];
      if (result.reprocessCleared) {
        parts.push(`cleared ${result.reprocessCleared} markers`);
      }
      if (result.skippedNoCreds) {
        parts.push("Gmail credentials missing — see docs/GMAIL_SETUP.md");
      }
      if (Array.isArray(result.errors) && result.errors.length) {
        parts.push(`${result.errors.length} errors`);
      }
      setInfo(parts.join(" · "));
      await load();
    } catch (err) {
      setError(err.message || "Ingest failed");
    } finally {
      setIngesting(false);
      setReprocessing(false);
      setStatusText("");
      setStatusIndex(0);
    }
  }

  return (
    <div>
      <div className={styles.row}>
        <div>
          <h1 className={styles.pageTitle}>Inbox</h1>
          <p className={styles.subtitle}>
            Scored jobs awaiting your decision. Alerts ingest hourly; paste on Analyze anytime.
          </p>
        </div>
        <div className={styles.actionRow}>
          <button
            type="button"
            className={`${styles.btn} ${styles.btnSecondary}`}
            onClick={() => runIngest(false)}
            disabled={ingesting}
          >
            {ingesting && !reprocessing ? "Ingesting…" : "Run ingest"}
          </button>
          <button
            type="button"
            className={`${styles.btn} ${styles.btnSecondary}`}
            onClick={() => {
              if (
                window.confirm(
                  "Clear processed Gmail markers and re-read recent JobAlerts? Use after a failed ingest."
                )
              ) {
                runIngest(true);
              }
            }}
            disabled={ingesting}
          >
            {ingesting && reprocessing ? "Reprocessing…" : "Reprocess alerts"}
          </button>
        </div>
      </div>

      {error ? <div className={styles.error}>{error}</div> : null}
      {info && !ingesting ? <div className={styles.info}>{info}</div> : null}

      {ingesting ? (
        <div
          className={`${styles.statusPanel} ${styles.statusPanelIngest}`}
          role="status"
          aria-live="polite"
        >
          <LoadingGif
            message={reprocessing ? "Reprocessing alerts" : "Ingesting job alerts"}
            alt="Ingest loading animation"
          />
          <div className={styles.statusPanelBody}>
            <p className={styles.statusTitle}>
              {reprocessing ? "Reprocessing JobAlerts" : "Ingesting JobAlerts"}
            </p>
            <p className={styles.statusText}>{statusText}</p>
            <ul className={styles.statusStepList}>
              {statusSteps.map((step, idx) => (
                <li
                  key={step}
                  className={
                    idx < statusIndex
                      ? styles.statusStepDone
                      : idx === statusIndex
                        ? styles.statusStepCurrent
                        : styles.statusStepPending
                  }
                >
                  {idx < statusIndex ? "✓ " : idx === statusIndex ? "→ " : "○ "}
                  {step}
                </li>
              ))}
            </ul>
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
              disabled={ingesting}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {loading && !ingesting ? <p className={styles.empty}>Loading…</p> : null}

      {!loading && !ingesting && jobs.length === 0 ? (
        <p className={styles.empty}>
          No jobs yet.{" "}
          <a href="/analyze">Analyze a job description</a>
          {" "}or configure Gmail alerts (<code>docs/GMAIL_SETUP.md</code>) then click Run
          ingest.
        </p>
      ) : null}

      {!ingesting ? (
        <div className={styles.grid}>
          {jobs.map((job) => {
            const match = job.match;
            const loc = locationChip(job);
            return (
              <a
                key={job._id}
                href={`/jobs/${job._id}`}
                className={`${styles.card} ${styles.cardLink}`}
              >
                <div className={styles.row}>
                  <h2 className={styles.title}>
                    {job.title} — {job.company}
                  </h2>
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
              </a>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
