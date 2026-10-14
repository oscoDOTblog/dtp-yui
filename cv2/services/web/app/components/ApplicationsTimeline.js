"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardPanel } from "@/components/ui/card";
import {
  applicationStatusLabel,
} from "../../lib/applicationStatus";
import { formatDayHeading, groupByLocalDay } from "../../lib/applicationDays";

function ApplicationRow({ app }) {
  return (
    <Card>
      <CardPanel className="p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="m-0 text-base font-semibold">
            {app.title || "Job"} — {app.company || "Company"}
          </h3>
          <Badge variant="outline">
            {applicationStatusLabel(app.applicationStatus) ||
              app.applicationStatus ||
              "—"}
          </Badge>
        </div>
        <p className="mt-1.5 m-0 text-sm text-muted-foreground">
          Applied:{" "}
          {app.appliedAt
            ? new Date(app.appliedAt).toLocaleString(undefined, {
                month: "short",
                day: "numeric",
                hour: "numeric",
                minute: "2-digit",
              })
            : "—"}
        </p>
        {app.jobId ? (
          <p className="m-0 mt-1 text-sm">
            <a
              href={`/jobs/${app.jobId}`}
              className="text-primary underline-offset-2 hover:underline"
            >
              View job
            </a>
          </p>
        ) : null}
      </CardPanel>
    </Card>
  );
}

export default function ApplicationsTimeline({ apps = [] }) {
  const groups = groupByLocalDay(apps);

  if (!apps.length) {
    return (
      <p className="py-8 text-muted-foreground">
        No applications yet. Open a job and set status to Pending when you
        apply.
      </p>
    );
  }

  return (
    <div className="grid gap-6">
      {groups.map((group) => (
        <section key={group.dayKey}>
          <div className="mb-2.5 flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="m-0 text-lg font-semibold tracking-tight">
              {formatDayHeading(group.dayKey)}
            </h2>
            <span className="text-sm tabular-nums text-muted-foreground">
              {group.apps.length}{" "}
              {group.apps.length === 1 ? "application" : "applications"}
            </span>
          </div>
          <div className="grid gap-3">
            {group.apps.map((app) => (
              <ApplicationRow
                key={app.jobId || `${group.dayKey}-${app.appliedAt}`}
                app={app}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
