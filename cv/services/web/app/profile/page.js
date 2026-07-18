import { apiGet } from "../../lib/api";
import styles from "../ui.module.css";

export default async function ProfilePage() {
  let candidate = null;
  let skills = [];
  let projects = [];
  let workHistory = [];
  let error = null;

  try {
    [candidate, skills, projects, workHistory] = await Promise.all([
      apiGet("/candidate"),
      apiGet("/skills"),
      apiGet("/projects"),
      apiGet("/work-history"),
    ]);
  } catch (err) {
    error = err.message || "Failed to load profile";
  }

  if (error) {
    return (
      <div>
        <h1 className={styles.pageTitle}>Profile</h1>
        <div className={styles.error}>{error}</div>
        <p className={styles.meta}>
          If Mongo is empty, run seed via worker startup or{" "}
          <code>POST /seed</code> on the API.
        </p>
      </div>
    );
  }

  const byCategory = {};
  for (const skill of skills) {
    const cat = skill.category || "other";
    if (!byCategory[cat]) byCategory[cat] = [];
    byCategory[cat].push(skill);
  }

  return (
    <div>
      <h1 className={styles.pageTitle}>{candidate.name}</h1>
      <p className={styles.subtitle}>
        {candidate.location} · {candidate.email} ·{" "}
        <a href={candidate.linkedin} target="_blank" rel="noreferrer">
          LinkedIn
        </a>{" "}
        ·{" "}
        <a href={candidate.github} target="_blank" rel="noreferrer">
          GitHub
        </a>
      </p>

      <section className={styles.section}>
        <h2>Education</h2>
        <ul className={styles.list}>
          {(candidate.education || []).map((edu, idx) => (
            <li key={idx}>
              <strong>{edu.institution}</strong> — {edu.degree} ({edu.graduatedAt})
            </li>
          ))}
        </ul>
      </section>

      <section className={styles.section}>
        <h2>Preferences</h2>
        <p className={styles.meta}>
          Min salary: ${candidate.minimumSalary?.toLocaleString?.() || candidate.minimumSalary} ·
          Remote: {candidate.remotePreference}
        </p>
        <div className={styles.pillRow}>
          {(candidate.preferredRoles || []).map((role) => (
            <span className={styles.pill} key={role}>
              {role}
            </span>
          ))}
        </div>
      </section>

      <section className={styles.section}>
        <h2>Positioning</h2>
        {Object.entries(candidate.positioningSummaries || {}).map(([key, text]) => (
          <div className={styles.card} key={key} style={{ marginBottom: "0.75rem" }}>
            <strong style={{ color: "var(--pink)", textTransform: "capitalize" }}>
              {key}
            </strong>
            <p className={styles.meta}>{text}</p>
          </div>
        ))}
      </section>

      <section className={styles.section}>
        <h2>Work history</h2>
        {workHistory.map((role) => (
          <div className={styles.card} key={role._id} style={{ marginBottom: "0.75rem" }}>
            <div className={styles.row}>
              <h3 className={styles.title}>
                {role.title} · {role.company}
              </h3>
              <span className={styles.meta}>
                {role.startDate} – {role.endDate}
              </span>
            </div>
            <ul className={styles.list}>
              {(role.bullets || []).map((b, idx) => (
                <li key={idx}>{b}</li>
              ))}
            </ul>
          </div>
        ))}
      </section>

      <section className={styles.section}>
        <h2>Projects</h2>
        <div className={styles.grid}>
          {projects.map((project) => (
            <div className={styles.card} key={project._id}>
              <h3 className={styles.title}>{project.name}</h3>
              <p className={styles.meta}>{project.summary}</p>
              <div className={styles.pillRow}>
                {(project.technologies || []).slice(0, 8).map((tech) => (
                  <span className={styles.pill} key={tech}>
                    {tech}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className={styles.section}>
        <h2>Skills ({skills.length})</h2>
        {Object.entries(byCategory)
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([category, items]) => (
            <div key={category} style={{ marginBottom: "1rem" }}>
              <h3 className={styles.title} style={{ textTransform: "capitalize" }}>
                {category}
              </h3>
              <div className={styles.pillRow}>
                {items.map((skill) => (
                  <span className={styles.pill} key={skill._id} title={skill.evidenceLevel}>
                    {skill.name}
                  </span>
                ))}
              </div>
            </div>
          ))}
      </section>
    </div>
  );
}
