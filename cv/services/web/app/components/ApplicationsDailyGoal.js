"use client";

import { Progress, ProgressLabel } from "@/components/ui/progress";
import { Card, CardPanel } from "@/components/ui/card";

export default function ApplicationsDailyGoal({
  appliedToday = 0,
  target = 10,
}) {
  const safeTarget = Math.max(1, Number(target) || 10);
  const count = Math.max(0, Number(appliedToday) || 0);
  const percent = Math.min(100, (count / safeTarget) * 100);
  const remaining = Math.max(0, safeTarget - count);
  const met = count >= safeTarget;

  return (
    <Card className="mb-5">
      <CardPanel className="space-y-3 p-4">
        <Progress value={percent}>
          <div className="flex items-center justify-between gap-3">
            <ProgressLabel>Today&apos;s applications</ProgressLabel>
            <span className="text-sm tabular-nums text-muted-foreground">
              {count} / {safeTarget}
            </span>
          </div>
        </Progress>
        <p className="m-0 text-sm text-muted-foreground">
          {met
            ? "Daily target met. Jobs marked pending count as applied."
            : `${remaining} more to hit your daily target. Mark a job pending when you apply.`}{" "}
          Target is set in{" "}
          <a
            href="/settings"
            className="text-primary underline-offset-2 hover:underline"
          >
            Settings
          </a>
          .
        </p>
      </CardPanel>
    </Card>
  );
}
