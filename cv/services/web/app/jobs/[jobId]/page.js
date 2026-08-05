"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import DocumentPackagePanel, {
  clearPackageFromBrowser,
  loadPackageFromBrowser,
  savePackageToBrowser,
} from "../../components/DocumentPackagePanel";
import ApplicationStatusTracker from "../../components/ApplicationStatusTracker";
import FitAssessmentTable from "../../components/FitAssessmentTable";
import JobTitleEditor from "../../components/JobTitleEditor";
import MarkdownContent from "../../components/MarkdownContent";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardPanel } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import { jobMetaLine } from "../../../lib/jobDisplay";
import {
  applicationStatusLabel,
  resolveApplicationStatus,
} from "../../../lib/applicationStatus";
import { apiDelete, apiGet, apiPatch, apiPost } from "../../../lib/api";

function recommendationVariant(recommendation) {
  if (recommendation === "apply") return "success";
  if (recommendation === "consider") return "warning";
  if (recommendation === "reject") return "error";
  return "outline";
}

/** Score chips: >=80 green, 61–79 yellow, <=60 red. hardPenalty is inverted (0 = good). */
function componentPillVariant(key, value) {
  const num = Number(value);
  if (Number.isNaN(num)) return "outline";
  if (key === "hardPenalty") {
    if (num <= 0) return "success";
    if (num < 25) return "warning";
    return "error";
  }
  if (num >= 80) return "success";
  if (num >= 61) return "warning";
  return "error";
}

const ANALYZE_STEPS = [
  "Extracting requirements with Ollama…",
  "Matching against your evidence bank…",
  "Scoring gaps and recommendation…",
  "Almost done…",
];

const GENERATE_STEPS = [
  "Analyzing role and ATS keywords…",
  "Ranking verified evidence…",
  "Composing tailored resume…",
  "Reviewing resume quality…",
  "Writing cover letter…",
  "Checking resume ↔ cover consistency…",
  "Rendering PDF and DOCX files…",
  "Saving package to disk…",
];

