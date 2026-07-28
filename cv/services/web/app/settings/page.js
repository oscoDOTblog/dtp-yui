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
  {
    key: "ashby",
    label: "Ashby",
    description:
      "Poll curated Ashby job boards from the Sources watchlist. Board slug is the last path segment of jobs.ashbyhq.com/{slug}.",
  },
];

const OLLAMA_THINK_PROCESSES = [
  {
    key: "jobExtract",
    label: "Job extract",
    description:
      "Structured JD extraction during analyze/ingest (JSON skills, seniority, role family).",
  },
  {
    key: "profileUpdate",
    label: "Profile update",
    description: "Free-text → profile merge on the Profile page.",
  },
  {
    key: "githubClassify",
    label: "GitHub classify",
    description: "Commit → skill evidence classification on repo sync.",
  },
  {
    key: "coverLetter",
    label: "Cover letter",
    description:
      "Application package cover-letter drafting — most likely place to want thinking on.",
  },
  {
    key: "resumeTailor",
    label: "Resume tailor",
    description:
      "Select and lightly rewrite approved achievements for each job package.",
  },
];

const DEFAULT_OLLAMA = {
  think: false,
  thinkByProcess: {
    jobExtract: false,
    profileUpdate: false,
    githubClassify: false,
    coverLetter: false,
    resumeTailor: false,
  },
};

const DEFAULT_RESUME = {
  renderEngine: "legacy",
  templateId: "classic",
  pages: 2,
};

const DEFAULT_INGEST_FILTERS = {
  dropOutOfArea: true,
  dropWrongRole: true,
  greenhouseTwoPhase: true,
};

