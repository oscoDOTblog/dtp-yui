"use client";

import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardPanel } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { applicationStatusLabel } from "../../lib/applicationStatus";
import {
  buildMonthCells,
  dayCountMap,
  formatDayHeading,
  localDayKey,
  monthLabel,
  todayLocalDayKey,
} from "../../lib/applicationDays";

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function DayApps({ apps, dayKey }) {
  if (!dayKey) {
    return (
      <p className="py-4 text-sm text-muted-foreground">Select a day.</p>
    );
  }
  if (!apps.length) {
    return (
      <p className="py-4 text-sm text-muted-foreground">
        No applications on {formatDayHeading(dayKey)}.
      </p>
    );
  }
  return (
    <div className="grid gap-2.5">
      <h3 className="m-0 text-base font-semibold">
        {formatDayHeading(dayKey)}{" "}
        <span className="font-normal text-muted-foreground">
          · {apps.length}
        </span>
      </h3>
      {apps.map((app) => (
        <Card key={app.jobId || `${dayKey}-${app.appliedAt}`}>
          <CardPanel className="flex flex-wrap items-baseline justify-between gap-2 p-3">
            <div className="min-w-0">
              <p className="m-0 text-sm font-semibold">
                {app.title || "Job"} — {app.company || "Company"}
              </p>
              {app.jobId ? (
                <a
                  href={`/jobs/${app.jobId}`}
                  className="text-xs text-primary underline-offset-2 hover:underline"
                >
                  View job
                </a>
              ) : null}
            </div>
            <Badge variant="outline">
              {applicationStatusLabel(app.applicationStatus) ||
                app.applicationStatus ||
                "—"}
            </Badge>
          </CardPanel>
        </Card>
      ))}
    </div>
  );
}

export default function ApplicationsCalendar({
  apps = [],
  dailyTarget = 10,
}) {
  const now = new Date();
  const [cursor, setCursor] = useState({
    year: now.getFullYear(),
    month: now.getMonth(),
  });
  const [selectedDay, setSelectedDay] = useState(todayLocalDayKey());

  const counts = useMemo(() => dayCountMap(apps), [apps]);
  const cells = useMemo(
    () => buildMonthCells(cursor.year, cursor.month),
    [cursor.year, cursor.month],
  );

  const selectedApps = useMemo(() => {
    if (!selectedDay) return [];
    return apps
      .filter((app) => localDayKey(app.appliedAt) === selectedDay)
      .sort((a, b) => {
        const ta = new Date(a.appliedAt).getTime() || 0;
        const tb = new Date(b.appliedAt).getTime() || 0;
        return tb - ta;
      });
  }, [apps, selectedDay]);

  const target = Math.max(1, Number(dailyTarget) || 10);

  function shiftMonth(delta) {
    setCursor((prev) => {
      const d = new Date(prev.year, prev.month + delta, 1);
      return { year: d.getFullYear(), month: d.getMonth() };
    });
  }

  return (
    <div className="grid gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="m-0 text-lg font-semibold tracking-tight">
          {monthLabel(cursor.year, cursor.month)}
        </h2>
        <div className="flex gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => shiftMonth(-1)}
            aria-label="Previous month"
          >
            Prev
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              const t = new Date();
              setCursor({ year: t.getFullYear(), month: t.getMonth() });
              setSelectedDay(todayLocalDayKey());
            }}
          >
            Today
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => shiftMonth(1)}
            aria-label="Next month"
          >
            Next
          </Button>
        </div>
      </div>

      <div
        className="grid grid-cols-7 gap-1.5 sm:gap-2"
        role="grid"
        aria-label="Applications calendar"
      >
        {WEEKDAYS.map((label) => (
          <div
            key={label}
            className="px-1 pb-1 text-center text-xs font-medium uppercase tracking-wide text-muted-foreground"
          >
            {label}
          </div>
        ))}
        {cells.map((cell) => {
          const count = counts.get(cell.dayKey) || 0;
          const selected = selectedDay === cell.dayKey;
          const met = count >= target;
          const partial = count > 0 && count < target;
          return (
            <button
              key={cell.dayKey}
              type="button"
              role="gridcell"
              onClick={() => setSelectedDay(cell.dayKey)}
              aria-label={`${cell.dayKey}: ${count} applications`}
              aria-pressed={selected}
              className={cn(
                "flex min-h-14 flex-col items-center justify-center gap-0.5 rounded-lg border p-1.5 text-sm transition-colors sm:min-h-16",
                cell.inMonth
                  ? "border-border bg-card"
                  : "border-transparent bg-transparent text-muted-foreground/50",
                cell.isToday && "ring-1 ring-primary/60",
                selected && "border-primary bg-primary/10",
                met && cell.inMonth && "bg-primary/15 text-foreground",
                partial && cell.inMonth && !selected && "border-primary/40",
                "hover:border-primary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              )}
            >
              <span
                className={cn(
                  "tabular-nums leading-none",
                  !cell.inMonth && "opacity-50",
                )}
              >
                {cell.day}
              </span>
              {count > 0 ? (
                <span
                  className={cn(
                    "text-xs font-semibold tabular-nums leading-none",
                    met ? "text-primary" : "text-muted-foreground",
                  )}
                >
                  {count}
                </span>
              ) : (
                <span className="text-xs leading-none opacity-0">0</span>
              )}
            </button>
          );
        })}
      </div>

      <DayApps apps={selectedApps} dayKey={selectedDay} />
    </div>
  );
}
