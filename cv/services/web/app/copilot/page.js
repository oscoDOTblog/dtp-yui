"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardPanel, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { agentEventSource, agentGet, agentPost } from "../../lib/agentApi";
import BrowserPreview from "../components/BrowserPreview";

function formatTime(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return iso;
  }
}

function eventLine(ev) {
  if (ev.message) return ev.message;
  if (ev.type === "DECISION_MADE") {
    return `Decision: ${ev.decision}${ev.reason ? ` — ${ev.reason}` : ""}`;
  }
  if (ev.type === "STATE_CHANGED") return `State → ${ev.state}`;
  if (ev.type === "USER_INPUT_REQUIRED") return `Needs input: ${ev.question}`;
  if (ev.type === "ERROR") return `Error: ${ev.message || "unknown"}`;
  return ev.type || "event";
}

export default function CopilotPage() {
  const [status, setStatus] = useState(null);
  const [config, setConfig] = useState(null);
  const [events, setEvents] = useState([]);
  const [error, setError] = useState(null);
  const [answerDraft, setAnswerDraft] = useState("");
  const [reusePolicy, setReusePolicy] = useState("ONCE");
  const [starting, setStarting] = useState(false);
  const feedRef = useRef(null);

  const refreshStatus = useCallback(async () => {
    try {
      const s = await agentGet("/status");
      setStatus(s);
      setError(null);
    } catch (err) {
      setError(err.message || "Agent unreachable");
    }
  }, []);

  useEffect(() => {
    agentGet("/config")
      .then(setConfig)
      .catch(() => setConfig(null));
    refreshStatus();
    const poll = setInterval(refreshStatus, 3000);
    return () => clearInterval(poll);
  }, [refreshStatus]);

  useEffect(() => {
    let es;
    try {
      es = agentEventSource();
    } catch {
      return undefined;
    }
    if (!es) return undefined;
    es.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data);
        setEvents((prev) => [...prev.slice(-199), data]);
        if (data.type === "STATE_CHANGED" || data.type === "USER_INPUT_REQUIRED") {
          refreshStatus();
        }
      } catch {
        /* ignore */
      }
    };
    es.onerror = () => {
      /* EventSource reconnects automatically */
    };
    return () => es.close();
  }, [refreshStatus]);

  useEffect(() => {
    if (feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [events]);

  const pendingInputs = status?.pendingInputs || [];
  const activeInput = pendingInputs[0] || null;
  const currentJob = status?.currentJob;
  const reviewFromEvents = [...events]
    .reverse()
    .find((e) => e.kind === "SUBMISSION_APPROVAL" || e.reviewSummary);

  async function startRun() {
    setStarting(true);
    setError(null);
    try {
      await agentPost("/runs/start", {});
      setEvents([]);
      await refreshStatus();
    } catch (err) {
      setError(err.message);
    } finally {
      setStarting(false);
    }
  }

  async function control(path) {
    try {
      await agentPost(path, {});
      await refreshStatus();
    } catch (err) {
      setError(err.message);
    }
  }

  async function resolveInput(payload) {
    if (!activeInput?.requestId) return;
    try {
      await agentPost("/input/resolve", {
        requestId: activeInput.requestId,
        kind: activeInput.kind,
        ...payload,
      });
      setAnswerDraft("");
      await refreshStatus();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="m-0 mb-1.5 text-3xl font-semibold tracking-tight max-sm:text-2xl">
            Apply Copilot
          </h1>
          <p className="m-0 text-muted-foreground">
            Glassdoor-first Stage 6 runner — live browser preview below (Expand
            for fullscreen). Human approval required before submit.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            onClick={startRun}
            disabled={starting || status?.running}
            loading={starting}
          >
            Start Glassdoor run
          </Button>
        </div>
      </div>

      {error ? (
        <Alert variant="error">
          <AlertDescription>
            {error}
            <span className="mt-1 block text-xs opacity-80">
              Start the agent (`cd services/agent && CV_AGENT_HEADLESS=0 npm start`)
              or Compose service on :8010.
            </span>
          </AlertDescription>
        </Alert>
      ) : null}

      <div className="flex flex-wrap gap-2">
        <Badge variant="outline">state: {status?.state || "—"}</Badge>
        <Badge variant="outline">mode: {status?.uiMode || "—"}</Badge>
        <Badge variant={status?.running ? "default" : "secondary"}>
          {status?.running ? "running" : "idle"}
        </Badge>
        {status?.runId ? (
          <Badge variant="outline">run: {status.runId}</Badge>
        ) : null}
      </div>

      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="secondary"
          onClick={() => control("/control/pause")}
          disabled={!status?.running}
        >
          Pause
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => control("/control/resume")}
          disabled={!status?.running}
        >
          Resume
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => control("/control/take-control")}
          disabled={!status?.running}
        >
          Take control
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => control("/control/return-control")}
          disabled={!status?.running}
        >
          Return control
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => control("/control/skip")}
          disabled={!status?.running}
        >
          Skip job
        </Button>
        <Button
          size="sm"
          variant="destructive"
          onClick={() => control("/control/abort")}
          disabled={!status?.running}
        >
          Abort
        </Button>
      </div>

      <BrowserPreview
        active={Boolean(status?.running)}
        pageUrl={status?.pageUrl || status?.preview?.pageUrl || null}
        uiMode={status?.uiMode || null}
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Current job</CardTitle>
          </CardHeader>
          <CardPanel className="space-y-2 text-sm">
            {currentJob ? (
              <>
                <p className="m-0 text-base font-semibold">
                  {currentJob.title || "—"}
                </p>
                <p className="m-0 text-muted-foreground">
                  {currentJob.company || "—"}
                  {currentJob.location ? ` · ${currentJob.location}` : ""}
                </p>
                {currentJob.jobId ? (
                  <p className="m-0">
                    <a href={`/jobs/${currentJob.jobId}`}>Open in Inbox</a>
                  </p>
                ) : null}
                {currentJob.match?.score != null ||
                currentJob.match?.overallScore != null ? (
                  <p className="m-0">
                    Score:{" "}
                    {currentJob.match.score ?? currentJob.match.overallScore}
                    /100
                  </p>
                ) : null}
                {currentJob.sourceUrl ? (
                  <p className="m-0 break-all text-xs text-muted-foreground">
                    {currentJob.sourceUrl}
                  </p>
                ) : null}
              </>
            ) : (
              <p className="m-0 text-muted-foreground">
                No active listing. Start a run to open Glassdoor search results.
              </p>
            )}
            {config ? (
              <div className="mt-3 border-t border-border pt-3 text-xs text-muted-foreground">
                <p className="m-0">
                  Search: {config.query} @ {config.location}
                  {config.preferRemote ? " · prefer remote" : ""}
                </p>
                <p className="m-0">
                  Caps: {config.maxResultsPerRun} results /{" "}
                  {config.maxApplicationsPerRun} applies · min score{" "}
                  {config.minimumScore}
                </p>
                {(config.preferRemote
                  ? config.searchUrlRemote || config.searchUrl
                  : config.searchUrl || config.searchUrlRemote) ? (
                  <p className="m-0 break-all">
                    URL ({config.preferRemote ? "remote" : "local"}):{" "}
                    {config.preferRemote
                      ? config.searchUrlRemote || config.searchUrl
                      : config.searchUrl || config.searchUrlRemote}
                  </p>
                ) : null}
              </div>
            ) : null}
          </CardPanel>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Input queue</CardTitle>
          </CardHeader>
          <CardPanel className="space-y-3">
            {!activeInput ? (
              <p className="m-0 text-sm text-muted-foreground">
                No pending questions. When the agent pauses, prompts appear here.
              </p>
            ) : (
              <>
                <p className="m-0 text-sm font-medium">{activeInput.question}</p>
                {activeInput.riskLevel ? (
                  <Badge variant="outline">risk: {activeInput.riskLevel}</Badge>
                ) : null}
                {activeInput.kind === "SUBMISSION_APPROVAL" ||
                reviewFromEvents?.reviewSummary ? (
                  <div className="rounded-lg border border-border bg-muted/30 p-3 text-xs">
                    <pre className="m-0 whitespace-pre-wrap font-mono">
                      {JSON.stringify(
                        activeInput.reviewSummary ||
                          reviewFromEvents?.reviewSummary,
                        null,
                        2
                      )}
                    </pre>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        onClick={() =>
                          resolveInput({ action: "SUBMIT", value: "Submit" })
                        }
                      >
                        Approve submit
                      </Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() =>
                          resolveInput({ action: "SKIP", value: "Skip" })
                        }
                      >
                        Skip application
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {activeInput.options?.length ? (
                      <div className="flex flex-wrap gap-2">
                        {activeInput.options.map((opt) => (
                          <Button
                            key={opt}
                            size="sm"
                            variant="secondary"
                            onClick={() =>
                              resolveInput({
                                value: opt,
                                action: /skip/i.test(opt) ? "SKIP" : undefined,
                                reusePolicy,
                              })
                            }
                          >
                            {opt}
                          </Button>
                        ))}
                      </div>
                    ) : null}
                    <Textarea
                      value={answerDraft}
                      onChange={(e) => setAnswerDraft(e.target.value)}
                      placeholder="Type an answer…"
                      rows={3}
                    />
                    <div className="flex flex-wrap items-center gap-2">
                      <label className="text-xs text-muted-foreground">
                        Reuse
                        <select
                          className="ml-2 rounded-md border border-input bg-background px-2 py-1 text-sm"
                          value={reusePolicy}
                          onChange={(e) => setReusePolicy(e.target.value)}
                        >
                          <option value="ONCE">Use once</option>
                          <option value="WEBSITE">This website</option>
                          <option value="SIMILAR_ROLES">Similar roles</option>
                          <option value="ALWAYS">Always</option>
                        </select>
                      </label>
                      <Button
                        size="sm"
                        onClick={() =>
                          resolveInput({
                            value: answerDraft,
                            reusePolicy,
                          })
                        }
                        disabled={!answerDraft.trim()}
                      >
                        Send answer
                      </Button>
                    </div>
                  </div>
                )}
              </>
            )}
          </CardPanel>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Activity feed</CardTitle>
        </CardHeader>
        <CardPanel>
          <div
            ref={feedRef}
            className="max-h-[420px] overflow-y-auto rounded-lg border border-border bg-muted/20 p-3 font-mono text-xs leading-relaxed"
          >
            {events.length === 0 ? (
              <p className="m-0 text-muted-foreground">
                Waiting for agent events…
              </p>
            ) : (
              events.map((ev, idx) => (
                <div key={`${ev.sequence || idx}-${ev.createdAt || idx}`} className="mb-2">
                  <span className="text-muted-foreground">
                    {formatTime(ev.createdAt)}
                  </span>{" "}
                  <span className="text-primary">{ev.type}</span>{" "}
                  <span>{eventLine(ev)}</span>
                  {ev.evidence?.length ? (
                    <ul className="m-0 mt-1 list-disc pl-5 text-muted-foreground">
                      {ev.evidence.slice(0, 4).map((e, i) => (
                        <li key={i}>
                          {typeof e === "string"
                            ? e
                            : e.requirement || JSON.stringify(e)}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              ))
            )}
          </div>
        </CardPanel>
      </Card>
    </div>
  );
}
