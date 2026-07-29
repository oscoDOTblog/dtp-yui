"use client";

import { useState } from "react";
import { getApiBase } from "../../lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardPanel } from "@/components/ui/card";

function packageStorageKey(jobId) {
  return `cv-package-${jobId}`;
}

export function savePackageToBrowser(jobId, pkg) {
  if (typeof window === "undefined" || !pkg) return;
  try {
    const slim = {
      _id: pkg._id,
      jobId: pkg.jobId,
      folderName: pkg.folderName,
      generatedAt: pkg.generatedAt,
      previews: pkg.previews || {},
      downloads: pkg.downloads || [],
      files: pkg.files || [],
      renderer: pkg.renderer,
      selectionSummary: pkg.selectionSummary || null,
      tailorPayload: pkg.tailorPayload || null,
    };
    localStorage.setItem(packageStorageKey(jobId), JSON.stringify(slim));
  } catch {
    // quota / private mode — ignore
  }
}

export function loadPackageFromBrowser(jobId) {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(packageStorageKey(jobId));
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function clearPackageFromBrowser(jobId) {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem(packageStorageKey(jobId));
  } catch {
    // ignore
  }
}

function packageFileUrl(jobId, filename, { inline } = {}) {
  const params = new URLSearchParams();
  if (inline === true) params.set("inline", "true");
  if (inline === false) params.set("inline", "false");
  const qs = params.toString();
  return `${getApiBase()}/jobs/${jobId}/package/files/${encodeURIComponent(filename)}${
    qs ? `?${qs}` : ""
  }`;
}

function isPdf(filename) {
  return String(filename || "")
    .toLowerCase()
    .endsWith(".pdf");
}

/** Open in a new tab — PDFs use inline disposition for the browser viewer. */
function openFromApi(jobId, filename) {
  const url = packageFileUrl(jobId, filename, {
    inline: isPdf(filename) ? true : undefined,
  });
  window.open(url, "_blank", "noopener,noreferrer");
}

function downloadFromApi(jobId, filename) {
  const url = packageFileUrl(jobId, filename, { inline: false });
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noreferrer";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.style.position = "fixed";
  area.style.left = "-9999px";
  document.body.appendChild(area);
  area.select();
  document.execCommand("copy");
  document.body.removeChild(area);
}

