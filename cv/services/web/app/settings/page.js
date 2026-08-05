"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPatch } from "../../lib/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardPanel } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Progress, ProgressLabel } from "@/components/ui/progress";
import {
  Select,
  SelectItem,
  SelectPopup,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
  {
    key: "remotive",
    label: "Remotive",
    description:
      "Poll Remotive’s public remote-jobs API (category software-dev). Public results are ~24 hours delayed — useful as a supplementary source, not for apply-immediately. Subject to Remotive API terms.",
  },
];

const DEFAULT_ATS_INGEST = {
  greenhouse: true,
  ashby: true,
  remotive: false,
};

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
  {
    key: "jobAnalyzer",
    label: "Job analyzer",
    description:
      "OpenAI multi-stage: extract ATS keywords and role priorities when package generation uses OpenAI.",
  },
  {
    key: "evidenceRanker",
    label: "Evidence ranker",
    description:
      "OpenAI multi-stage: score catalog achievements for the target role.",
  },
  {
    key: "resumeCritic",
    label: "Resume critic",
    description:
      "OpenAI multi-stage: score the draft resume and request one revision if needed.",
  },
  {
    key: "consistencyReview",
    label: "Consistency review",
    description:
      "OpenAI multi-stage: cross-check resume and cover letter for unsupported claims.",
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
    jobAnalyzer: false,
    evidenceRanker: false,
    resumeCritic: false,
    consistencyReview: false,
  },
};

const DEFAULT_RESUME = {
  renderEngine: "legacy",
  templateId: "classic",
  pages: 2,
};

const DEFAULT_DOCUMENT_PROVIDER = {
  provider: "ollama",
  model: "gpt-4o-mini",
  openaiConfigured: false,
  adminKeyConfigured: false,
  availableModels: [],
};

function formatTokens(value) {
  const n = Number(value) || 0;
  if (n >= 1_000_000) {
    const millions = n / 1_000_000;
    return `${millions >= 10 ? Math.round(millions) : millions.toFixed(1)}M`;
  }
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return String(n);
}

function usagePercent(used, limit) {
  if (!limit) return 0;
  return Math.min(100, (Number(used) || 0) / limit * 100);
}

const DEFAULT_INGEST_FILTERS = {
  dropOutOfArea: true,
  dropWrongRole: true,
  greenhouseTwoPhase: true,
};

const DEFAULT_DAILY_APPLICATIONS_TARGET = 10;

