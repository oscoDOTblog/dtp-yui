"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { apiDelete, apiGet, apiPost } from "../../../lib/api";
import DocumentPackagePanel, {
  clearPackageFromBrowser,
  loadPackageFromBrowser,
  savePackageToBrowser,
} from "../../components/DocumentPackagePanel";
import styles from "../../ui.module.css";

function badgeClass(recommendation) {
  if (recommendation === "apply") return `${styles.badge} ${styles.badgeApply}`;
  if (recommendation === "consider") return `${styles.badge} ${styles.badgeConsider}`;
  if (recommendation === "reject") return `${styles.badge} ${styles.badgeReject}`;
  return `${styles.badge} ${styles.badgeSkip}`;
}

/** Score chips: >=80 green, 61–79 yellow, <=60 red. hardPenalty is inverted (0 = good). */
function componentPillClass(key, value) {
  const num = Number(value);
  if (Number.isNaN(num)) return styles.pillNeutral;
  if (key === "hardPenalty") {
    if (num <= 0) return styles.pillGood;
    if (num < 25) return styles.pillWarn;
    return styles.pillBad;
  }
  if (num >= 80) return styles.pillGood;
  if (num >= 61) return styles.pillWarn;
  return styles.pillBad;
}

const ANALYZE_STEPS = [
  "Extracting requirements with Ollama…",
  "Matching against your evidence bank…",
  "Scoring gaps and recommendation…",
  "Almost done…",
];

const GENERATE_STEPS = [
  "Selecting grounded evidence…",
  "Drafting tailored resume…",
  "Writing cover letter with Ollama…",
  "Rendering PDF and DOCX files…",
  "Writing application answers…",
  "Saving package to disk…",
];

