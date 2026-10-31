"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiGet } from "../../lib/api";
import {
  countToday,
  localDayKey,
  loadViewMode,
  saveViewMode,
  todayLocalDayKey,
} from "../../lib/applicationDays";
import { Alert, AlertDescription } from "@/components/ui/alert";
import ApplicationsAnalysisSummary from "../components/ApplicationsAnalysisSummary";
import ApplicationsCalendar from "../components/ApplicationsCalendar";
import ApplicationsDailyGoal from "../components/ApplicationsDailyGoal";
import ApplicationsTimeline from "../components/ApplicationsTimeline";
import ApplicationsViewToggle from "../components/ApplicationsViewToggle";

const DEFAULT_TARGET = 10;

export default function ApplicationsPage() {
  const [apps, setApps] = useState([]);
  const [recentJobs, setRecentJobs] = useState([]);
  const [target, setTarget] = useState(DEFAULT_TARGET);
  const [viewMode, setViewMode] = useState("timeline");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setViewMode(loadViewMode());
  }, []);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [tracker, settings, jobs] = await Promise.all([
        apiGet("/applications/tracker"),
        apiGet("/settings").catch(() => null),
        apiGet("/jobs?recent=true").catch(() => []),
      ]);
      setApps(Array.isArray(tracker) ? tracker : []);
      setRecentJobs(Array.isArray(jobs) ? jobs : []);
      const t = Number(settings?.dailyApplicationsTarget);
      setTarget(Number.isFinite(t) && t > 0 ? t : DEFAULT_TARGET);
    } catch (err) {
      setError(err.message || "Failed to load applications");
      setApps([]);
      setRecentJobs([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function handleViewChange(mode) {
    setViewMode(mode);
    saveViewMode(mode);
  }

  const appliedToday = useMemo(() => countToday(apps), [apps]);
  const analyzedTodayJobs = useMemo(
    () => {
      const today = todayLocalDayKey();
      return recentJobs.filter(
        (job) => localDayKey(job.match?.generatedAt) === today,
      );
    },
    [recentJobs],
  );
  const readyToApply = useMemo(
    () =>
      analyzedTodayJobs.filter(
        (job) =>
          job.locationAssessment?.bayAreaEligible === true &&
          job.roleAssessment?.roleEligible === true &&
          !["out_of_area", "wrong_role"].includes(job.status),
      ).length,
    [analyzedTodayJobs],
  );

  return (
    <div>
      <h1 className="m-0 mb-1.5 text-3xl font-semibold tracking-tight max-sm:text-2xl">
        Applications
      </h1>
      <p className="mb-6 text-muted-foreground">
        Jobs you have applied to (status set to Pending). Track daily progress
        and review by timeline or calendar.
      </p>

      {error ? (
        <Alert variant="error" className="mb-4">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {loading ? (
        <p className="py-8 text-muted-foreground">Loading…</p>
      ) : (
        <>
          <ApplicationsAnalysisSummary
            analyzedToday={analyzedTodayJobs.length}
            readyToApply={readyToApply}
          />
          <ApplicationsDailyGoal
            appliedToday={appliedToday}
            target={target}
          />
          <ApplicationsViewToggle
            value={viewMode}
            onChange={handleViewChange}
          />
          {viewMode === "calendar" ? (
            <ApplicationsCalendar apps={apps} dailyTarget={target} />
          ) : (
            <ApplicationsTimeline apps={apps} />
          )}
        </>
      )}
    </div>
  );
}
