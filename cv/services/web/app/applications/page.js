import { apiGet } from "../../lib/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardPanel } from "@/components/ui/card";

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
      <h1 className="m-0 mb-1.5 text-3xl font-semibold tracking-tight max-sm:text-2xl">
        Applications
      </h1>
      <p className="mb-6 text-muted-foreground">
        Generated packages under <code>generated-applications/</code> on the
        Legion.
      </p>

      {error ? (
        <Alert variant="error" className="mb-4">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {!error && apps.length === 0 ? (
        <p className="py-8 text-muted-foreground">
          No packages yet. Open a job and click Generate documents.
        </p>
      ) : null}

      <div className="grid gap-3.5">
        {apps.map((app) => (
          <Card key={app._id}>
            <CardPanel className="p-4">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="m-0 text-base font-semibold">
                  {app.job?.title || "Job"} — {app.job?.company || "Company"}
                </h2>
                <Badge variant="outline">{app.status}</Badge>
              </div>
              <p className="mt-1.5 m-0 text-sm text-muted-foreground">
                Package: {app.package?.folderName || app.packageId}
              </p>
              <p className="m-0 text-sm text-muted-foreground">
                Updated: {app.updatedAt}
              </p>
              {app.job?._id ? (
                <p className="m-0 text-sm text-muted-foreground">
                  <a href={`/jobs/${app.job._id}`}>View job</a>
                </p>
              ) : null}
            </CardPanel>
          </Card>
        ))}
      </div>
    </div>
  );
}
