"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPatch, apiPost } from "../../lib/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardPanel } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectItem,
  SelectPopup,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

const LOOKBACK_OPTIONS = [
  { value: "1d", label: "1 day" },
  { value: "7d", label: "1 week" },
  { value: "30d", label: "1 month" },
  { value: "90d", label: "3 months" },
  { value: "365d", label: "1 year" },
  { value: "all", label: "All time" },
];

function formatTs(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function shortSha(sha) {
  if (!sha) return "—";
  return String(sha).slice(0, 7);
}

export default function RepositoriesPage() {
  const [repos, setRepos] = useState([]);
  const [githubEnabled, setGithubEnabled] = useState(true);
  const [lookback, setLookback] = useState("7d");
  const [force, setForce] = useState(false);
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const [list, settings] = await Promise.all([
        apiGet("/repositories"),
        apiGet("/settings"),
      ]);
      setRepos(Array.isArray(list) ? list : []);
      setGithubEnabled(Boolean(settings?.githubEvidence?.enabled ?? true));
      if (settings?.githubEvidence?.defaultLookback) {
        setLookback(settings.githubEvidence.defaultLookback);
      }
    } catch (err) {
      setError(err.message || "Failed to load repositories");
      setRepos([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function toggleEnabled(repo) {
    if (busyId) return;
    setBusyId(repo._id);
    setError("");
    setInfo("");
    const previous = repos;
    setRepos(
      repos.map((r) =>
        r._id === repo._id ? { ...r, enabled: !r.enabled } : r
      )
    );
    try {
      const updated = await apiPatch(`/repositories/${repo._id}`, {
        enabled: !repo.enabled,
      });
      setRepos((cur) =>
        cur.map((r) => (r._id === repo._id ? updated : r))
      );
      setInfo("Saved.");
    } catch (err) {
      setRepos(previous);
      setError(err.message || "Failed to update repository");
    } finally {
      setBusyId("");
    }
  }

  async function syncOne(repo) {
    if (busyId) return;
    setBusyId(`sync:${repo._id}`);
    setError("");
    setInfo("");
    try {
      const result = await apiPost(`/repositories/${repo._id}/sync`, {
        lookback,
        force,
      });
      setInfo(
        result?.runId
          ? `Sync started (${result.runId}). Refresh in a minute for status.`
          : "Sync started."
      );
      setTimeout(load, 2500);
    } catch (err) {
      setError(err.message || "Failed to sync repository");
    } finally {
      setBusyId("");
    }
  }

  async function syncAll() {
    if (busyId) return;
    setBusyId("sync:all");
    setError("");
    setInfo("");
    try {
      const result = await apiPost("/repositories/sync", {
        lookback,
        force,
      });
      setInfo(
        result?.runId
          ? `GitHub sync started (${result.runId}, lookback ${lookback}).`
          : "GitHub sync started."
      );
      setTimeout(load, 2500);
    } catch (err) {
      setError(err.message || "Failed to start GitHub sync");
    } finally {
      setBusyId("");
    }
  }

  async function addRepo(e) {
    e.preventDefault();
    if (busyId) return;
    setBusyId("add");
    setError("");
    setInfo("");
    try {
      const created = await apiPost("/repositories", {
        fullName: fullName.trim(),
      });
      setRepos((cur) =>
        [...cur, created].sort((a, b) =>
          (a.fullName || "").localeCompare(b.fullName || "")
        )
      );
      setFullName("");
      setInfo(`Added ${created.fullName}.`);
    } catch (err) {
      setError(err.message || "Failed to add repository");
    } finally {
      setBusyId("");
    }
  }

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="m-0 mb-1.5 text-3xl font-semibold tracking-tight max-sm:text-2xl">
            Repositories
          </h1>
          <p className="m-0 text-muted-foreground">
            GitHub evidence scan. Master on/off is in{" "}
            <a href="/settings">Settings</a>; pick a lookback and Sync.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="grid gap-1 text-sm">
            <span className="text-muted-foreground">Lookback</span>
            <Select value={lookback} onValueChange={(v) => setLookback(v)}>
              <SelectTrigger className="min-w-36">
                <SelectValue placeholder="Lookback" />
              </SelectTrigger>
              <SelectPopup>
                {LOOKBACK_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectPopup>
            </Select>
          </label>
          <label className="mt-5 flex items-center gap-2 text-sm">
            <Checkbox
              checked={force}
              onCheckedChange={(v) => setForce(Boolean(v))}
              aria-label="Force re-scan already processed commits"
            />
            <span className="text-muted-foreground">Force</span>
          </label>
          <Button
            type="button"
            className="mt-5"
            onClick={syncAll}
            disabled={!!busyId || !githubEnabled}
          >
            Sync all
          </Button>
        </div>
      </div>

      {!githubEnabled ? (
        <Alert variant="warning" className="mb-4">
          <AlertDescription>
            GitHub evidence is disabled in{" "}
            <a href="/settings">Settings</a>. Enable it to sync repositories.
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
          <h2 className="m-0 mb-3 text-lg font-semibold">Add repository</h2>
          <form
            onSubmit={addRepo}
            className="flex flex-wrap items-end gap-3"
          >
            <label className="grid min-w-[220px] flex-1 gap-1 text-sm">
              <span className="text-muted-foreground">owner/repo</span>
              <input
                className="rounded-md border border-border bg-background px-3 py-2 text-foreground"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                required
                placeholder="oscoDOTblog/sway-f4"
              />
            </label>
            <Button type="submit" disabled={!!busyId}>
              Add
            </Button>
          </form>
          <p className="mt-2 m-0 text-xs text-muted-foreground">
            Requires a GitHub PAT in{" "}
            <code>secrets/github-token</code>. See GITHUB_SETUP.md.
          </p>
        </CardPanel>
      </Card>

      {loading ? (
        <p className="py-8 text-muted-foreground">Loading…</p>
      ) : null}

      {!loading && repos.length === 0 ? (
        <p className="py-8 text-muted-foreground">
          No repositories yet. Run seed or add one above.
        </p>
      ) : null}

      <div className="grid gap-3">
        {repos.map((repo) => (
          <Card key={repo._id}>
            <CardPanel className="flex flex-wrap items-start justify-between gap-4 p-4">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="m-0 text-base font-semibold">
                    {repo.fullName}
                  </h2>
                  <Badge variant="outline">{repo.defaultBranch || "main"}</Badge>
                  {repo.lastError ? (
                    <Badge variant="error">error</Badge>
                  ) : null}
                </div>
                <p className="mt-1 m-0 text-sm text-muted-foreground">
                  HEAD: <code>{shortSha(repo.lastSeenCommitSha)}</code>
                  {" · "}
                  <a
                    href={`https://github.com/${repo.fullName}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    github
                  </a>
                </p>
                <p className="m-0 text-sm text-muted-foreground">
                  Last success: {formatTs(repo.lastSuccessAt)} · Commits last
                  sync: {repo.lastCommitCount ?? "—"}
                </p>
                {repo.lastError ? (
                  <p className="m-0 text-sm text-destructive">
                    Last error: {repo.lastError}
                  </p>
                ) : null}
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <Switch
                  checked={Boolean(repo.enabled)}
                  disabled={!!busyId}
                  onCheckedChange={() => toggleEnabled(repo)}
                  aria-label={`${repo.fullName} ${repo.enabled ? "enabled" : "disabled"}`}
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={!!busyId || !repo.enabled || !githubEnabled}
                  onClick={() => syncOne(repo)}
                >
                  Sync
                </Button>
              </div>
            </CardPanel>
          </Card>
        ))}
      </div>
    </div>
  );
}
