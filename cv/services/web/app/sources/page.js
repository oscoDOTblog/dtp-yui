"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPatch, apiPost } from "../../lib/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardPanel } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";

function formatTs(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

export default function SourcesPage() {
  const [sources, setSources] = useState([]);
  const [greenhouseEnabled, setGreenhouseEnabled] = useState(true);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState("");
  const [name, setName] = useState("");
  const [boardToken, setBoardToken] = useState("");
  const [priority, setPriority] = useState("50");

  const load = useCallback(async () => {
    setError("");
    try {
      const [src, settings] = await Promise.all([
        apiGet("/sources"),
        apiGet("/settings"),
      ]);
      setSources(Array.isArray(src) ? src : []);
      setGreenhouseEnabled(Boolean(settings?.atsIngest?.greenhouse ?? true));
    } catch (err) {
      setError(err.message || "Failed to load sources");
      setSources([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function toggleEnabled(source) {
    if (busyId) return;
    setBusyId(source._id);
    setError("");
    setInfo("");
    const previous = sources;
    setSources(
      sources.map((s) =>
        s._id === source._id ? { ...s, enabled: !s.enabled } : s
      )
    );
    try {
      const updated = await apiPatch(`/sources/${source._id}`, {
        enabled: !source.enabled,
      });
      setSources((cur) =>
        cur.map((s) => (s._id === source._id ? updated : s))
      );
      setInfo("Saved.");
    } catch (err) {
      setSources(previous);
      setError(err.message || "Failed to update source");
    } finally {
      setBusyId("");
    }
  }

  async function pollOne(source) {
    if (busyId) return;
    setBusyId(`poll:${source._id}`);
    setError("");
    setInfo("");
    try {
      const result = await apiPost(`/sources/${source._id}/poll`);
      setInfo(
        result?.runId
          ? `Poll started (${result.runId}). Refresh in a minute for last-poll status.`
          : "Poll started."
      );
      setTimeout(load, 2500);
    } catch (err) {
      setError(err.message || "Failed to poll source");
    } finally {
      setBusyId("");
    }
  }

  async function pollAll() {
    if (busyId) return;
    setBusyId("poll:all");
    setError("");
    setInfo("");
    try {
      const result = await apiPost("/ingest/run?sources=greenhouse");
      setInfo(
        result?.runId
          ? `Greenhouse ingest started (${result.runId}).`
          : "Greenhouse ingest started."
      );
      setTimeout(load, 2500);
    } catch (err) {
      setError(err.message || "Failed to start Greenhouse poll");
    } finally {
      setBusyId("");
    }
  }

  async function addSource(e) {
    e.preventDefault();
    if (busyId) return;
    setBusyId("add");
    setError("");
    setInfo("");
    try {
      const created = await apiPost("/sources", {
        name: name.trim(),
        boardToken: boardToken.trim(),
        priority: Number(priority) || 50,
        ats: "greenhouse",
      });
      setSources((cur) => [created, ...cur]);
      setName("");
      setBoardToken("");
      setPriority("50");
      setInfo(`Added ${created.name}.`);
    } catch (err) {
      setError(err.message || "Failed to add source");
    } finally {
      setBusyId("");
    }
  }

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="m-0 mb-1.5 text-3xl font-semibold tracking-tight max-sm:text-2xl">
            Sources
          </h1>
          <p className="m-0 text-muted-foreground">
            Greenhouse company watchlist. Master on/off is in{" "}
            <a href="/settings">Settings</a>; per-company switches below.
          </p>
        </div>
        <Button
          type="button"
          onClick={pollAll}
          disabled={!!busyId || !greenhouseEnabled}
        >
          Poll all Greenhouse
        </Button>
      </div>

      {!greenhouseEnabled ? (
        <Alert variant="warning" className="mb-4">
          <AlertDescription>
            Greenhouse ingest is disabled in{" "}
            <a href="/settings">Settings</a>. Enable ATS board ingest to poll
            boards.
          </AlertDescription>
        </Alert>
      ) : null}

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

      <Card className="mb-8">
        <CardPanel className="p-4">
          <h2 className="m-0 mb-3 text-lg font-semibold">Add company</h2>
          <form
            onSubmit={addSource}
            className="flex flex-wrap items-end gap-3"
          >
            <label className="grid min-w-[140px] flex-1 gap-1 text-sm">
              <span className="text-muted-foreground">Name</span>
              <input
                className="rounded-md border border-border bg-background px-3 py-2 text-foreground"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                placeholder="Stripe"
              />
            </label>
            <label className="grid min-w-[140px] flex-1 gap-1 text-sm">
              <span className="text-muted-foreground">Board token</span>
              <input
                className="rounded-md border border-border bg-background px-3 py-2 text-foreground"
                value={boardToken}
                onChange={(e) => setBoardToken(e.target.value)}
                required
                placeholder="stripe"
              />
            </label>
            <label className="grid w-24 gap-1 text-sm">
              <span className="text-muted-foreground">Priority</span>
              <input
                className="rounded-md border border-border bg-background px-3 py-2 text-foreground"
                type="number"
                value={priority}
                onChange={(e) => setPriority(e.target.value)}
              />
            </label>
            <Button type="submit" disabled={!!busyId}>
              Add
            </Button>
          </form>
          <p className="mt-2 m-0 text-xs text-muted-foreground">
            Token is the public slug from{" "}
            <code>boards.greenhouse.io/&#123;token&#125;</code>.
          </p>
        </CardPanel>
      </Card>

      {loading ? (
        <p className="py-8 text-muted-foreground">Loading…</p>
      ) : null}

      {!loading && sources.length === 0 ? (
        <p className="py-8 text-muted-foreground">
          No sources yet. Run seed or add a company above.
        </p>
      ) : null}

      <div className="grid gap-3">
        {sources.map((source) => (
          <Card key={source._id}>
            <CardPanel className="flex flex-wrap items-start justify-between gap-4 p-4">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="m-0 text-base font-semibold">{source.name}</h2>
                  <Badge variant="outline">{source.ats}</Badge>
                  {source.lastError ? (
                    <Badge variant="error">error</Badge>
                  ) : null}
                </div>
                <p className="mt-1 m-0 text-sm text-muted-foreground">
                  Token: <code>{source.boardToken}</code>
                  {source.careersUrl ? (
                    <>
                      {" "}
                      ·{" "}
                      <a
                        href={source.careersUrl}
                        target="_blank"
                        rel="noreferrer"
                      >
                        careers
                      </a>
                    </>
                  ) : null}
                </p>
                <p className="m-0 text-sm text-muted-foreground">
                  Last success: {formatTs(source.lastSuccessAt)} · Jobs last
                  poll: {source.lastJobCount ?? "—"} · Priority:{" "}
                  {source.priority ?? 0}
                </p>
                {source.lastError ? (
                  <p className="m-0 text-sm text-destructive">
                    Last error: {source.lastError}
                  </p>
                ) : null}
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <Switch
                  checked={Boolean(source.enabled)}
                  disabled={!!busyId}
                  onCheckedChange={() => toggleEnabled(source)}
                  aria-label={`${source.name} ${source.enabled ? "enabled" : "disabled"}`}
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={
                    !!busyId || !source.enabled || !greenhouseEnabled
                  }
                  onClick={() => pollOne(source)}
                >
                  Poll
                </Button>
              </div>
            </CardPanel>
          </Card>
        ))}
      </div>
    </div>
  );
}
