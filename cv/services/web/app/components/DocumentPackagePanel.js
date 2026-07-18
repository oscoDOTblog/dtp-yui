"use client";

import { useState } from "react";
import { getApiBase } from "../../lib/api";
import styles from "../ui.module.css";

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
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function downloadFromApi(jobId, filename) {
  const url = `${getApiBase()}/jobs/${jobId}/package/files/${encodeURIComponent(filename)}`;
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.target = "_blank";
  a.rel = "noreferrer";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function CollapsibleDoc({ title, filename, content, jobId, defaultOpen }) {
  const [open, setOpen] = useState(!!defaultOpen);
  const [copied, setCopied] = useState(false);

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
    <div className={styles.collapseItem}>
      <button
        type="button"
        className={styles.collapseHeader}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span>
          {open ? "▼" : "▶"} {title}
        </span>
        <span className={styles.meta}>{filename}</span>
      </button>
      {open ? (
        <div className={styles.collapseBody}>
          <div className={styles.collapseActions}>
            <button type="button" className={`${styles.btn} ${styles.btnSecondary}`} onClick={onCopy}>
              {copied ? "Copied!" : "Copy to clipboard"}
            </button>
            <button
              type="button"
              className={`${styles.btn} ${styles.btnSecondary}`}
              onClick={() => downloadTextFile(filename, content || "")}
            >
              Save .txt
            </button>
            {jobId && filename ? (
              <button
                type="button"
                className={`${styles.btn} ${styles.btnSecondary}`}
                onClick={() => downloadFromApi(jobId, filename)}
              >
                Download original
              </button>
            ) : null}
          </div>
          <pre className={styles.docPre}>{content || "(empty)"}</pre>
        </div>
      ) : null}
    </div>
  );
}

export default function DocumentPackagePanel({ jobId, package: pkg }) {
  if (!pkg?.previews) return null;

  const previewEntries = Object.values(pkg.previews);
  const downloads = pkg.downloads || [];

  return (
    <section className={styles.section}>
      <h2>Generated documents</h2>
      <p className={styles.meta}>
        Package <code>{pkg.folderName}</code>
        {pkg.generatedAt ? ` · ${pkg.generatedAt}` : ""} · also saved in this browser
      </p>

      <div className={styles.collapseList}>
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
        <div className={styles.actions} style={{ marginTop: "1rem" }}>
          {downloads.map((item) => (
            <button
              key={item.filename}
              type="button"
              className={`${styles.btn} ${styles.btnSecondary}`}
              onClick={() => downloadFromApi(jobId, item.filename)}
            >
              Download {item.label}
            </button>
          ))}
          <button
            type="button"
            className={styles.btn}
            onClick={() => {
              previewEntries.forEach((item) => {
                if (item.content) downloadTextFile(item.filename, item.content);
              });
            }}
          >
            Save all text to downloads
          </button>
        </div>
      ) : null}
    </section>
  );
}
