"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiPost } from "../../lib/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

const FETCH_STEPS = ["Fetching job page…", "Extracting listing text…"];

const ANALYZE_STEPS = [
  "Saving job listing…",
  "Extracting requirements with Ollama…",
  "Matching against your evidence bank…",
  "Scoring gaps and recommendation…",
  "Almost done…",
];

export default function AnalyzePage() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [descriptionRaw, setDescriptionRaw] = useState("");
  const [needsPaste, setNeedsPaste] = useState(false);
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState("");
  const [statusIndex, setStatusIndex] = useState(0);
  const [statusText, setStatusText] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  const statusSteps = phase === "fetch" ? FETCH_STEPS : ANALYZE_STEPS;

  useEffect(() => {
    if (!busy) return undefined;
    setStatusIndex(0);
    setStatusText(statusSteps[0]);
    const id = setInterval(() => {
      setStatusIndex((prev) => {
        const next = Math.min(prev + 1, statusSteps.length - 1);
        setStatusText(statusSteps[next]);
        return next;
      });
    }, 1800);
    return () => clearInterval(id);
  }, [busy, phase]);

  async function analyzeWithDescription(jobUrl, description) {
    setPhase("analyze");
    setStatusText("Saving job listing…");
    const job = await apiPost("/jobs", {
      url: jobUrl || null,
      descriptionRaw: description || null,
    });
    setStatusText("Extracting requirements with Ollama…");
    await apiPost(`/jobs/${job._id}/analyze`);
    setStatusText("Opening match results…");
    router.push(`/jobs/${job._id}`);
  }

  async function onSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setInfo("");

    try {
      if (needsPaste) {
        if (!descriptionRaw.trim()) {
          throw new Error("Paste the full job description to continue.");
        }
        await analyzeWithDescription(url.trim(), descriptionRaw.trim());
        return;
      }

      if (!url.trim()) {
        throw new Error("Enter a job posting URL.");
      }

      setPhase("fetch");
      setStatusText("Fetching job page…");
      const preview = await apiPost("/jobs/fetch-url", { url: url.trim() });

      if (!preview.ok || preview.blocked) {
        setNeedsPaste(true);
        setInfo(
          preview.reason ||
            "Could not read that page. Paste the full job description below.",
        );
        if (preview.text) {
          setDescriptionRaw(preview.text);
        }
        setBusy(false);
        setStatusText("");
        setPhase("");
        return;
      }

      await analyzeWithDescription(url.trim(), preview.text);
    } catch (err) {
      const detail = err.detail;
      if (detail?.blocked || err.status === 422) {
        setNeedsPaste(true);
        setInfo(
          detail?.message ||
            err.message ||
            "Could not read that page. Paste the full job description below.",
        );
        setBusy(false);
        setStatusText("");
        setPhase("");
        return;
      }
      setError(err.message || "Analyze failed");
      setBusy(false);
      setStatusText("");
      setPhase("");
    }
  }

  return (
    <div>
      <h1 className="m-0 mb-1.5 text-3xl font-semibold tracking-tight max-sm:text-2xl">
        Analyze a job
      </h1>
      <p className="mb-6 text-muted-foreground">
        Start with a job URL. We’ll try to pull the posting from the page. If
        it’s blocked (common on LinkedIn), you can paste the description.
      </p>

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

      {busy ? (
        <div
          className="mb-5 flex max-w-xl items-start gap-4 rounded-xl border border-primary/35 bg-primary/8 p-4"
          role="status"
          aria-live="polite"
        >
          <Spinner className="mt-0.5 size-6 text-primary" />
          <div>
            <p className="m-0 mb-1 font-semibold">
              {phase === "fetch" ? "Reading job page" : "Working on it"}
            </p>
            <p className="m-0 min-h-[1.4em] text-sm text-foreground/90">
              {statusText}
            </p>
            <div className="mt-3 flex gap-1.5">
              {statusSteps.map((_, idx) => (
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
          </div>
        </div>
      ) : null}

      <form className="grid max-w-xl gap-3.5" onSubmit={onSubmit}>
        <Field>
          <FieldLabel>Job URL</FieldLabel>
          <Input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://..."
            required={!needsPaste}
            disabled={busy}
          />
        </Field>

        {needsPaste ? (
          <Field>
            <FieldLabel>Job description</FieldLabel>
            <Textarea
              className="min-h-[220px]"
              value={descriptionRaw}
              onChange={(e) => setDescriptionRaw(e.target.value)}
              placeholder="Paste the full job description here..."
              required
              disabled={busy}
              autoFocus
            />
          </Field>
        ) : null}

        <div className="mt-2 flex flex-wrap gap-2.5">
          <Button
            type="submit"
            disabled={busy || (!url.trim() && !needsPaste)}
            loading={busy}
          >
            {busy
              ? phase === "fetch"
                ? "Fetching…"
                : "Analyzing…"
              : needsPaste
                ? "Analyze pasted description"
                : "Fetch & analyze"}
          </Button>
          {!needsPaste ? (
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => {
                setNeedsPaste(true);
                setInfo("Paste the full job description below.");
              }}
            >
              Paste description instead
            </Button>
          ) : (
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => {
                setNeedsPaste(false);
                setInfo("");
                setError("");
                setDescriptionRaw("");
              }}
            >
              Back to URL only
            </Button>
          )}
        </div>
      </form>
    </div>
  );
}
