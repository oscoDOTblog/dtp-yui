"use client";

import { useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  isPlaceholderTitle,
  jobCompanyLabel,
  jobHeadline,
} from "../../lib/jobDisplay";

const MAX_TITLE_LENGTH = 160;

function initialDraft(job) {
  return isPlaceholderTitle(job?.title) ? "" : String(job.title).trim();
}

/**
 * Headline with inline title editing. Titles parsed from alert emails and ATS
 * boards are often wrong, and the title feeds the role gate, match scoring, and
 * generated documents — so a hand correction is worth persisting.
 */
export default function JobTitleEditor({
  job,
  disabled = false,
  saving = false,
  onSave,
  onReset,
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(() => initialDraft(job));
  const inputRef = useRef(null);

  const isManual = job?.titleSource === "manual";
  const detectedTitle = String(job?.titleAuto || "").trim();
  const company = jobCompanyLabel(job);
  const trimmedDraft = draft.trim();

  useEffect(() => {
    if (!editing) setDraft(initialDraft(job));
  }, [editing, job?.title]);

  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  async function save() {
    if (!trimmedDraft || saving) return;
    if (trimmedDraft === initialDraft(job)) {
      setEditing(false);
      return;
    }
    const ok = await onSave?.(trimmedDraft);
    if (ok !== false) setEditing(false);
  }

  async function reset() {
    if (saving) return;
    const ok = await onReset?.();
    if (ok !== false) setEditing(false);
  }

  if (!editing) {
    return (
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2.5">
          <h1 className="m-0 text-3xl font-semibold tracking-tight max-sm:text-2xl">
            {jobHeadline(job)}
          </h1>
          {isManual ? <Badge variant="outline">Title edited</Badge> : null}
          <Button
            variant="ghost"
            size="sm"
            disabled={disabled}
            onClick={() => setEditing(true)}
          >
            Edit title
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-w-0 flex-1">
      <div className="flex flex-wrap items-center gap-2">
        <Input
          className="max-w-md"
          type="text"
          aria-label="Job title"
          ref={inputRef}
          value={draft}
          maxLength={MAX_TITLE_LENGTH}
          disabled={saving}
          placeholder="Senior Software Engineer"
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              save();
            } else if (event.key === "Escape") {
              event.preventDefault();
              setEditing(false);
            }
          }}
        />
        <Button onClick={save} disabled={!trimmedDraft || saving} loading={saving}>
          {saving ? "Saving…" : "Save"}
        </Button>
        <Button
          variant="outline"
          onClick={() => setEditing(false)}
          disabled={saving}
        >
          Cancel
        </Button>
        {isManual && detectedTitle ? (
          <Button
            variant="ghost"
            onClick={reset}
            disabled={saving}
            title={detectedTitle}
          >
            <span className="max-w-[18rem] truncate">
              Use detected: {detectedTitle}
            </span>
          </Button>
        ) : null}
      </div>
      <p className="mt-2 m-0 text-sm text-muted-foreground">
        {company ? `Company stays ${company}. ` : ""}
        Applies to the role gate, Re-analyze, and generated documents. Kept when
        this listing is polled again.
      </p>
    </div>
  );
}
