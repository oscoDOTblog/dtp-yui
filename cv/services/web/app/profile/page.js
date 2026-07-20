import { apiGet } from "../../lib/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardPanel } from "@/components/ui/card";

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
        <h1 className="m-0 mb-1.5 text-3xl font-semibold tracking-tight">
          Profile
        </h1>
        <Alert variant="error" className="mb-4">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
        <p className="text-sm text-muted-foreground">
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
      <h1 className="m-0 mb-1.5 text-3xl font-semibold tracking-tight max-sm:text-2xl">
        {candidate.name}
      </h1>
      <p className="mb-6 text-muted-foreground">
        {candidate.location} · {candidate.email} ·{" "}
        <a href={candidate.linkedin} target="_blank" rel="noreferrer">
          LinkedIn
        </a>{" "}
        ·{" "}
        <a href={candidate.github} target="_blank" rel="noreferrer">
          GitHub
        </a>
      </p>

      <section className="mt-7">
        <h2 className="mb-3 text-lg font-semibold">Education</h2>
        <ul className="m-0 list-disc space-y-1.5 pl-4.5">
          {(candidate.education || []).map((edu, idx) => (
            <li key={idx}>
              <strong>{edu.institution}</strong> — {edu.degree} (
              {edu.graduatedAt})
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-7">
        <h2 className="mb-3 text-lg font-semibold">Preferences</h2>
        <p className="m-0 text-sm text-muted-foreground">
          Min salary: $
          {candidate.minimumSalary?.toLocaleString?.() ||
            candidate.minimumSalary}{" "}
          · Remote: {candidate.remotePreference}
        </p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {(candidate.preferredRoles || []).map((role) => (
            <Badge variant="outline" key={role}>
              {role}
            </Badge>
          ))}
        </div>
      </section>

      <section className="mt-7">
        <h2 className="mb-3 text-lg font-semibold">Positioning</h2>
        {Object.entries(candidate.positioningSummaries || {}).map(
          ([key, text]) => (
            <Card key={key} className="mb-3">
              <CardPanel className="p-4">
                <strong className="capitalize text-primary">{key}</strong>
                <p className="mt-1.5 m-0 text-sm text-muted-foreground">
                  {text}
                </p>
              </CardPanel>
            </Card>
          ),
        )}
      </section>

      <section className="mt-7">
        <h2 className="mb-3 text-lg font-semibold">Work history</h2>
        {workHistory.map((role) => (
          <Card key={role._id} className="mb-3">
            <CardPanel className="p-4">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="m-0 text-base font-semibold">
                  {role.title} · {role.company}
                </h3>
                <span className="text-sm text-muted-foreground">
                  {role.startDate} – {role.endDate}
                </span>
              </div>
              <ul className="mt-2 mb-0 list-disc space-y-1 pl-4.5">
                {(role.bullets || []).map((b, idx) => (
                  <li key={idx}>{b}</li>
                ))}
              </ul>
            </CardPanel>
          </Card>
        ))}
      </section>

      <section className="mt-7">
        <h2 className="mb-3 text-lg font-semibold">Projects</h2>
        <div className="grid gap-3.5">
          {projects.map((project) => (
            <Card key={project._id}>
              <CardPanel className="p-4">
                <h3 className="m-0 text-base font-semibold">{project.name}</h3>
                <p className="mt-1.5 m-0 text-sm text-muted-foreground">
                  {project.summary}
                </p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {(project.technologies || []).slice(0, 8).map((tech) => (
                    <Badge variant="outline" key={tech}>
                      {tech}
                    </Badge>
                  ))}
                </div>
              </CardPanel>
            </Card>
          ))}
        </div>
      </section>

      <section className="mt-7">
        <h2 className="mb-3 text-lg font-semibold">
          Skills ({skills.length})
        </h2>
        {Object.entries(byCategory)
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([category, items]) => (
            <div key={category} className="mb-4">
              <h3 className="m-0 mb-2 text-base font-semibold capitalize">
                {category}
              </h3>
              <div className="flex flex-wrap gap-1.5">
                {items.map((skill) => (
                  <Badge
                    variant="outline"
                    key={skill._id}
                    title={skill.evidenceLevel}
                  >
                    {skill.name}
                  </Badge>
                ))}
              </div>
            </div>
          ))}
      </section>
    </div>
  );
}