export default function SettingsPage() {
  const [gmailIngest, setGmailIngest] = useState(null);
  const [atsIngest, setAtsIngest] = useState(null);
  const [githubEvidence, setGithubEvidence] = useState(null);
  const [ingestFilters, setIngestFilters] = useState(null);
  const [ollama, setOllama] = useState(null);
  const [resume, setResume] = useState(null);
  const [documentProvider, setDocumentProvider] = useState(null);
  const [dailyApplicationsTarget, setDailyApplicationsTarget] = useState(
    DEFAULT_DAILY_APPLICATIONS_TARGET,
  );
  const [dailyTargetDraft, setDailyTargetDraft] = useState(
    String(DEFAULT_DAILY_APPLICATIONS_TARGET),
  );
  const [openaiUsage, setOpenaiUsage] = useState(null);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const data = await apiGet("/settings");
      setGmailIngest(data.gmailIngest || {});
      setAtsIngest(data.atsIngest || DEFAULT_ATS_INGEST);
      setGithubEvidence(
        data.githubEvidence || { enabled: true, defaultLookback: "7d" }
      );
      setIngestFilters(data.ingestFilters || DEFAULT_INGEST_FILTERS);
      setOllama(data.ollama || DEFAULT_OLLAMA);
      setResume(data.resume || DEFAULT_RESUME);
      setDocumentProvider(data.documentProvider || DEFAULT_DOCUMENT_PROVIDER);
      const target =
        Number(data.dailyApplicationsTarget) ||
        DEFAULT_DAILY_APPLICATIONS_TARGET;
      setDailyApplicationsTarget(target);
      setDailyTargetDraft(String(target));
    } catch (err) {
      setError(err.message || "Failed to load settings");
      setGmailIngest(null);
      setAtsIngest(null);
      setGithubEvidence(null);
      setIngestFilters(null);
      setOllama(null);
      setResume(null);
      setDocumentProvider(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadUsage = useCallback(async () => {
    try {
      setOpenaiUsage(await apiGet("/openai/usage"));
    } catch {
      // Usage is informational — never block the settings page on it
      setOpenaiUsage(null);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (documentProvider?.openaiConfigured) loadUsage();
  }, [documentProvider?.openaiConfigured, loadUsage]);

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
    if (data.documentProvider) setDocumentProvider(data.documentProvider);
    else if (previousSlices?.documentProvider)
      setDocumentProvider(previousSlices.documentProvider);
    if (data.dailyApplicationsTarget != null) {
      const target = Number(data.dailyApplicationsTarget);
      if (Number.isFinite(target) && target > 0) {
        setDailyApplicationsTarget(target);
        setDailyTargetDraft(String(target));
      }
    } else if (previousSlices?.dailyApplicationsTarget != null) {
      setDailyApplicationsTarget(previousSlices.dailyApplicationsTarget);
      setDailyTargetDraft(String(previousSlices.dailyApplicationsTarget));
    }
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

  async function setDocProvider(provider) {
    if (!documentProvider || savingKey) return;
    if (provider !== "ollama" && provider !== "openai") return;
    if (documentProvider.provider === provider) return;
    if (provider === "openai" && !documentProvider.openaiConfigured) return;
    const previous = { ...documentProvider };
    const next = { ...documentProvider, provider };
    setDocumentProvider(next);
    setSavingKey("documentProvider:provider");
    setError("");
    setInfo("");
    try {
      const data = await apiPatch("/settings", {
        documentProvider: { provider },
      });
      syncFromResponse(data, { documentProvider: next });
      setInfo(
        provider === "openai"
          ? "Saved. Cover letters and resume tailor use OpenAI (falls back to Ollama on failure)."
          : "Saved. Cover letters and resume tailor use local Ollama.",
      );
      loadUsage();
    } catch (err) {
      setDocumentProvider(previous);
      setError(err.message || "Failed to save settings");
    } finally {
      setSavingKey("");
    }
  }

  async function setDocModel(model) {
    if (!documentProvider || savingKey) return;
    if (!model || documentProvider.model === model) return;
    const previous = { ...documentProvider };
    const next = { ...documentProvider, model };
    setDocumentProvider(next);
    setSavingKey("documentProvider:model");
    setError("");
    setInfo("");
    try {
      const data = await apiPatch("/settings", {
        documentProvider: { model },
      });
      syncFromResponse(data, { documentProvider: next });
      setInfo(`Saved. New packages use ${model}.`);
      loadUsage();
    } catch (err) {
      setDocumentProvider(previous);
      setError(err.message || "Failed to save settings");
    } finally {
      setSavingKey("");
    }
  }

  async function saveDailyApplicationsTarget() {
    if (savingKey) return;
    const parsed = parseInt(dailyTargetDraft, 10);
    if (!Number.isFinite(parsed) || parsed < 1 || parsed > 100) {
      setError("Daily applications target must be an integer from 1 to 100.");
      setDailyTargetDraft(String(dailyApplicationsTarget));
      return;
    }
    if (parsed === dailyApplicationsTarget) return;
    const previous = dailyApplicationsTarget;
    setDailyApplicationsTarget(parsed);
    setSavingKey("dailyApplicationsTarget");
    setError("");
    setInfo("");
    try {
      const data = await apiPatch("/settings", {
        dailyApplicationsTarget: parsed,
      });
      syncFromResponse(data, { dailyApplicationsTarget: parsed });
      setInfo("Saved. Applications page goal uses this daily target.");
    } catch (err) {
      setDailyApplicationsTarget(previous);
      setDailyTargetDraft(String(previous));
      setError(err.message || "Failed to save settings");
    } finally {
      setSavingKey("");
    }
  }

  const availableModels = documentProvider?.availableModels || [];
  const modelOptions = availableModels.map((m) => ({
    value: m.id,
    label: `${m.label} · ${m.tier === "mini" ? "10M" : "1M"}/day`,
  }));
  const selectedModel = availableModels.find(
    (m) => m.id === documentProvider?.model,
  );

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
        is managed on <a href="/repositories">Repositories</a>. Document
        generation can use local Ollama or OpenAI for cover letters and resume
        tailor. Ollama thinking can be set per process. Resume render engine
        chooses PDF typography. Changes apply on the next call — no restart.
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

      {!loading && documentProvider ? (
        <section className="mt-7">
          <h2 className="mb-3 text-lg font-semibold">Applications</h2>
          <p className="mb-3 m-0 text-sm text-muted-foreground">
            Daily target for jobs marked{" "}
            <code className="text-[0.8em]">pending</code> (applied). Showed on
            the{" "}
            <a href="/applications">Applications</a> page as today&apos;s
            progress.
          </p>
          <Card>
            <CardPanel className="flex flex-wrap items-center gap-3 p-4">
              <div className="min-w-0 flex-1">
                <p className="m-0 font-semibold">Jobs applied per day</p>
                <p className="mt-1 m-0 text-sm text-muted-foreground">
                  Default is 10. Range 1–100.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Input
                  type="number"
                  min={1}
                  max={100}
                  step={1}
                  className="w-20"
                  value={dailyTargetDraft}
                  disabled={!!savingKey}
                  nativeInput
                  onChange={(e) => setDailyTargetDraft(e.target.value)}
                  onBlur={saveDailyApplicationsTarget}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.currentTarget.blur();
                    }
                  }}
                  aria-label="Daily applications target"
                />
              </div>
            </CardPanel>
          </Card>
        </section>
      ) : null}

      {!loading && documentProvider ? (
        <section className="mt-7">
          <h2 className="mb-3 text-lg font-semibold">Document generation</h2>
          <p className="mb-3 m-0 text-sm text-muted-foreground">
            When OpenAI is on, package generation runs a multi-stage pipeline
            (job analysis → evidence ranking → resume compose → critic → cover
            letter → consistency). Job extract, profile update, and GitHub
            classify stay on Ollama. OpenAI failures fall back to Ollama, then
            deterministic templates.
          </p>
          <div className="grid gap-3">
            <Card>
              <CardPanel className="flex items-start gap-4 p-4">
                <Switch
                  className="mt-0.5 shrink-0"
                  checked={documentProvider.provider === "openai"}
                  disabled={
                    !!savingKey || !documentProvider.openaiConfigured
                  }
                  onCheckedChange={(on) =>
                    setDocProvider(on ? "openai" : "ollama")
                  }
                  aria-label={`OpenAI multi-stage package generation ${
                    documentProvider.provider === "openai" ? "on" : "off"
                  }`}
                />
                <div className="min-w-0 flex-1">
                  <p className="m-0 font-semibold">
                    Use OpenAI multi-stage package generation
                  </p>
                  <p className="mt-1 m-0 text-sm text-muted-foreground">
                    {documentProvider.openaiConfigured ? (
                      <>
                        When on, packages use{" "}
                        <code>{documentProvider.model}</code> for the multi-stage
                        application pipeline (≈5–6 API calls). Ollama thinking
                        toggles below only apply when falling back to Ollama.
                      </>
                    ) : (
                      <>
                        Add an API key at{" "}
                        <code>secrets/openai-api-key</code> (or set{" "}
                        <code>OPENAI_API_KEY</code>), then restart the API
                        container. Until then this switch stays off and
                        packages use local Ollama (simple two-step path).
                      </>
                    )}
                  </p>
                </div>
              </CardPanel>
            </Card>

            {documentProvider.openaiConfigured ? (
              <Card>
                <CardPanel className="grid gap-3 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="m-0 font-semibold">Model</p>
                      <p className="mt-1 m-0 text-sm text-muted-foreground">
                        {selectedModel?.description ||
                          "Model used for both document calls."}{" "}
                        {selectedModel &&
                        selectedModel.supportsTemperature === false
                          ? "Reasoning model — temperature is not sent."
                          : null}
                      </p>
                    </div>
                    <Select
                      value={documentProvider.model}
                      onValueChange={setDocModel}
                      disabled={!!savingKey}
                      items={modelOptions}
                    >
                      <SelectTrigger
                        className="w-56 shrink-0"
                        aria-label="OpenAI model"
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectPopup>
                        {modelOptions.map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.label}
                          </SelectItem>
                        ))}
                      </SelectPopup>
                    </Select>
                  </div>

                  {openaiUsage ? (
                    <div className="grid gap-2 border-t border-border pt-3">
                      <Progress
                        value={usagePercent(
                          openaiUsage.usedTokens,
                          openaiUsage.limit,
                        )}
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <ProgressLabel>
                            Free daily tokens
                            <Badge variant="outline" className="ms-2">
                              {openaiUsage.tier === "mini"
                                ? "mini / nano tier"
                                : "standard tier"}
                            </Badge>
                          </ProgressLabel>
                          <span className="text-sm text-muted-foreground tabular-nums">
                            {formatTokens(openaiUsage.usedTokens)} /{" "}
                            {formatTokens(openaiUsage.limit)}
                          </span>
                        </div>
                      </Progress>
                      <p className="m-0 text-xs text-muted-foreground">
                        {openaiUsage.source === "org" ? (
                          <>
                            Org-wide usage across all traffic sharing this
                            allowance. This app spent{" "}
                            {formatTokens(openaiUsage.local.totalTokens)} today
                            over {openaiUsage.local.requests} calls.
                          </>
                        ) : (
                          <>
                            Counts only this app (
                            {formatTokens(openaiUsage.local.totalTokens)} over{" "}
                            {openaiUsage.local.requests} calls). For the real
                            shared total, add an admin key at{" "}
                            <code>secrets/openai-admin-key</code>.
                          </>
                        )}{" "}
                        Resets at UTC midnight.
                      </p>
                    </div>
                  ) : null}
                </CardPanel>
              </Card>
            ) : null}
          </div>
        </section>
      ) : null}

      {!loading && ollama ? (
        <section className="mt-10">
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
