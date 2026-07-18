import { apiGet } from "../lib/api";
import styles from "./ui.module.css";

function badgeClass(recommendation) {
  if (recommendation === "apply") return `${styles.badge} ${styles.badgeApply}`;
  if (recommendation === "consider") return `${styles.badge} ${styles.badgeConsider}`;
  if (recommendation === "reject") return `${styles.badge} ${styles.badgeReject}`;
  return `${styles.badge} ${styles.badgeSkip}`;
}

export default async function HomePage() {
  let jobs = [];
  let error = null;
  try {
    jobs = await apiGet("/jobs");
  } catch (err) {
    error = err.message || "Failed to load jobs";
  }

  return (
    <div>
      <h1 className={styles.pageTitle}>Inbox</h1>
      <p className={styles.subtitle}>
        Scored jobs awaiting your decision. Paste a listing on Analyze to get started.
      </p>

      {error ? <div className={styles.error}>{error}</div> : null}

      {!error && jobs.length === 0 ? (
        <p className={styles.empty}>
          No jobs yet.{" "}
          <a href="/analyze">Analyze a job description</a> to create your first match.
        </p>
      ) : null}

      <div className={styles.grid}>
        {jobs.map((job) => {
          const match = job.match;
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
                  <span className={styles.meta}>Not analyzed</span>
                )}
              </div>
              <p className={styles.meta}>
                {job.location || "Location n/a"} · {job.workMode || "unknown"} ·{" "}
                {job.status}
              </p>
              {match ? (
                <div className={styles.pillRow}>
                  <span className={badgeClass(match.recommendation)}>
                    {match.recommendation}
                  </span>
                  {match.roleFamily ? (
                    <span className={styles.pill}>{match.roleFamily}</span>
                  ) : null}
                </div>
              ) : null}
            </a>
          );
        })}
      </div>
    </div>
  );
}