export default function JobDetailPage() {
  const params = useParams();
  const router = useRouter();
  const jobId = params.jobId;
  const [job, setJob] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [statusText, setStatusText] = useState("");
  const [statusIndex, setStatusIndex] = useState(0);
  const [message, setMessage] = useState("");
  const [pkg, setPkg] = useState(null);

  async function load() {
    try {
      const data = await apiGet(`/jobs/${jobId}`);
      setJob(data);
    } catch (err) {
      setError(err.message || "Failed to load job");
    }
  }

  async function loadPackage() {
    const cached = loadPackageFromBrowser(jobId);
    if (cached?.previews) setPkg(cached);
    try {
      const remote = await apiGet(`/jobs/${jobId}/package`);
      setPkg(remote);
      savePackageToBrowser(jobId, remote);
    } catch {
      // no package yet
    }
  }

  useEffect(() => {
    load();
    loadPackage();
  }, [jobId]);

  useEffect(() => {
    if (!busy) return undefined;
    const steps =
      busy === "analyze"
        ? ANALYZE_STEPS
        : busy === "generate"
          ? GENERATE_STEPS
          : ["Working…"];
    setStatusIndex(0);
    setStatusText(steps[0]);
    const id = setInterval(() => {
      setStatusIndex((prev) => {
        const next = Math.min(prev + 1, steps.length - 1);
        setStatusText(steps[next]);
        return next;
      });
    }, busy === "generate" ? 3200 : 2800);
    return () => clearInterval(id);
  }, [busy]);

  async function run(action) {
    setBusy(action);
    setMessage("");
    setError("");
    try {
      if (action === "analyze") {
        await apiPost(`/jobs/${jobId}/analyze`);
        setMessage("Analysis refreshed.");
      } else if (action === "generate") {
        const generated = await apiPost(`/jobs/${jobId}/generate`);
        setPkg(generated);
        savePackageToBrowser(jobId, generated);
        setMessage(`Package ready: ${generated.folderName} (saved in this browser)`);
      } else {
        await apiPost(`/jobs/${jobId}/decision`, { decision: action });
        setMessage(`Decision recorded: ${action}`);
      }
      await load();
    } catch (err) {
      setError(err.message || "Action failed");
    } finally {
      setBusy("");
      setStatusText("");
    }
  }

  async function deleteJob() {
    const label = `${job?.title || "this job"} — ${job?.company || ""}`.trim();
    const ok = window.confirm(
      `Delete ${label}?\n\nThis removes the job, match, decisions, application package, generated files, and gap references. This cannot be undone.`
    );
    if (!ok) return;

    setBusy("delete");
    setMessage("");
    setError("");
    try {
      await apiDelete(`/jobs/${jobId}`);
      clearPackageFromBrowser(jobId);
      router.push("/");
    } catch (err) {
      setError(err.message || "Delete failed");
      setBusy("");
      setStatusText("");
    }
  }

  if (error && !job) {
    return <div className={styles.error}>{error}</div>;
  }

  if (!job) {
    return (
      <div className={styles.statusPanel} role="status">
        <div className={styles.spinner} aria-hidden="true" />
        <div>
          <p className={styles.statusTitle}>Loading job</p>
          <p className={styles.statusText}>Fetching match details…</p>
        </div>
      </div>
    );
  }

  const match = job.match;
  const steps =
    busy === "analyze"
      ? ANALYZE_STEPS
      : busy === "generate"
        ? GENERATE_STEPS
        : [];

  const openHref =
    job.canonicalApplyUrl || job.url || job.sourceUrl || "";

  return (
    <div>
      <div className={styles.row}>
        <div>
          <h1 className={styles.pageTitle}>
            {job.title} — {job.company}
          </h1>
          <p className={styles.subtitle}>
            {job.location || "Location n/a"} · {job.workMode || "unknown"} · status:{" "}
            {job.status}
          </p>
        </div>
        {openHref ? (
          <a
            className={styles.btn}
            href={openHref}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open
          </a>
        ) : null}
      </div>

      {error ? <div className={styles.error}>{error}</div> : null}
      {message && !busy ? <p className={styles.meta}>{message}</p> : null}

      {busy === "analyze" || busy === "generate" ? (
        <div
          className={
            busy === "generate"
              ? `${styles.statusPanel} ${styles.statusPanelGenerate}`
              : styles.statusPanel
          }
          role="status"
          aria-live="polite"
        >
          <div
            className={
              busy === "generate" ? `${styles.spinner} ${styles.spinnerLarge}` : styles.spinner
            }
            aria-hidden="true"
          />
          <div>
            <p className={styles.statusTitle}>
              {busy === "analyze" ? "Re-analyzing" : "Generating application package"}
            </p>
            <p className={styles.statusText}>{statusText}</p>
            {busy === "generate" ? (
              <ul className={styles.statusStepList}>
                {GENERATE_STEPS.map((step, idx) => (
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
            ) : (
              <div className={styles.statusDots}>
                {steps.map((_, idx) => (
                  <span
                    key={idx}
                    className={
                      idx <= statusIndex
                        ? `${styles.statusDot} ${styles.statusDotActive}`
                        : styles.statusDot
                    }
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      ) : null}

      <div className={styles.actions}>
        <button
          className={styles.btnSecondary + " " + styles.btn}
          onClick={() => run("analyze")}
          disabled={!!busy}
        >
          {busy === "analyze" ? "Analyzing…" : "Re-analyze"}
        </button>
        <button
          className={styles.btn}
          onClick={() => run("generate")}
          disabled={!!busy || !match}
        >
          {busy === "generate" ? (
            <span className={styles.btnBusy}>
              <span className={styles.spinnerInline} aria-hidden="true" />
              Generating…
            </span>
          ) : (
            "Generate documents"
          )}
        </button>
        <button
          className={styles.btnSecondary + " " + styles.btn}
          onClick={() => run("apply")}
          disabled={!!busy}
        >
          Apply
        </button>
        <button
          className={styles.btnSecondary + " " + styles.btn}
          onClick={() => run("save")}
          disabled={!!busy}
        >
          Save
        </button>
        <button
          className={styles.btnSecondary + " " + styles.btn}
          onClick={() => run("reject")}
          disabled={!!busy}
        >
          Reject
        </button>
        <button
          className={`${styles.btn} ${styles.btnDanger}`}
          onClick={deleteJob}
          disabled={!!busy}
        >
          {busy === "delete" ? "Deleting…" : "Delete job"}
        </button>
      </div>

      {match ? (
        <>
          <section className={styles.section}>
            <div className={styles.row}>
              <h2>Match {match.score}/100</h2>
              <span className={badgeClass(match.recommendation)}>
                {match.recommendation}
              </span>
            </div>
            <p className={styles.meta}>
              Role family: {match.roleFamily}
              {match.whyViable ? ` · ${match.whyViable}` : ""}
            </p>
            {match.components ? (
              <div className={styles.pillRow}>
                {Object.entries(match.components).map(([key, value]) => (
                  <span
                    className={`${styles.pill} ${componentPillClass(key, value)}`}
                    key={key}
                  >
                    {key}: {value}
                  </span>
                ))}
              </div>
            ) : null}
          </section>

          <section className={styles.section}>
            <div className={styles.row}>
              <h2>Fit assessment</h2>
              <div className={styles.legend}>
                <span className={styles.fitStrong}>Strength</span>
                <span className={styles.fitWarning}>Warning</span>
                <span className={styles.fitGap}>Gap</span>
              </div>
            </div>
            <div className={styles.fitTableWrap}>
              <table className={styles.fitTable}>
                <thead>
                  <tr>
                    <th>Area</th>
                    <th>Your fit</th>
                    <th>Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {(match.strongMatches || []).map((item, idx) => (
                    <tr key={`s-${idx}`}>
                      <td>{item.requirement}</td>
                      <td className={styles.fitStrong}>
                        <strong>Strong</strong>
                      </td>
                      <td className={styles.meta}>
                        {item.evidenceLevel || "verified evidence"}
                      </td>
                    </tr>
                  ))}
                  {(match.warnings || []).map((item, idx) => (
                    <tr key={`w-${idx}`}>
                      <td>{item.skill || item.requirement}</td>
                      <td className={styles.fitWarning}>
                        <strong>{item.label || "Warning"}</strong>
                      </td>
                      <td className={styles.meta}>{item.reason}</td>
                    </tr>
                  ))}
                  {(match.meaningfulGaps || []).map((item, idx) => (
                    <tr key={`g-${idx}`}>
                      <td>{item.skill}</td>
                      <td className={styles.fitGap}>
                        <strong>{item.label || "Gap"}</strong>
                      </td>
                      <td className={styles.meta}>{item.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : (
        <p className={styles.empty}>Not analyzed yet.</p>
      )}

      <section className={styles.section}>
        <h2>Description</h2>
        <div className={styles.card}>
          <pre
            style={{
              whiteSpace: "pre-wrap",
              margin: 0,
              color: "var(--text)",
              fontFamily: "inherit",
              fontSize: "0.9rem",
            }}
          >
            {job.descriptionRaw}
          </pre>
        </div>
      </section>

      {pkg ? <DocumentPackagePanel jobId={jobId} package={pkg} /> : null}
    </div>
  );
}
