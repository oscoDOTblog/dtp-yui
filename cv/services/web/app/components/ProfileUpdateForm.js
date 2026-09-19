"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { apiPost } from "../../lib/api";
import LoadingGif from "./LoadingGif";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldLabel } from "@/components/ui/field";
import { Textarea } from "@/components/ui/textarea";

export default function ProfileUpdateForm() {
  const router = useRouter();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  async function onSubmit(event) {
    event.preventDefault();
    if (!text.trim() || busy) return;

    setBusy(true);
    setError("");
    setInfo("");
    try {
      const result = await apiPost("/candidate/update", { text: text.trim() });
      const fields = result.changedFields || [];
      const skills = result.skillsAdded || [];
      let msg = result.summaryOfChanges || "Profile updated.";
      if (fields.length) {
        msg += ` Updated: ${fields.join(", ")}.`;
      }
      if (skills.length) {
        msg += ` Skills added: ${skills.join(", ")}.`;
      }
      if (result.profileVersion) {
        msg += ` Profile version ${result.profileVersion}.`;
      }
      setInfo(msg);
      setText("");
      router.refresh();
    } catch (err) {
      setError(err.message || "Failed to update profile");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mb-8 max-w-3xl">
      <form className="grid gap-3.5" onSubmit={onSubmit}>
        <Field>
          <FieldLabel>Update profile</FieldLabel>
          <Textarea
            className="min-h-[140px]"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={
              "Paste new info — e.g. role preferences, salary floor, " +
              "location, positioning blurbs, new skills…"
            }
            disabled={busy}
          />
        </Field>
        <div className="flex flex-wrap items-center gap-2.5">
          <Button
            type="submit"
            disabled={busy || !text.trim()}
            loading={busy}
          >
            {busy ? "Updating…" : "Update profile"}
          </Button>
          <p className="m-0 text-sm text-muted-foreground">
            Ollama merges this into your seeded profile and bumps the version.
          </p>
        </div>
      </form>

      {error ? (
        <Alert variant="error" className="mt-4">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      {info && !busy ? (
        <Alert variant="info" className="mt-4">
          <AlertDescription>{info}</AlertDescription>
        </Alert>
      ) : null}

      {busy ? (
        <div
          className="mt-5 flex items-center gap-5 rounded-xl border border-primary/35 bg-primary/8 p-5 max-md:flex-col max-md:items-stretch"
          role="status"
          aria-live="polite"
        >
          <LoadingGif
            message="Updating profile"
            alt="Profile update loading animation"
          />
          <div className="min-w-0 flex-1">
            <p className="m-0 mb-1 font-semibold text-foreground">
              Applying profile update
            </p>
            <p className="m-0 text-sm text-muted-foreground">
              Extracting structured changes · merging into candidate · bumping
              profile version.
            </p>
          </div>
        </div>
      ) : null}
    </section>
  );
}
