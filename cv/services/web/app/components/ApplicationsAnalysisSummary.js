"use client";

import Link from "next/link";
import { Card, CardPanel } from "@/components/ui/card";

export default function ApplicationsAnalysisSummary({
  analyzedToday = 0,
  readyToApply = 0,
}) {
  const analyzed = Math.max(0, Number(analyzedToday) || 0);
  const ready = Math.max(0, Number(readyToApply) || 0);

  return (
    <Card className="mb-5">
      <CardPanel className="p-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <p className="m-0 text-sm font-medium text-muted-foreground">
              Analyzed today
            </p>
            <p className="m-0 mt-1 text-3xl font-semibold tabular-nums">
              {analyzed}
            </p>
          </div>
          <div>
            <p className="m-0 text-sm font-medium text-muted-foreground">
              Ready to apply
            </p>
            <p className="m-0 mt-1 text-3xl font-semibold tabular-nums">
              {ready}
            </p>
          </div>
        </div>
        <p className="m-0 mt-3 text-sm text-muted-foreground">
          Apply-ready jobs passed the location and role checks. They count as
          applications only after you mark them Pending.{" "}
          <Link
            href="/"
            className="text-primary underline-offset-2 hover:underline"
          >
            Review jobs
          </Link>
          .
        </p>
      </CardPanel>
    </Card>
  );
}
