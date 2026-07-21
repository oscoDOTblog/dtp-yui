"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPatch } from "../../lib/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card, CardPanel } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";

const PROVIDERS = [
  {
    key: "linkedinEmail",
    label: "LinkedIn",
    description: "Ingest LinkedIn Job Alerts digests from Gmail.",
  },
  {
    key: "indeedEmail",
    label: "Indeed",
    description: "Ingest Indeed job alert emails from Gmail.",
  },
  {
    key: "glassdoorEmail",
    label: "Glassdoor",
    description: "Ingest Glassdoor digest emails (per-listing cards).",
  },
  {
    key: "builtinEmail",
    label: "Built In",
    description: "Ingest Built In job alert emails from Gmail.",
  },
  {
    key: "otherEmail",
    label: "Other alerts",
    description:
      "Wellfound, Google Alerts, Dice, ZipRecruiter, and unrecognized senders.",
  },
];

const ATS_PROVIDERS = [
  {
    key: "greenhouse",
    label: "Greenhouse",
    description:
      "Poll curated company boards from the Sources watchlist. Individual companies are managed on the Sources page.",
  },
];

export default function SettingsPage() {
  const [gmailIngest, setGmailIngest] = useState(null);
  const [atsIngest, setAtsIngest] = useState(null);
  const [githubEvidence, setGithubEvidence] = useState(null);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const data = await apiGet("/settings");
      setGmailIngest(data.gmailIngest || {});
      setAtsIngest(data.atsIngest || { greenhouse: true });
      setGithubEvidence(
        data.githubEvidence || { enabled: true, defaultLookback: "7d" }
      );
    } catch (err) {
      setError(err.message || "Failed to load settings");
      setGmailIngest(null);
      setAtsIngest(null);
      setGithubEvidence(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function toggleGmail(key) {
    if (!gmailIngest || savingKey) return;
    const nextValue = !gmailIngest[key];
    const previous = { ...gmailIngest };
    setGmailIngest({ ...gmailIngest, [key]: nextValue });
    setSavingKey(`gmail:${key}`);
    setError("");
    setInfo("");
    try {
      const data = await apiPatch("/settings", {
        gmailIngest: { [key]: nextValue },
      });
      setGmailIngest(data.gmailIngest || { ...previous, [key]: nextValue });
      if (data.atsIngest) setAtsIngest(data.atsIngest);
      if (data.githubEvidence) setGithubEvidence(data.githubEvidence);
      setInfo("Saved. Next ingest run will use these toggles.");
    } catch (err) {
      setGmailIngest(previous);
      setError(err.message || "Failed to save settings");
    } finally {
      setSavingKey("");
    }
  }

  async function toggleAts(key) {
    if (!atsIngest || savingKey) return;
    const nextValue = !atsIngest[key];
    const previous = { ...atsIngest };
    setAtsIngest({ ...atsIngest, [key]: nextValue });
    setSavingKey(`ats:${key}`);
    setError("");
    setInfo("");
    try {
      const data = await apiPatch("/settings", {
        atsIngest: { [key]: nextValue },
      });
      setAtsIngest(data.atsIngest || { ...previous, [key]: nextValue });
      if (data.gmailIngest) setGmailIngest(data.gmailIngest);
      if (data.githubEvidence) setGithubEvidence(data.githubEvidence);
      setInfo("Saved. Next ingest run will use these toggles.");
    } catch (err) {
      setAtsIngest(previous);
      setError(err.message || "Failed to save settings");
    } finally {
      setSavingKey("");
    }
  }

  async function toggleGithub(key) {
    if (!githubEvidence || savingKey) return;
    const nextValue = !githubEvidence[key];
    const previous = { ...githubEvidence };
    setGithubEvidence({ ...githubEvidence, [key]: nextValue });
    setSavingKey(`github:${key}`);
    setError("");
    setInfo("");
    try {
      const data = await apiPatch("/settings", {
        githubEvidence: { [key]: nextValue },
      });
      setGithubEvidence(
        data.githubEvidence || { ...previous, [key]: nextValue }
      );
      if (data.gmailIngest) setGmailIngest(data.gmailIngest);
      if (data.atsIngest) setAtsIngest(data.atsIngest);
      setInfo("Saved. Cron and manual Sync respect this toggle.");
    } catch (err) {
      setGithubEvidence(previous);
      setError(err.message || "Failed to save settings");
    } finally {
      setSavingKey("");
    }
  }

  return (
    <div>
      <h1 className="m-0 mb-1.5 text-3xl font-semibold tracking-tight max-sm:text-2xl">
        Settings
      </h1>
      <p className="mb-6 text-muted-foreground">
        Control which intake sources run. Gmail switches decide which alert
        senders are processed after mail is fetched. ATS switches master-gate
        board polling (companies still managed on{" "}
        <a href="/sources">Sources</a>). GitHub evidence is managed on{" "}
        <a href="/repositories">Repositories</a>. Changes apply on the next
        run — no restart.
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

      {loading ? (
        <p className="py-8 text-muted-foreground">Loading…</p>
      ) : null}

      {!loading && gmailIngest ? (
        <section className="mt-7">
          <h2 className="mb-3 text-lg font-semibold">Gmail alert ingest</h2>
          <div className="grid gap-3">
            {PROVIDERS.map((p) => {
              const on = Boolean(gmailIngest[p.key]);
              return (
                <Card key={p.key}>
                  <CardPanel className="flex items-center justify-between gap-4 p-4">
                    <div className="min-w-0">
                      <p className="m-0 font-semibold">{p.label}</p>
                      <p className="mt-1 m-0 text-sm text-muted-foreground">
                        {p.description}
                      </p>
                    </div>
                    <Switch
                      checked={on}
                      disabled={!!savingKey}
                      onCheckedChange={() => toggleGmail(p.key)}
                      aria-label={`${p.label} ingest ${on ? "on" : "off"}`}
                    />
                  </CardPanel>
                </Card>
              );
            })}
          </div>
        </section>
      ) : null}

      {!loading && atsIngest ? (
        <section className="mt-10">
          <h2 className="mb-3 text-lg font-semibold">ATS board ingest</h2>
          <div className="grid gap-3">
            {ATS_PROVIDERS.map((p) => {
              const on = Boolean(atsIngest[p.key]);
              return (
                <Card key={p.key}>
                  <CardPanel className="flex items-center justify-between gap-4 p-4">
                    <div className="min-w-0">
                      <p className="m-0 font-semibold">{p.label}</p>
                      <p className="mt-1 m-0 text-sm text-muted-foreground">
                        {p.description}
                      </p>
                    </div>
                    <Switch
                      checked={on}
                      disabled={!!savingKey}
                      onCheckedChange={() => toggleAts(p.key)}
                      aria-label={`${p.label} ingest ${on ? "on" : "off"}`}
                    />
                  </CardPanel>
                </Card>
              );
            })}
          </div>
        </section>
      ) : null}

      {!loading && githubEvidence ? (
        <section className="mt-10">
          <h2 className="mb-3 text-lg font-semibold">GitHub evidence</h2>
          <div className="grid gap-3">
            <Card>
              <CardPanel className="flex items-center justify-between gap-4 p-4">
                <div className="min-w-0">
                  <p className="m-0 font-semibold">Evidence engine</p>
                  <p className="mt-1 m-0 text-sm text-muted-foreground">
                    Poll configured repos at :30 UTC and on manual Sync.
                    Individual repos are managed on the{" "}
                    <a href="/repositories">Repositories</a> page.
                  </p>
                </div>
                <Switch
                  checked={Boolean(githubEvidence.enabled)}
                  disabled={!!savingKey}
                  onCheckedChange={() => toggleGithub("enabled")}
                  aria-label={`GitHub evidence ${githubEvidence.enabled ? "on" : "off"}`}
                />
              </CardPanel>
            </Card>
            <Card>
              <CardPanel className="flex items-center justify-between gap-4 p-4">
                <div className="min-w-0">
                  <p className="m-0 font-semibold">Repo discovery</p>
                  <p className="mt-1 m-0 text-sm text-muted-foreground">
                    Scan your GitHub account for new or missing repos on each
                    sync. Finds are listed as suggestions on{" "}
                    <a href="/repositories">Repositories</a> for manual
                    approval — nothing is scanned until you approve it.
                  </p>
                </div>
                <Switch
                  checked={Boolean(githubEvidence.discoverRepos)}
                  disabled={!!savingKey || !githubEvidence.enabled}
                  onCheckedChange={() => toggleGithub("discoverRepos")}
                  aria-label={`Repo discovery ${githubEvidence.discoverRepos ? "on" : "off"}`}
                />
              </CardPanel>
            </Card>
          </div>
        </section>
      ) : null}
    </div>
  );
}