export default function SettingsPage() {
  const [gmailIngest, setGmailIngest] = useState(null);
  const [atsIngest, setAtsIngest] = useState(null);
  const [githubEvidence, setGithubEvidence] = useState(null);
  const [ingestFilters, setIngestFilters] = useState(null);
  const [ollama, setOllama] = useState(null);
  const [resume, setResume] = useState(null);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const data = await apiGet("/settings");
      setGmailIngest(data.gmailIngest || {});
      setAtsIngest(data.atsIngest || { greenhouse: true, ashby: true });
      setGithubEvidence(
        data.githubEvidence || { enabled: true, defaultLookback: "7d" }
      );
      setIngestFilters(data.ingestFilters || DEFAULT_INGEST_FILTERS);
      setOllama(data.ollama || DEFAULT_OLLAMA);
      setResume(data.resume || DEFAULT_RESUME);
    } catch (err) {
      setError(err.message || "Failed to load settings");
      setGmailIngest(null);
      setAtsIngest(null);
      setGithubEvidence(null);
      setIngestFilters(null);
      setOllama(null);
      setResume(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function syncFromResponse(data, previousSlices) {
    if (data.gmailIngest) setGmailIngest(data.gmailIngest);
    else if (previousSlices?.gmail) setGmailIngest(previousSlices.gmail);
    if (data.atsIngest) setAtsIngest(data.atsIngest);
    else if (previousSlices?.ats) setAtsIngest(previousSlices.ats);
    if (data.githubEvidence) setGithubEvidence(data.githubEvidence);
    else if (previousSlices?.github) setGithubEvidence(previousSlices.github);
    if (data.ingestFilters) setIngestFilters(data.ingestFilters);
    else if (previousSlices?.ingestFilters)
      setIngestFilters(previousSlices.ingestFilters);
    if (data.ollama) setOllama(data.ollama);
    else if (previousSlices?.ollama) setOllama(previousSlices.ollama);
    if (data.resume) setResume(data.resume);
    else if (previousSlices?.resume) setResume(previousSlices.resume);
  }

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
      syncFromResponse(data, { gmail: { ...previous, [key]: nextValue } });
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
      syncFromResponse(data, { ats: { ...previous, [key]: nextValue } });
      setInfo("Saved. Next ingest run will use these toggles.");
    } catch (err) {
      setAtsIngest(previous);
      setError(err.message || "Failed to save settings");
    } finally {
      setSavingKey("");
    }
  }

  async function toggleIngestFilter(key) {
    if (!ingestFilters || savingKey) return;
    const nextValue = !ingestFilters[key];
    const previous = { ...ingestFilters };
    setIngestFilters({ ...ingestFilters, [key]: nextValue });
    setSavingKey(`filter:${key}`);
    setError("");
    setInfo("");
    try {
      const data = await apiPatch("/settings", {
        ingestFilters: { [key]: nextValue },
      });
      syncFromResponse(data, {
        ingestFilters: { ...previous, [key]: nextValue },
      });
      setInfo(
        "Saved. Next ingest drops gated listings before they reach Inbox.",
      );
    } catch (err) {
      setIngestFilters(previous);
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
      syncFromResponse(data, {
        github: { ...previous, [key]: nextValue },
      });
      setInfo("Saved. Cron and manual Sync respect this toggle.");
    } catch (err) {
      setGithubEvidence(previous);
      setError(err.message || "Failed to save settings");
    } finally {
      setSavingKey("");
    }
  }

  async function toggleOllamaThinkProcess(key) {
    if (!ollama || savingKey) return;
    const currentBy = ollama.thinkByProcess || {};
    const nextValue = !currentBy[key];
    const previous = {
      ...ollama,
      thinkByProcess: { ...(ollama.thinkByProcess || {}) },
    };
    const nextBy = { ...currentBy, [key]: nextValue };
    setOllama({
      ...ollama,
      thinkByProcess: nextBy,
      think: Object.values(nextBy).some(Boolean),
    });
    setSavingKey(`ollama:${key}`);
    setError("");
    setInfo("");
    try {
      const data = await apiPatch("/settings", {
        ollama: { thinkByProcess: { [key]: nextValue } },
      });
      syncFromResponse(data, {
        ollama: {
          ...previous,
          thinkByProcess: nextBy,
          think: Object.values(nextBy).some(Boolean),
        },
      });
      const label =
        OLLAMA_THINK_PROCESSES.find((p) => p.key === key)?.label || key;
      setInfo(
        nextValue
          ? `Saved. Thinking on for ${label}.`
          : `Saved. Thinking off for ${label}.`,
      );
    } catch (err) {
      setOllama(previous);
      setError(err.message || "Failed to save settings");
    } finally {
      setSavingKey("");
    }
  }

  async function toggleOllamaThinkAll() {
    if (!ollama || savingKey) return;
    const by = ollama.thinkByProcess || {};
    const anyOn = Object.values(by).some(Boolean);
    const nextValue = !anyOn;
    const previous = {
      ...ollama,
      thinkByProcess: { ...(ollama.thinkByProcess || {}) },
    };
    const nextBy = Object.fromEntries(
      OLLAMA_THINK_PROCESSES.map((p) => [p.key, nextValue]),
    );
    setOllama({ think: nextValue, thinkByProcess: nextBy });
    setSavingKey("ollama:think");
    setError("");
    setInfo("");
    try {
      const data = await apiPatch("/settings", {
        ollama: { think: nextValue },
      });
      syncFromResponse(data, {
        ollama: { think: nextValue, thinkByProcess: nextBy },
      });
      setInfo(
        nextValue
          ? "Saved. Thinking enabled for all Ollama processes."
          : "Saved. Thinking disabled for all Ollama processes.",
      );
    } catch (err) {
      setOllama(previous);
      setError(err.message || "Failed to save settings");
    } finally {
      setSavingKey("");
    }
  }

  async function setResumeEngine(engine) {
    if (!resume || savingKey) return;
    if (engine !== "legacy" && engine !== "rendercv") return;
    if (resume.renderEngine === engine) return;
    const previous = { ...resume };
    const next = { ...resume, renderEngine: engine };
    setResume(next);
    setSavingKey("resume:renderEngine");
    setError("");
    setInfo("");
    try {
      const data = await apiPatch("/settings", {
        resume: { renderEngine: engine },
      });
      syncFromResponse(data, { resume: next });
      setInfo(
        engine === "rendercv"
          ? "Saved. New packages use RenderCV for resume PDF (falls back to legacy on failure)."
          : "Saved. New packages use the legacy ReportLab resume PDF.",
      );
    } catch (err) {
      setResume(previous);
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
        <a href="/sources">Sources</a>). Ingest filters drop out-of-area and
        wrong-role listings before they are saved or analyzed. GitHub evidence
        is managed on <a href="/repositories">Repositories</a>. Ollama thinking
        can be set per process. Resume render engine chooses PDF typography.
        Changes apply on the next call — no restart.
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

      {!loading && ollama ? (
        <section className="mt-7">
          <h2 className="mb-3 text-lg font-semibold">Ollama thinking</h2>
          <p className="mb-3 m-0 text-sm text-muted-foreground">
            When on for a process, models like qwen3 spend tokens on internal
            reasoning before answering. Defaults are off for speed. Cover letter
            is the usual one to turn on.
          </p>
          <div className="grid gap-3">
            <Card>
              <CardPanel className="flex items-start gap-4 p-4">
                <Switch
                  className="mt-0.5 shrink-0"
                  checked={Boolean(
                    ollama.think ||
                      Object.values(ollama.thinkByProcess || {}).some(Boolean),
                  )}
                  disabled={!!savingKey}
                  onCheckedChange={toggleOllamaThinkAll}
                  aria-label="Ollama thinking for all processes"
                />
                <div className="min-w-0 flex-1">
                  <p className="m-0 font-semibold">All processes</p>
                  <p className="mt-1 m-0 text-sm text-muted-foreground">
                    Convenience toggle — sets every process below to the same
                    value.
                  </p>
                </div>
              </CardPanel>
            </Card>
            {OLLAMA_THINK_PROCESSES.map((p) => {
              const on = Boolean(ollama.thinkByProcess?.[p.key]);
              return (
                <Card key={p.key}>
                  <CardPanel className="flex items-start gap-4 p-4">
                    <Switch
                      className="mt-0.5 shrink-0"
                      checked={on}
                      disabled={!!savingKey}
                      onCheckedChange={() => toggleOllamaThinkProcess(p.key)}
                      aria-label={`${p.label} thinking ${on ? "on" : "off"}`}
                    />
                    <div className="min-w-0 flex-1">
                      <p className="m-0 font-semibold">{p.label}</p>
                      <p className="mt-1 m-0 text-sm text-muted-foreground">
                        {p.description}
                      </p>
                    </div>
                  </CardPanel>
                </Card>
              );
            })}
          </div>
        </section>
      ) : null}

      {!loading && resume ? (
        <section className="mt-10">
          <h2 className="mb-3 text-lg font-semibold">Resume render</h2>
          <p className="mb-3 m-0 text-sm text-muted-foreground">
            Packages always tailor achievements with grounded{" "}
            <code>sourceId</code> selection. Choose how the PDF is typeset.
            Default is legacy until RenderCV is validated in your Docker image.
          </p>
          <div className="grid gap-3">
            <Card>
              <CardPanel className="flex items-start gap-4 p-4">
                <Switch
                  className="mt-0.5 shrink-0"
                  checked={resume.renderEngine === "rendercv"}
                  disabled={!!savingKey}
                  onCheckedChange={(on) =>
                    setResumeEngine(on ? "rendercv" : "legacy")
                  }
                  aria-label={`RenderCV engine ${
                    resume.renderEngine === "rendercv" ? "on" : "off"
                  }`}
                />
                <div className="min-w-0 flex-1">
                  <p className="m-0 font-semibold">Use RenderCV for PDF</p>
                  <p className="mt-1 m-0 text-sm text-muted-foreground">
                    When on, resume PDF is built via RenderCV (
                    {resume.templateId || "classic"} theme). On failure the
                    package falls back to ReportLab. DOCX always uses the
                    structured tailor payload.
                  </p>
                </div>
              </CardPanel>
            </Card>
          </div>
        </section>
      ) : null}

      {!loading && ingestFilters ? (
        <section className="mt-10">
          <h2 className="mb-3 text-lg font-semibold">Inbox ingest filters</h2>
          <p className="mb-3 m-0 text-sm text-muted-foreground">
            After the Bay Area and role gates run on the listing text, drop
            mismatches before saving a job or running analyze. Defaults are on
            so Invalid noise stays out of Inbox.
          </p>
          <div className="grid gap-3">
            <Card>
              <CardPanel className="flex items-start gap-4 p-4">
                <Switch
                  className="mt-0.5 shrink-0"
                  checked={Boolean(ingestFilters.dropOutOfArea)}
                  disabled={!!savingKey}
                  onCheckedChange={() => toggleIngestFilter("dropOutOfArea")}
                  aria-label={`Drop out of area ${ingestFilters.dropOutOfArea ? "on" : "off"}`}
                />
                <div className="min-w-0 flex-1">
                  <p className="m-0 font-semibold">Drop out of area</p>
                  <p className="mt-1 m-0 text-sm text-muted-foreground">
                    Skip listings that fail the Bay Area / remote location gate.
                    They never appear in Inbox.
                  </p>
                </div>
              </CardPanel>
            </Card>
            <Card>
              <CardPanel className="flex items-start gap-4 p-4">
                <Switch
                  className="mt-0.5 shrink-0"
                  checked={Boolean(ingestFilters.dropWrongRole)}
                  disabled={!!savingKey}
                  onCheckedChange={() => toggleIngestFilter("dropWrongRole")}
                  aria-label={`Drop wrong role ${ingestFilters.dropWrongRole ? "on" : "off"}`}
                />
                <div className="min-w-0 flex-1">
                  <p className="m-0 font-semibold">Drop wrong role</p>
                  <p className="mt-1 m-0 text-sm text-muted-foreground">
                    Skip titles that fail the SWE / adjacent role filter. Turn
                    off if you want to review borderline roles in Invalid.
                  </p>
                </div>
              </CardPanel>
            </Card>
            <Card>
              <CardPanel className="flex items-start gap-4 p-4">
                <Switch
                  className="mt-0.5 shrink-0"
                  checked={Boolean(ingestFilters.greenhouseTwoPhase)}
                  disabled={!!savingKey}
                  onCheckedChange={() =>
                    toggleIngestFilter("greenhouseTwoPhase")
                  }
                  aria-label={`Greenhouse two-phase poll ${ingestFilters.greenhouseTwoPhase ? "on" : "off"}`}
                />
                <div className="min-w-0 flex-1">
                  <p className="m-0 font-semibold">
                    Greenhouse two-phase poll
                  </p>
                  <p className="mt-1 m-0 text-sm text-muted-foreground">
                    List board jobs without full JDs, drop out-of-area /
                    wrong-role on title+location, then fetch detail only for
                    keepers. Faster and quieter. Optional per-company location
                    prefs live on Sources.
                  </p>
                </div>
              </CardPanel>
            </Card>
          </div>
        </section>
      ) : null}

      {!loading && gmailIngest ? (
        <section className="mt-10">
          <h2 className="mb-3 text-lg font-semibold">Gmail alert ingest</h2>
          <div className="grid gap-3">
            <Card>
              <CardPanel className="flex items-start gap-4 p-4">
                <Switch
                  className="mt-0.5 shrink-0"
                  checked={Boolean(gmailIngest.enabled ?? true)}
                  disabled={!!savingKey}
                  onCheckedChange={() => toggleGmail("enabled")}
                  aria-label={`Gmail ingest ${gmailIngest.enabled ?? true ? "on" : "off"}`}
                />
                <div className="min-w-0 flex-1">
                  <p className="m-0 font-semibold">Gmail ingest</p>
                  <p className="mt-1 m-0 text-sm text-muted-foreground">
                    Master switch for JobAlerts via Gmail. When off, ingest
                    skips the Gmail API entirely (no OAuth / token refresh).
                    Greenhouse, Ashby, and Analyze still run.
                  </p>
                </div>
              </CardPanel>
            </Card>
            {PROVIDERS.map((p) => {
              const masterOn = Boolean(gmailIngest.enabled ?? true);
              const on = Boolean(gmailIngest[p.key]);
              return (
                <Card key={p.key}>
                  <CardPanel className="flex items-start gap-4 p-4">
                    <Switch
                      className="mt-0.5 shrink-0"
                      checked={on}
                      disabled={!!savingKey || !masterOn}
                      onCheckedChange={() => toggleGmail(p.key)}
                      aria-label={`${p.label} ingest ${on ? "on" : "off"}`}
                    />
                    <div className="min-w-0 flex-1">
                      <p className="m-0 font-semibold">{p.label}</p>
                      <p className="mt-1 m-0 text-sm text-muted-foreground">
                        {p.description}
                        {!masterOn
                          ? " Turn on Gmail ingest above to use this filter."
                          : ""}
                      </p>
                    </div>
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
                  <CardPanel className="flex items-start gap-4 p-4">
                    <Switch
                      className="mt-0.5 shrink-0"
                      checked={on}
                      disabled={!!savingKey}
                      onCheckedChange={() => toggleAts(p.key)}
                      aria-label={`${p.label} ingest ${on ? "on" : "off"}`}
                    />
                    <div className="min-w-0 flex-1">
                      <p className="m-0 font-semibold">{p.label}</p>
                      <p className="mt-1 m-0 text-sm text-muted-foreground">
                        {p.description}
                      </p>
                    </div>
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
              <CardPanel className="flex items-start gap-4 p-4">
                <Switch
                  className="mt-0.5 shrink-0"
                  checked={Boolean(githubEvidence.enabled)}
                  disabled={!!savingKey}
                  onCheckedChange={() => toggleGithub("enabled")}
                  aria-label={`GitHub evidence ${githubEvidence.enabled ? "on" : "off"}`}
                />
                <div className="min-w-0 flex-1">
                  <p className="m-0 font-semibold">Evidence engine</p>
                  <p className="mt-1 m-0 text-sm text-muted-foreground">
                    Poll configured repos at :30 UTC and on manual Sync.
                    Individual repos are managed on the{" "}
                    <a href="/repositories">Repositories</a> page.
                  </p>
                </div>
              </CardPanel>
            </Card>
            <Card>
              <CardPanel className="flex items-start gap-4 p-4">
                <Switch
                  className="mt-0.5 shrink-0"
                  checked={Boolean(githubEvidence.discoverRepos)}
                  disabled={!!savingKey || !githubEvidence.enabled}
                  onCheckedChange={() => toggleGithub("discoverRepos")}
                  aria-label={`Repo discovery ${githubEvidence.discoverRepos ? "on" : "off"}`}
                />
                <div className="min-w-0 flex-1">
                  <p className="m-0 font-semibold">Repo discovery</p>
                  <p className="mt-1 m-0 text-sm text-muted-foreground">
                    Scan your GitHub account for new or missing repos on each
                    sync. Finds are listed as suggestions on{" "}
                    <a href="/repositories">Repositories</a> for manual
                    approval — nothing is scanned until you approve it.
                  </p>
                </div>
              </CardPanel>
            </Card>
          </div>
        </section>
      ) : null}
    </div>
  );
}
