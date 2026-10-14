"use client";

import { useCallback, useEffect, useState } from "react";
import { apiDelete, apiGet, apiPatch, apiPost } from "../../lib/api";
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

  async function discover() {
    if (busyId) return;
    setBusyId("discover");
    setError("");
    setInfo("");
    try {
      const result = await apiPost("/repositories/discover");
      const found = result?.suggested ?? 0;
      setInfo(
        found > 0
          ? `Found ${found} new ${found === 1 ? "repo" : "repos"} — review suggestions below.`
          : `No new repos found (checked ${result?.checked ?? 0}).`
      );
      await load();
    } catch (err) {
      setError(err.message || "Failed to discover repositories");
    } finally {
      setBusyId("");
    }
  }

  async function approveSuggestion(repo) {
    if (busyId) return;
    setBusyId(`approve:${repo._id}`);
    setError("");
    setInfo("");
    try {
      const updated = await apiPatch(`/repositories/${repo._id}`, {
        suggested: false,
        enabled: true,
      });
      setRepos((cur) =>
        cur.map((r) => (r._id === repo._id ? updated : r))
      );
      setInfo(`Approved ${repo.fullName}. It will be scanned on the next sync.`);
    } catch (err) {
      setError(err.message || "Failed to approve repository");
    } finally {
      setBusyId("");
    }
  }

  async function dismissSuggestion(repo) {
    if (busyId) return;
    setBusyId(`dismiss:${repo._id}`);
    setError("");
    setInfo("");
    try {
      const updated = await apiPatch(`/repositories/${repo._id}`, {
        dismissed: true,
      });
      setRepos((cur) =>
        cur.map((r) => (r._id === repo._id ? updated : r))
      );
      setInfo(`Dismissed ${repo.fullName}. It won't be suggested again.`);
    } catch (err) {
      setError(err.message || "Failed to dismiss repository");
    } finally {
      setBusyId("");
    }
  }

  async function removeRepo(repo) {
    if (busyId) return;
    if (
      typeof window !== "undefined" &&
      !window.confirm(
        `Remove ${repo.fullName}? This stops future scans and deletes its commit scan records. Evidence already added to your profile is kept.`
      )
    ) {
      return;
    }
    setBusyId(`remove:${repo._id}`);
    setError("");
    setInfo("");
    try {
      await apiDelete(`/repositories/${repo._id}`);
      setRepos((cur) => cur.filter((r) => r._id !== repo._id));
      setInfo(`Removed ${repo.fullName}.`);
    } catch (err) {
      setError(err.message || "Failed to remove repository");
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

  const suggestions = repos.filter((r) => r.suggested && !r.dismissed);
  const activeRepos = repos.filter((r) => !r.suggested);

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
            variant="outline"
            className="mt-5"
            onClick={discover}
            disabled={!!busyId || !githubEnabled}
          >
            Discover
          </Button>
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

      {!loading && suggestions.length > 0 ? (
        <section className="mb-8">
          <h2 className="mb-3 text-lg font-semibold">
            Suggested ({suggestions.length})
          </h2>
          <p className="mb-3 text-sm text-muted-foreground">
            Repos found on your GitHub account that aren&apos;t tracked yet.
            Approve to enable evidence scanning, or dismiss to hide forever.
          </p>
          <div className="grid gap-3">
            {suggestions.map((repo) => (
              <Card key={repo._id}>
                <CardPanel className="flex flex-wrap items-start justify-between gap-4 p-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="m-0 text-base font-semibold">
                        {repo.fullName}
                      </h3>
                      <Badge variant="outline">
                        {repo.defaultBranch || "main"}
                      </Badge>
                      <Badge>suggested</Badge>
                    </div>
                    <p className="mt-1 m-0 text-sm text-muted-foreground">
                      Discovered: {formatTs(repo.discoveredAt)}
                      {" · "}
                      <a
                        href={`https://github.com/${repo.fullName}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        github
                      </a>
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-3">
                    <Button
                      type="button"
                      size="sm"
                      disabled={!!busyId}
                      onClick={() => approveSuggestion(repo)}
                    >
                      Approve
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={!!busyId}
                      onClick={() => dismissSuggestion(repo)}
                    >
                      Dismiss
                    </Button>
                  </div>
                </CardPanel>
              </Card>
            ))}
          </div>
        </section>
      ) : null}

      {!loading && activeRepos.length === 0 ? (
        <p className="py-8 text-muted-foreground">
          No repositories yet. Run seed, add one above, or Discover.
        </p>
      ) : null}

      <div className="grid gap-3">
        {activeRepos.map((repo) => (
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
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={!!busyId}
                  onClick={() => removeRepo(repo)}
                >
                  Remove
                </Button>
              </div>
            </CardPanel>
          </Card>
        ))}
      </div>
    </div>
  );
}