export default function JobDetailPage() {
  const params = useParams();
  const router = useRouter();
  const jobId = params.jobId;
  const [job, setJob] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [statusText, setStatusText] = useState("");
  const [statusIndex, setStatusIndex] = useState(0);
  const [message, setMessage] = useState("");
  const [pkg, setPkg] = useState(null);
  const [fitBusyRequirement, setFitBusyRequirement] = useState("");

  async function load() {
    try {
      const data = await apiGet(`/jobs/${jobId}`);
      setJob(data);
    } catch (err) {
      setError(err.message || "Failed to load job");
    }
  }

  async function loadPackage() {
    const cached = loadPackageFromBrowser(jobId);
    if (cached?.previews) setPkg(cached);
    try {
      const remote = await apiGet(`/jobs/${jobId}/package`);
      setPkg(remote);
      savePackageToBrowser(jobId, remote);
    } catch {
      // no package yet
    }
  }

  useEffect(() => {
    load();
    loadPackage();
  }, [jobId]);

  useEffect(() => {
    if (!busy) return undefined;
    const steps =
      busy === "analyze"
        ? ANALYZE_STEPS
        : busy === "generate"
          ? GENERATE_STEPS
          : ["Working…"];
    setStatusIndex(0);
    setStatusText(steps[0]);
    const id = setInterval(() => {
      setStatusIndex((prev) => {
        const next = Math.min(prev + 1, steps.length - 1);
        setStatusText(steps[next]);
        return next;
      });
    }, busy === "generate" ? 3200 : 2800);
    return () => clearInterval(id);
  }, [busy]);

  async function run(action) {
    setBusy(action);
    setMessage("");
    setError("");
    try {
      if (action === "analyze") {
        await apiPost(`/jobs/${jobId}/analyze`);
        setMessage("Analysis refreshed.");
      } else if (action === "generate") {
        const generated = await apiPost(`/jobs/${jobId}/generate`);
        setPkg(generated);
        savePackageToBrowser(jobId, generated);
        setMessage(
          `Package ready: ${generated.folderName} (saved in this browser)`,
        );
      }
      await load();
    } catch (err) {
      setError(err.message || "Action failed");
    } finally {
      setBusy("");
      setStatusText("");
    }
  }

  async function setApplicationStatus(nextStatus) {
    if (!nextStatus || busy) return;
    const previous = resolveApplicationStatus(job);
    if (previous === nextStatus) return;

    setBusy("status");
    setMessage("");
    setError("");
    // Optimistic UI
    setJob((cur) =>
      cur
        ? {
            ...cur,
            applicationStatus: nextStatus,
            applicationStatusAt: new Date().toISOString(),
          }
        : cur,
    );
    try {
      const result = await apiPatch(`/jobs/${jobId}/application-status`, {
        applicationStatus: nextStatus,
      });
      setMessage(
        `Status set to ${applicationStatusLabel(result.applicationStatus || nextStatus)}`,
      );
      await load();
    } catch (err) {
      setJob((cur) =>
        cur
          ? {
              ...cur,
              applicationStatus: previous,
            }
          : cur,
      );
      setError(err.message || "Failed to update status");
    } finally {
      setBusy("");
      setStatusText("");
    }
  }

  async function setFitOverride(requirement, fit) {
    if (!requirement || !fit || busy) return;
    setBusy("fit");
    setFitBusyRequirement(requirement);
    setMessage("");
    setError("");
    try {
      const result = await apiPatch(`/jobs/${jobId}/fit-overrides`, {
        requirement,
        fit,
      });
      if (result?.match) {
        setJob((cur) =>
          cur
            ? {
                ...cur,
                fitOverrides: result.fitOverrides || cur.fitOverrides,
                match: result.match,
              }
            : cur,
        );
        const label =
          fit === "strong" ? "Strength" : fit === "gap" ? "Gap" : "Warning";
        setMessage(`Fit updated to ${label}. Used on Re-analyze.`);
      } else {
        setMessage("Fit override saved — run Re-analyze to apply.");
        await load();
      }
    } catch (err) {
      setError(err.message || "Failed to update fit");
      await load();
    } finally {
      setBusy("");
      setFitBusyRequirement("");
      setStatusText("");
    }
  }

  /** Save (or reset) the job title. Returns false so the editor stays open on error. */
  async function saveTitle(body, successMessage) {
    if (busy) return false;
    setBusy("title");
    setMessage("");
    setError("");
    try {
      const updated = await apiPatch(`/jobs/${jobId}/title`, body);
      // Replace rather than merge: a reset unsets titleSource/titleAuto
      setJob((cur) => ({ ...updated, match: cur?.match ?? updated.match }));
      setMessage(successMessage);
      return true;
    } catch (err) {
      setError(err.message || "Failed to update title");
      return false;
    } finally {
      setBusy("");
      setStatusText("");
    }
  }

  async function deleteJob() {
    const label = `${job?.title || "this job"} — ${job?.company || ""}`.trim();
    const ok = window.confirm(
      `Delete ${label}?\n\nThis removes the job, match, decisions, application package, generated files, and gap references. This cannot be undone.`,
    );
    if (!ok) return;

    setBusy("delete");
    setMessage("");
    setError("");
    try {
      await apiDelete(`/jobs/${jobId}`);
      clearPackageFromBrowser(jobId);
      router.push("/");
    } catch (err) {
      setError(err.message || "Delete failed");
      setBusy("");
      setStatusText("");
    }
  }

  if (error && !job) {
    return (
      <Alert variant="error">
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  if (!job) {
    return (
      <div
        className="flex max-w-xl items-start gap-4 rounded-xl border border-primary/35 bg-primary/8 p-4"
        role="status"
      >
        <Spinner className="mt-0.5 size-6 text-primary" />
        <div>
          <p className="m-0 mb-1 font-semibold">Loading job</p>
          <p className="m-0 text-sm text-foreground/90">
            Fetching match details…
          </p>
        </div>
      </div>
    );
  }

  const match = job.match;
  const steps =
    busy === "analyze"
      ? ANALYZE_STEPS
      : busy === "generate"
        ? GENERATE_STEPS
        : [];

  const openHref = job.canonicalApplyUrl || job.url || job.sourceUrl || "";

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-4">
        <div className="min-w-0 flex-1">
          <JobTitleEditor
            job={job}
            disabled={!!busy}
            saving={busy === "title"}
            onSave={(title) =>
              saveTitle({ title }, `Title updated to “${title}”.`)
            }
            onReset={() =>
              saveTitle({ reset: true }, "Reverted to the detected title.")
            }
          />
          <p className="m-0 mt-1.5 text-muted-foreground">{jobMetaLine(job)}</p>
        </div>
        {openHref ? (
          <Button
            render={
              <a href={openHref} target="_blank" rel="noopener noreferrer" />
            }
          >
            Open
          </Button>
        ) : null}
      </div>

      {error ? (
        <Alert variant="error" className="mb-4">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      {message && !busy ? (
        <p className="mb-4 text-sm text-muted-foreground">{message}</p>
      ) : null}

      {busy === "analyze" || busy === "generate" ? (
        <div
          className={cn(
            "mb-5 flex items-start gap-4 rounded-xl border border-primary/35 bg-primary/8 p-4",
            busy === "generate" &&
              "p-5 shadow-[0_0_0_1px_rgba(255,20,147,0.12),0_12px_40px_rgba(0,0,0,0.35)]",
          )}
          role="status"
          aria-live="polite"
        >
          <Spinner
            className={cn(
              "mt-0.5 text-primary",
              busy === "generate" ? "size-8" : "size-6",
            )}
          />
          <div className="min-w-0 flex-1">
            <p className="m-0 mb-1 font-semibold">
              {busy === "analyze"
                ? "Re-analyzing"
                : "Generating application package"}
            </p>
            <p className="m-0 min-h-[1.4em] text-sm text-foreground/90">
              {statusText}
            </p>
            {busy === "generate" ? (
              <ul className="mt-3.5 m-0 grid list-none gap-1.5 p-0">
                {GENERATE_STEPS.map((step, idx) => (
                  <li
                    key={step}
                    className={cn(
                      "text-sm",
                      idx < statusIndex && "text-success-foreground",
                      idx === statusIndex && "font-semibold text-primary",
                      idx > statusIndex && "text-muted-foreground/65",
                    )}
                  >
                    {idx < statusIndex
                      ? "✓ "
                      : idx === statusIndex
                        ? "→ "
                        : "○ "}
                    {step}
                  </li>
                ))}
              </ul>
            ) : (
              <div className="mt-3 flex gap-1.5">
                {steps.map((_, idx) => (
                  <span
                    key={idx}
                    className={cn(
                      "size-1.5 rounded-full bg-border",
                      idx <= statusIndex &&
                        "bg-primary shadow-[0_0_8px_rgba(255,20,147,0.55)]",
                    )}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      ) : null}

      <div className="mb-6 flex flex-wrap gap-2.5">
        <Button
          variant="outline"
          onClick={() => run("analyze")}
          disabled={!!busy}
        >
          {busy === "analyze" ? "Analyzing…" : "Re-analyze"}
        </Button>
        <Button
          onClick={() => run("generate")}
          disabled={!!busy || !match}
          loading={busy === "generate"}
        >
          {busy === "generate" ? "Generating…" : "Generate documents"}
        </Button>
        <Button
          variant="destructive-outline"
          onClick={deleteJob}
          disabled={!!busy}
        >
          {busy === "delete" ? "Deleting…" : "Delete job"}
        </Button>
      </div>

      <ApplicationStatusTracker
        className="mb-6"
        value={resolveApplicationStatus(job)}
        updatedAt={job.applicationStatusAt}
        disabled={!!busy}
        onChange={setApplicationStatus}
      />

      {match ? (
        <>
          <section className="mt-7">
            <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="m-0 text-lg font-semibold">
                Match {match.score}/100
              </h2>
              <Badge
                variant={recommendationVariant(match.recommendation)}
                className="uppercase tracking-wide"
              >
                {match.recommendation}
              </Badge>
            </div>
            <p className="m-0 text-sm text-muted-foreground">
              Role family: {match.roleFamily}
              {match.whyViable ? ` · ${match.whyViable}` : ""}
            </p>
            {match.components ? (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {Object.entries(match.components).map(([key, value]) => (
                  <Badge
                    variant={componentPillVariant(key, value)}
                    key={key}
                  >
                    {key}: {value}
                  </Badge>
                ))}
              </div>
            ) : null}
          </section>

          <section className="mt-7">
            <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="m-0 text-lg font-semibold">Fit assessment</h2>
              <p className="m-0 text-sm text-muted-foreground">
                Change Strength / Warning / Gap — saved for Re-analyze
              </p>
            </div>
            <FitAssessmentTable
              match={match}
              busy={busy === "fit"}
              busyRequirement={fitBusyRequirement}
              onChangeFit={setFitOverride}
            />
          </section>
        </>
      ) : (
        <p className="py-8 text-muted-foreground">Not analyzed yet.</p>
      )}

      <section className="mt-7">
        <h2 className="mb-3 text-lg font-semibold">Description</h2>
        <Card>
          <CardPanel className="p-4">
            <MarkdownContent
              content={job.descriptionMarkdown || job.descriptionRaw}
            />
          </CardPanel>
        </Card>
      </section>

      {pkg ? <DocumentPackagePanel jobId={jobId} package={pkg} /> : null}
    </div>
  );
}
