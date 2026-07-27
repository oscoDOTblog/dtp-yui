"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { apiDelete, apiGet, apiPost } from "../../../lib/api";
import DocumentPackagePanel, {
  clearPackageFromBrowser,
  loadPackageFromBrowser,
  savePackageToBrowser,
} from "../../components/DocumentPackagePanel";
import MarkdownContent from "../../components/MarkdownContent";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardPanel } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { jobHeadline, jobMetaLine } from "../../../lib/jobDisplay";

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
  "Selecting grounded evidence…",
  "Drafting tailored resume…",
  "Writing cover letter with Ollama…",
  "Rendering PDF and DOCX files…",
  "Writing application answers…",
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
      } else {
        await apiPost(`/jobs/${jobId}/decision`, { decision: action });
        setMessage(`Decision recorded: ${action}`);
      }
      await load();
    } catch (err) {
      setError(err.message || "Action failed");
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
        <div>
          <h1 className="m-0 mb-1.5 text-3xl font-semibold tracking-tight max-sm:text-2xl">
            {jobHeadline(job)}
          </h1>
          <p className="m-0 text-muted-foreground">{jobMetaLine(job)}</p>
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
          variant="outline"
          onClick={() => run("apply")}
          disabled={!!busy}
        >
          Apply
        </Button>
        <Button
          variant="outline"
          onClick={() => run("save")}
          disabled={!!busy}
        >
          Save
        </Button>
        <Button
          variant="outline"
          onClick={() => run("reject")}
          disabled={!!busy}
        >
          Reject
        </Button>
        <Button
          variant="destructive-outline"
          onClick={deleteJob}
          disabled={!!busy}
        >
          {busy === "delete" ? "Deleting…" : "Delete job"}
        </Button>
      </div>

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
              <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm font-bold">
                <span className="text-success-foreground">Strength</span>
                <span className="text-warning-foreground">Warning</span>
                <span className="text-destructive-foreground">Gap</span>
              </div>
            </div>
            <div className="overflow-x-auto rounded-xl border border-border bg-card">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Area</TableHead>
                    <TableHead>Your fit</TableHead>
                    <TableHead>Notes</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(match.strongMatches || []).map((item, idx) => (
                    <TableRow key={`s-${idx}`}>
                      <TableCell>{item.requirement}</TableCell>
                      <TableCell className="font-bold text-success-foreground">
                        Strong
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {item.evidenceLevel || "verified evidence"}
                      </TableCell>
                    </TableRow>
                  ))}
                  {(match.warnings || []).map((item, idx) => (
                    <TableRow key={`w-${idx}`}>
                      <TableCell>{item.skill || item.requirement}</TableCell>
                      <TableCell className="font-bold text-warning-foreground">
                        {item.label || "Warning"}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {item.reason}
                      </TableCell>
                    </TableRow>
                  ))}
                  {(match.meaningfulGaps || []).map((item, idx) => (
                    <TableRow key={`g-${idx}`}>
                      <TableCell>{item.skill}</TableCell>
                      <TableCell className="font-bold text-destructive-foreground">
                        {item.label || "Gap"}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {item.reason}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
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
