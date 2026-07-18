import { apiGet } from "../../lib/api";
import styles from "../ui.module.css";

export default async function ApplicationsPage() {
  let apps = [];
  let error = null;
  try {
    apps = await apiGet("/applications");
  } catch (err) {
    error = err.message || "Failed to load applications";
  }

  return (
    <div>
      <h1 className={styles.pageTitle}>Applications</h1>
      <p className={styles.subtitle}>
        Generated packages under <code>generated-applications/</code> on the Legion.
      </p>

      {error ? <div className={styles.error}>{error}</div> : null}

      {!error && apps.length === 0 ? (
        <p className={styles.empty}>
          No packages yet. Open a job and click Generate documents.
        </p>
      ) : null}

      <div className={styles.grid}>
        {apps.map((app) => (
          <div className={styles.card} key={app._id}>
            <div className={styles.row}>
              <h2 className={styles.title}>
                {app.job?.title || "Job"} — {app.job?.company || "Company"}
              </h2>
              <span className={styles.badge}>{app.status}</span>
            </div>
            <p className={styles.meta}>
              Package: {app.package?.folderName || app.packageId}
            </p>
            <p className={styles.meta}>Updated: {app.updatedAt}</p>
            {app.job?._id ? (
              <p className={styles.meta}>
                <a href={`/jobs/${app.job._id}`}>View job</a>
              </p>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}
