"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPatch, apiPost } from "../../lib/api";
import styles from "../ui.module.css";

const KIND_FILTERS = [
  { id: "all", label: "All kinds" },
  { id: "gap", label: "Gaps only" },
  { id: "warning", label: "Warnings only" },
];

const STATUS_FILTERS = [
  { id: "all", label: "All status" },
  { id: "open", label: "Open" },
  { id: "learning", label: "Learning" },
  { id: "resolved", label: "Resolved" },
];

function rowTone(gap) {
  const gapCount = gap.kindCounts?.gap || 0;
  const warnCount = gap.kindCounts?.warning || 0;
  if (gapCount >= warnCount && gapCount > 0) return styles.gapRowHeavy;
  if (warnCount > 0) return styles.gapRowWarn;
  return "";
}

function formatSeen(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

export default function GapsPage() {
  const [kind, setKind] = useState("all");
  const [status, setStatus] = useState("open");
  const [gaps, setGaps] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busyId, setBusyId] = useState("");
  const [rebuilding, setRebuilding] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ kind, status });
      const data = await apiGet(`/gaps?${params.toString()}`);
      setGaps(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err.message || "Failed to load gaps");
      setGaps([]);
    } finally {
      setLoading(false);
    }
  }, [kind, status]);

  useEffect(() => {
    load();
  }, [load]);

  async function setGapStatus(gapId, nextStatus) {
    setBusyId(gapId);
    setError("");
    try {
      await apiPatch(`/gaps/${gapId}`, { status: nextStatus });
      await load();
    } catch (err) {
      setError(err.message || "Failed to update status");
    } finally {
      setBusyId("");
    }
  }

  async function rebuild() {
    setRebuilding(true);
    setError("");
    setInfo("");
    try {
      const result = await apiPost("/gaps/rebuild");
      setInfo(
        `Rebuilt from ${result.matchesScanned} matches · ${result.requirementsTouched} requirements · cleared ${result.deleted} prior rows`
      );
      await load();
    } catch (err) {
      setError(err.message || "Rebuild failed");
    } finally {
      setRebuilding(false);
    }
  }

  return (
    <div>
      <div className={styles.row}>
        <div>
          <h1 className={styles.pageTitle}>Gaps</h1>
          <p className={styles.subtitle}>
            Recurring missing requirements across analyses — prioritize what to
            learn or add evidence for.
          </p>
        </div>
        <button
          type="button"
          className={`${styles.btn} ${styles.btnSecondary}`}
          onClick={rebuild}
          disabled={rebuilding}
        >
          {rebuilding ? "Rebuilding…" : "Rebuild from matches"}
        </button>
      </div>

      {error ? <div className={styles.error}>{error}</div> : null}
      {info ? <div className={styles.info}>{info}</div> : null}

      <div className={styles.filterBar}>
        <div className={styles.filterGroup}>
          {KIND_FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              className={`${styles.filterChip} ${kind === f.id ? styles.filterChipActive : ""}`}
              onClick={() => setKind(f.id)}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className={styles.filterGroup}>
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              className={`${styles.filterChip} ${status === f.id ? styles.filterChipActive : ""}`}
              onClick={() => setStatus(f.id)}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {loading ? <p className={styles.empty}>Loading…</p> : null}

      {!loading && gaps.length === 0 ? (
        <p className={styles.empty}>
          No gap insights yet. Analyze jobs, or rebuild from existing matches.
        </p>
      ) : null}

      {!loading && gaps.length > 0 ? (
        <div className={styles.fitTableWrap}>
          <table className={styles.fitTable}>
            <thead>
              <tr>
                <th>Requirement</th>
                <th>Seen</th>
                <th>Gaps</th>
                <th>Warnings</th>
                <th>Last seen</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {gaps.map((gap) => {
                const tone = rowTone(gap);
                const lastJob = [
                  gap.lastJobTitle,
                  gap.lastCompany ? `@ ${gap.lastCompany}` : "",
                ]
                  .filter(Boolean)
                  .join(" ");
                return (
                  <tr key={gap._id} className={tone}>
                    <td>
                      <strong>{gap.displayName || gap.normalizedName}</strong>
                      {gap.sampleReasons?.[0] ? (
                        <p className={styles.meta}>{gap.sampleReasons[0]}</p>
                      ) : null}
                    </td>
                    <td>
                      <span className={styles.score}>{gap.totalSeen}</span>
                    </td>
                    <td className={styles.fitGap}>{gap.kindCounts?.gap || 0}</td>
                    <td className={styles.fitWarning}>
                      {gap.kindCounts?.warning || 0}
                    </td>
                    <td>
                      <div>{formatSeen(gap.lastSeenAt)}</div>
                      {lastJob ? (
                        <p className={styles.meta}>
                          {gap.lastJobId ? (
                            <a href={`/jobs/${gap.lastJobId}`}>{lastJob}</a>
                          ) : (
                            lastJob
                          )}
                        </p>
                      ) : null}
                    </td>
                    <td>
                      <span className={`${styles.badge} ${statusBadge(gap.status)}`}>
                        {gap.status || "open"}
                      </span>
                    </td>
                    <td>
                      <div className={styles.actionRow}>
                        {gap.status !== "learning" ? (
                          <button
                            type="button"
                            className={`${styles.btn} ${styles.btnSecondary} ${styles.btnSmall}`}
                            disabled={busyId === gap._id}
                            onClick={() => setGapStatus(gap._id, "learning")}
                          >
                            Learning
                          </button>
                        ) : null}
                        {gap.status !== "resolved" ? (
                          <button
                            type="button"
                            className={`${styles.btn} ${styles.btnSecondary} ${styles.btnSmall}`}
                            disabled={busyId === gap._id}
                            onClick={() => setGapStatus(gap._id, "resolved")}
                          >
                            Resolved
                          </button>
                        ) : null}
                        {gap.status !== "open" ? (
                          <button
                            type="button"
                            className={`${styles.btn} ${styles.btnSecondary} ${styles.btnSmall}`}
                            disabled={busyId === gap._id}
                            onClick={() => setGapStatus(gap._id, "open")}
                          >
                            Reopen
                          </button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

function statusBadge(status) {
  if (status === "resolved") return styles.badgeApply;
  if (status === "learning") return styles.badgeConsider;
  return "";
}
