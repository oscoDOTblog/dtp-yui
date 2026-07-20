"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPatch, apiPost } from "../../lib/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

const KIND_FILTERS = [
  { id: "all", label: "All kinds" },
  { id: "gap", label: "Gaps only" },
  { id: "warning", label: "Warnings only" },
];

const STATUS_FILTERS = [
  { id: "all", label: "All status" },
  { id: "open", label: "Open" },
  { id: "learning", label: "Learning" },
  { id: "resolved", label: "Resolved" },
];

function rowTone(gap) {
  const gapCount = gap.kindCounts?.gap || 0;
  const warnCount = gap.kindCounts?.warning || 0;
  if (gapCount >= warnCount && gapCount > 0) {
    return "shadow-[inset_3px_0_0_var(--destructive)]";
  }
  if (warnCount > 0) {
    return "shadow-[inset_3px_0_0_var(--warning)]";
  }
  return "";
}

function formatSeen(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

function statusVariant(status) {
  if (status === "resolved") return "success";
  if (status === "learning") return "warning";
  return "outline";
}

export default function GapsPage() {
  const [kind, setKind] = useState("all");
  const [status, setStatus] = useState("open");
  const [gaps, setGaps] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busyId, setBusyId] = useState("");
  const [rebuilding, setRebuilding] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ kind, status });
      const data = await apiGet(`/gaps?${params.toString()}`);
      setGaps(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err.message || "Failed to load gaps");
      setGaps([]);
    } finally {
      setLoading(false);
    }
  }, [kind, status]);

  useEffect(() => {
    load();
  }, [load]);

  async function setGapStatus(gapId, nextStatus) {
    setBusyId(gapId);
    setError("");
    try {
      await apiPatch(`/gaps/${gapId}`, { status: nextStatus });
      await load();
    } catch (err) {
      setError(err.message || "Failed to update status");
    } finally {
      setBusyId("");
    }
  }

  async function rebuild() {
    setRebuilding(true);
    setError("");
    setInfo("");
    try {
      const result = await apiPost("/gaps/rebuild");
      setInfo(
        `Rebuilt from ${result.matchesScanned} matches · ${result.requirementsTouched} requirements · cleared ${result.deleted} prior rows`,
      );
      await load();
    } catch (err) {
      setError(err.message || "Rebuild failed");
    } finally {
      setRebuilding(false);
    }
  }

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-baseline justify-between gap-4">
        <div>
          <h1 className="m-0 mb-1.5 text-3xl font-semibold tracking-tight max-sm:text-2xl">
            Gaps
          </h1>
          <p className="m-0 text-muted-foreground">
            Recurring missing requirements across analyses — prioritize what to
            learn or add evidence for.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={rebuild}
          disabled={rebuilding}
          loading={rebuilding}
        >
          {rebuilding ? "Rebuilding…" : "Rebuild from matches"}
        </Button>
      </div>

      {error ? (
        <Alert variant="error" className="mb-4">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      {info ? (
        <Alert variant="warning" className="mb-4">
          <AlertDescription>{info}</AlertDescription>
        </Alert>
      ) : null}

      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-1.5">
          {KIND_FILTERS.map((f) => (
            <Button
              key={f.id}
              type="button"
              size="sm"
              variant={kind === f.id ? "default" : "outline"}
              className="rounded-full"
              onClick={() => setKind(f.id)}
            >
              {f.label}
            </Button>
          ))}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {STATUS_FILTERS.map((f) => (
            <Button
              key={f.id}
              type="button"
              size="sm"
              variant={status === f.id ? "default" : "outline"}
              className="rounded-full"
              onClick={() => setStatus(f.id)}
            >
              {f.label}
            </Button>
          ))}
        </div>
      </div>

      {loading ? (
        <p className="py-8 text-muted-foreground">Loading…</p>
      ) : null}

      {!loading && gaps.length === 0 ? (
        <p className="py-8 text-muted-foreground">
          No gap insights yet. Analyze jobs, or rebuild from existing matches.
        </p>
      ) : null}

      {!loading && gaps.length > 0 ? (
        <div className="overflow-x-auto rounded-xl border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Requirement</TableHead>
                <TableHead>Seen</TableHead>
                <TableHead>Gaps</TableHead>
                <TableHead>Warnings</TableHead>
                <TableHead>Last seen</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {gaps.map((gap) => {
                const lastJob = [
                  gap.lastJobTitle,
                  gap.lastCompany ? `@ ${gap.lastCompany}` : "",
                ]
                  .filter(Boolean)
                  .join(" ");
                return (
                  <TableRow key={gap._id} className={cn(rowTone(gap))}>
                    <TableCell>
                      <strong>{gap.displayName || gap.normalizedName}</strong>
                      {gap.sampleReasons?.[0] ? (
                        <p className="mt-1 m-0 text-sm text-muted-foreground">
                          {gap.sampleReasons[0]}
                        </p>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <span className="text-xl font-bold text-primary">
                        {gap.totalSeen}
                      </span>
                    </TableCell>
                    <TableCell className="font-bold text-destructive-foreground">
                      {gap.kindCounts?.gap || 0}
                    </TableCell>
                    <TableCell className="font-bold text-warning-foreground">
                      {gap.kindCounts?.warning || 0}
                    </TableCell>
                    <TableCell>
                      <div>{formatSeen(gap.lastSeenAt)}</div>
                      {lastJob ? (
                        <p className="mt-1 m-0 text-sm text-muted-foreground">
                          {gap.lastJobId ? (
                            <a href={`/jobs/${gap.lastJobId}`}>{lastJob}</a>
                          ) : (
                            lastJob
                          )}
                        </p>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <Badge variant={statusVariant(gap.status)}>
                        {gap.status || "open"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1.5">
                        {gap.status !== "learning" ? (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            disabled={busyId === gap._id}
                            onClick={() => setGapStatus(gap._id, "learning")}
                          >
                            Learning
                          </Button>
                        ) : null}
                        {gap.status !== "resolved" ? (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            disabled={busyId === gap._id}
                            onClick={() => setGapStatus(gap._id, "resolved")}
                          >
                            Resolved
                          </Button>
                        ) : null}
                        {gap.status !== "open" ? (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            disabled={busyId === gap._id}
                            onClick={() => setGapStatus(gap._id, "open")}
                          >
                            Reopen
                          </Button>
                        ) : null}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      ) : null}
    </div>
  );
}
