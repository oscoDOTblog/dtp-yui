"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPatch, apiPost } from "../../lib/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardPanel } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";

const ATS_OPTIONS = [
  {
    id: "greenhouse",
    label: "Greenhouse",
    tokenHint: "boards.greenhouse.io/{token}",
    locationHint: "Greenhouse location.name",
  },
  {
    id: "ashby",
    label: "Ashby",
    tokenHint: "jobs.ashbyhq.com/{slug}",
    locationHint: "Ashby location / secondaryLocations",
  },
];

function formatTs(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function atsMasterOn(atsIngest, ats) {
  if (!atsIngest || typeof atsIngest !== "object") return true;
  if (ats in atsIngest) return Boolean(atsIngest[ats]);
  return true;
}

export default function SourcesPage() {
  const [sources, setSources] = useState([]);
  const [atsIngest, setAtsIngest] = useState({
    greenhouse: true,
    ashby: true,
  });
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState("");
  const [ats, setAts] = useState("greenhouse");
  const [name, setName] = useState("");
  const [boardToken, setBoardToken] = useState("");
  const [priority, setPriority] = useState("50");
  const [locations, setLocations] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const [src, settings] = await Promise.all([
        apiGet("/sources"),
        apiGet("/settings"),
      ]);
      setSources(Array.isArray(src) ? src : []);
      setAtsIngest({
        greenhouse: Boolean(settings?.atsIngest?.greenhouse ?? true),
        ashby: Boolean(settings?.atsIngest?.ashby ?? true),
      });
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

  const selectedAts = ATS_OPTIONS.find((o) => o.id === ats) || ATS_OPTIONS[0];
  const greenhouseEnabled = atsMasterOn(atsIngest, "greenhouse");
  const ashbyEnabled = atsMasterOn(atsIngest, "ashby");
  const anyAtsEnabled = greenhouseEnabled || ashbyEnabled;

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

  async function pollAll(atsKey) {
    if (busyId) return;
    setBusyId(`poll:all:${atsKey}`);
    setError("");
    setInfo("");
    const label = atsKey === "ashby" ? "Ashby" : "Greenhouse";
    try {
      const result = await apiPost(`/ingest/run?sources=${atsKey}`);
      setInfo(
        result?.runId
          ? `${label} ingest started (${result.runId}).`
          : `${label} ingest started.`
      );
      setTimeout(load, 2500);
    } catch (err) {
      setError(err.message || `Failed to start ${label} poll`);
    } finally {
      setBusyId("");
    }
  }

  async function saveLocations(source, rawText) {
    if (busyId) return;
    setBusyId(`loc:${source._id}`);
    setError("");
    setInfo("");
    const next = String(rawText || "")
      .split(/[\n,]/)
      .map((s) => s.trim())
      .filter(Boolean);
    try {
      const updated = await apiPatch(`/sources/${source._id}`, {
        locations: next,
      });
      setSources((cur) =>
        cur.map((s) => (s._id === source._id ? updated : s)),
      );
      setInfo(
        next.length
          ? `Location prefs saved for ${source.name}.`
          : `Cleared location prefs for ${source.name} (Bay Area gate only).`,
      );
    } catch (err) {
      setError(err.message || "Failed to update locations");
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
      const locationList = locations
        .split(/[\n,]/)
        .map((s) => s.trim())
        .filter(Boolean);
      const created = await apiPost("/sources", {
        name: name.trim(),
        boardToken: boardToken.trim(),
        priority: Number(priority) || 50,
        locations: locationList,
        ats,
      });
      setSources((cur) => [created, ...cur]);
      setName("");
      setBoardToken("");
      setPriority("50");
      setLocations("");
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
            Greenhouse and Ashby company watchlists. Master on/off is in{" "}
            <a href="/settings">Settings</a>; per-company switches below.
            Optional location prefs filter boards before ingest (e.g.{" "}
            <code>San Francisco, Remote, Bay Area</code>).
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            onClick={() => pollAll("greenhouse")}
            disabled={!!busyId || !greenhouseEnabled}
          >
            Poll all Greenhouse
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => pollAll("ashby")}
            disabled={!!busyId || !ashbyEnabled}
          >
            Poll all Ashby
          </Button>
        </div>
      </div>

      {!anyAtsEnabled ? (
        <Alert variant="warning" className="mb-4">
          <AlertDescription>
            All ATS board ingest is disabled in{" "}
            <a href="/settings">Settings</a>. Enable Greenhouse and/or Ashby
            under ATS board ingest to poll boards.
          </AlertDescription>
        </Alert>
      ) : null}
      {anyAtsEnabled && !greenhouseEnabled ? (
        <Alert variant="warning" className="mb-4">
          <AlertDescription>
            Greenhouse ingest is disabled in{" "}
            <a href="/settings">Settings</a>. Ashby boards can still be polled.
          </AlertDescription>
        </Alert>
      ) : null}
      {anyAtsEnabled && !ashbyEnabled ? (
        <Alert variant="warning" className="mb-4">
          <AlertDescription>
            Ashby ingest is disabled in <a href="/settings">Settings</a>.
            Greenhouse boards can still be polled.
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
            <label className="grid min-w-[140px] gap-1 text-sm">
              <span className="text-muted-foreground">ATS</span>
              <select
                className="rounded-md border border-border bg-background px-3 py-2 text-foreground"
                value={ats}
                onChange={(e) => setAts(e.target.value)}
              >
                {ATS_OPTIONS.map((opt) => (
                  <option key={opt.id} value={opt.id}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid min-w-[140px] flex-1 gap-1 text-sm">
              <span className="text-muted-foreground">Name</span>
              <input
                className="rounded-md border border-border bg-background px-3 py-2 text-foreground"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                placeholder={ats === "ashby" ? "Ashby" : "Stripe"}
              />
            </label>
            <label className="grid min-w-[140px] flex-1 gap-1 text-sm">
              <span className="text-muted-foreground">
                {ats === "ashby" ? "Board slug" : "Board token"}
              </span>
              <input
                className="rounded-md border border-border bg-background px-3 py-2 text-foreground"
                value={boardToken}
                onChange={(e) => setBoardToken(e.target.value)}
                required
                placeholder={ats === "ashby" ? "ashby" : "stripe"}
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
            <label className="grid min-w-[200px] flex-[2] gap-1 text-sm">
              <span className="text-muted-foreground">
                Location prefs (optional)
              </span>
              <input
                className="rounded-md border border-border bg-background px-3 py-2 text-foreground"
                value={locations}
                onChange={(e) => setLocations(e.target.value)}
                placeholder="San Francisco, Remote, Bay Area"
              />
            </label>
            <Button type="submit" disabled={!!busyId}>
              Add
            </Button>
          </form>
          <p className="mt-2 m-0 text-xs text-muted-foreground">
            Token/slug is the public path from{" "}
            <code>{selectedAts.tokenHint}</code>. Location prefs are substring
            matches on {selectedAts.locationHint}; leave blank to use global
            Bay Area / role gates only.
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
        {sources.map((source) => {
          const sourceAts = (source.ats || "greenhouse").toLowerCase();
          const masterOn = atsMasterOn(atsIngest, sourceAts);
          return (
            <Card key={source._id}>
              <CardPanel className="flex flex-wrap items-start justify-between gap-4 p-4">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="m-0 text-base font-semibold">
                      {source.name}
                    </h2>
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
                    Last success: {formatTs(source.lastSuccessAt)} · Listed:{" "}
                    {source.lastListedCount ?? "—"} · Kept:{" "}
                    {source.lastPrefilteredCount ?? source.lastJobCount ?? "—"} ·
                    Fetched: {source.lastJobCount ?? "—"} · Priority:{" "}
                    {source.priority ?? 0}
                  </p>
                  <label className="mt-2 grid max-w-xl gap-1 text-sm">
                    <span className="text-muted-foreground">
                      Location prefs
                    </span>
                    <input
                      className="rounded-md border border-border bg-background px-3 py-2 text-foreground"
                      defaultValue={(source.locations || []).join(", ")}
                      key={`${source._id}:${(source.locations || []).join("|")}`}
                      disabled={busyId === `loc:${source._id}`}
                      placeholder="San Francisco, Remote, Bay Area"
                      onBlur={(e) => {
                        const next = e.target.value
                          .split(/[\n,]/)
                          .map((s) => s.trim())
                          .filter(Boolean);
                        const prev = source.locations || [];
                        const same =
                          next.length === prev.length &&
                          next.every((v, i) => v === prev[i]);
                        if (!same) saveLocations(source, e.target.value);
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          e.currentTarget.blur();
                        }
                      }}
                    />
                  </label>
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
                    disabled={!!busyId || !source.enabled || !masterOn}
                    onClick={() => pollOne(source)}
                  >
                    Poll
                  </Button>
                </div>
              </CardPanel>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
