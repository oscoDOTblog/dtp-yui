"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiPost } from "../../lib/api";
import styles from "../ui.module.css";

const FETCH_STEPS = [
  "Fetching job page…",
  "Extracting listing text…",
];

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
  const [phase, setPhase] = useState(""); // fetch | analyze
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
      // Paste path already revealed
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

      // URL-only: try fetch first
      setPhase("fetch");
      setStatusText("Fetching job page…");
      const preview = await apiPost("/jobs/fetch-url", { url: url.trim() });

      if (!preview.ok || preview.blocked) {
        setNeedsPaste(true);
        setInfo(
          preview.reason ||
            "Could not read that page. Paste the full job description below."
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
            "Could not read that page. Paste the full job description below."
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
      <h1 className={styles.pageTitle}>Analyze a job</h1>
      <p className={styles.subtitle}>
        Start with a job URL. We’ll try to pull the posting from the page. If
        it’s blocked (common on LinkedIn), you can paste the description.
      </p>

      {error ? <div className={styles.error}>{error}</div> : null}
      {info ? <div className={styles.info}>{info}</div> : null}

      {busy ? (
        <div className={styles.statusPanel} role="status" aria-live="polite">
          <div className={styles.spinner} aria-hidden="true" />
          <div>
            <p className={styles.statusTitle}>
              {phase === "fetch" ? "Reading job page" : "Working on it"}
            </p>
            <p className={styles.statusText}>{statusText}</p>
            <div className={styles.statusDots}>
              {statusSteps.map((_, idx) => (
                <span
                  key={idx}
                  className={
                    idx <= statusIndex
                      ? `${styles.statusDot} ${styles.statusDotActive}`
                      : styles.statusDot
                  }
                />
              ))}
            </div>
          </div>
        </div>
      ) : null}

      <form className={styles.form} onSubmit={onSubmit}>
        <label className={styles.label}>
          Job URL
          <input
            className={styles.input}
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://..."
            required={!needsPaste}
            disabled={busy}
          />
        </label>

        {needsPaste ? (
          <label className={styles.label}>
            Job description
            <textarea
              className={styles.textarea}
              value={descriptionRaw}
              onChange={(e) => setDescriptionRaw(e.target.value)}
              placeholder="Paste the full job description here..."
              required
              disabled={busy}
              autoFocus
            />
          </label>
        ) : null}

        <div className={styles.actions}>
          <button className={styles.btn} type="submit" disabled={busy || (!url.trim() && !needsPaste)}>
            {busy
              ? phase === "fetch"
                ? "Fetching…"
                : "Analyzing…"
              : needsPaste
                ? "Analyze pasted description"
                : "Fetch & analyze"}
          </button>
          {!needsPaste ? (
            <button
              type="button"
              className={`${styles.btn} ${styles.btnSecondary}`}
              disabled={busy}
              onClick={() => {
                setNeedsPaste(true);
                setInfo("Paste the full job description below.");
              }}
            >
              Paste description instead
            </button>
          ) : (
            <button
              type="button"
              className={`${styles.btn} ${styles.btnSecondary}`}
              disabled={busy}
              onClick={() => {
                setNeedsPaste(false);
                setInfo("");
                setError("");
                setDescriptionRaw("");
              }}
            >
              Back to URL only
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