function downloadTextFile(filename, content) {
  const blob = new Blob([content], { type: "text/plain; charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function CollapsibleDoc({ title, filename, content, jobId, defaultOpen }) {
  const [open, setOpen] = useState(!!defaultOpen);
  const [copied, setCopied] = useState(false);
  const pdfName =
    filename === "resume.txt"
      ? "resume.pdf"
      : filename === "cover-letter.txt"
        ? "cover-letter.pdf"
        : null;

  async function onCopy() {
    try {
      await copyText(content || "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  }

  return (
    <Card className="overflow-hidden">
      <button
        type="button"
        className="flex w-full cursor-pointer items-center justify-between gap-4 border-0 bg-transparent px-4 py-3.5 text-left font-semibold text-foreground hover:bg-accent/50"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span>
          {open ? "▼" : "▶"} {title}
        </span>
        <span className="text-sm font-normal text-muted-foreground">
          {filename}
        </span>
      </button>
      {open ? (
        <CardPanel className="border-t border-border pt-4">
          <div className="mb-3 flex flex-wrap gap-2">
            {jobId && pdfName ? (
              <Button
                type="button"
                onClick={() => openFromApi(jobId, pdfName)}
              >
                Open PDF
              </Button>
            ) : null}
            <Button type="button" variant="outline" onClick={onCopy}>
              {copied ? "Copied!" : "Copy to clipboard"}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => downloadTextFile(filename, content || "")}
            >
              Save .txt
            </Button>
            {jobId && filename ? (
              <Button
                type="button"
                variant="outline"
                onClick={() => downloadFromApi(jobId, filename)}
              >
                Download original
              </Button>
            ) : null}
          </div>
          <pre className="m-0 max-h-[420px] overflow-auto rounded-lg border border-border bg-background p-3.5 font-mono text-sm leading-relaxed break-words whitespace-pre-wrap text-foreground">
            {content || "(empty)"}
          </pre>
        </CardPanel>
      ) : null}
    </Card>
  );
}

export default function DocumentPackagePanel({ jobId, package: pkg }) {
  if (!pkg?.previews) return null;

  const previewEntries = Object.values(pkg.previews);
  const downloads = pkg.downloads || [];
  const selection = pkg.selectionSummary || pkg.tailorPayload || null;
  const files = pkg.files || [];
  const pdfQuickOpen = [
    files.includes("resume.pdf")
      ? { label: "Open resume PDF", filename: "resume.pdf" }
      : null,
    files.includes("cover-letter.pdf")
      ? { label: "Open cover letter PDF", filename: "cover-letter.pdf" }
      : null,
  ].filter(Boolean);

  return (
    <section className="mt-7">
      <h2 className="mb-3 text-lg font-semibold">Generated documents</h2>
      <p className="m-0 text-sm text-muted-foreground">
        Package <code>{pkg.folderName}</code>
        {pkg.generatedAt ? ` · ${pkg.generatedAt}` : ""} · also saved in this
        browser
      </p>

      {pdfQuickOpen.length > 0 ? (
        <div className="mt-3.5 flex flex-wrap gap-2.5">
          {pdfQuickOpen.map((item) => (
            <Button
              key={item.filename}
              type="button"
              onClick={() => openFromApi(jobId, item.filename)}
            >
              {item.label}
            </Button>
          ))}
        </div>
      ) : null}

      {selection ? (
        <Card className="mt-3.5">
          <CardPanel className="p-4">
            <p className="m-0 font-semibold">Resume selection</p>
            <p className="mt-1.5 m-0 text-sm text-muted-foreground">
              {selection.bulletCount ??
                selection.selectedAchievementIds?.length ??
                0}{" "}
              bullets
              {selection.renderer || pkg.renderer
                ? ` · renderer ${selection.renderer || pkg.renderer}`
                : ""}
              {selection.usedLlm === false
                ? " · deterministic fallback"
                : selection.usedLlm
                  ? " · Ollama tailor"
                  : ""}
            </p>
            {Array.isArray(selection.omittedRequirements) &&
            selection.omittedRequirements.length > 0 ? (
              <ul className="mt-2 mb-0 pl-5 text-sm text-muted-foreground">
                {selection.omittedRequirements.slice(0, 6).map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 mb-0 text-sm text-muted-foreground">
                No omitted JD requirements listed.
              </p>
            )}
            <div className="mt-3 flex flex-wrap gap-2">
              {pkg.files?.includes("selection-report.json") ? (
                <Button
                  type="button"
                  variant="outline"
                  onClick={() =>
                    downloadFromApi(jobId, "selection-report.json")
                  }
                >
                  Download selection report
                </Button>
              ) : null}
              {pkg.files?.includes("resume.yaml") ? (
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => downloadFromApi(jobId, "resume.yaml")}
                >
                  Download resume.yaml
                </Button>
              ) : null}
            </div>
          </CardPanel>
        </Card>
      ) : null}

      <div className="mt-3.5 grid gap-2.5">
        {previewEntries.map((item, idx) => (
          <CollapsibleDoc
            key={item.filename || item.title}
            title={item.title}
            filename={item.filename}
            content={item.content}
            jobId={jobId}
            defaultOpen={idx === 0}
          />
        ))}
      </div>

      {downloads.length > 0 ? (
        <div className="mt-4 flex flex-wrap gap-2.5">
          {downloads.map((item) => {
            const pdf = isPdf(item.filename);
            return (
              <Button
                key={item.filename}
                type="button"
                variant="outline"
                onClick={() =>
                  pdf
                    ? openFromApi(jobId, item.filename)
                    : downloadFromApi(jobId, item.filename)
                }
              >
                {pdf ? `Open ${item.label}` : `Download ${item.label}`}
              </Button>
            );
          })}
          <Button
            type="button"
            onClick={() => {
              previewEntries.forEach((item) => {
                if (item.content) downloadTextFile(item.filename, item.content);
              });
            }}
          >
            Save all text to downloads
          </Button>
        </div>
      ) : null}
    </section>
  );
}
