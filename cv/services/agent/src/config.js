import fs from "fs/promises";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export const APPLY_MODES = {
  EASY_APPLY_LOCAL: "easyApplyLocal",
  EASY_APPLY_REMOTE: "easyApplyRemote",
  COMPANY_APPLY_LOCAL: "companyApplyLocal",
  COMPANY_APPLY_REMOTE: "companyApplyRemote",
};

export const APPLY_MODE_META = {
  [APPLY_MODES.EASY_APPLY_LOCAL]: {
    id: APPLY_MODES.EASY_APPLY_LOCAL,
    label: "Easy Apply (Local)",
    shortLabel: "Easy Apply · Local",
    enabled: true,
    kind: "easyApply",
  },
  [APPLY_MODES.EASY_APPLY_REMOTE]: {
    id: APPLY_MODES.EASY_APPLY_REMOTE,
    label: "Easy Apply (Remote)",
    shortLabel: "Easy Apply · Remote",
    enabled: true,
    kind: "easyApply",
  },
  [APPLY_MODES.COMPANY_APPLY_LOCAL]: {
    id: APPLY_MODES.COMPANY_APPLY_LOCAL,
    label: "Company Apply (Local)",
    shortLabel: "Company Apply · Local",
    enabled: false,
    kind: "companyApply",
  },
  [APPLY_MODES.COMPANY_APPLY_REMOTE]: {
    id: APPLY_MODES.COMPANY_APPLY_REMOTE,
    label: "Company Apply (Remote)",
    shortLabel: "Company Apply · Remote",
    enabled: false,
    kind: "companyApply",
  },
};

const DEFAULT_SEARCH_URLS = {
  easyApplyLocal: "",
  easyApplyRemote: "",
  companyApplyLocal: "",
  companyApplyRemote: "",
};

const DEFAULTS = {
  applyMode: APPLY_MODES.EASY_APPLY_LOCAL,
  searchUrls: { ...DEFAULT_SEARCH_URLS },
  searchUrl: "",
  searchUrlRemote: "",
  preferRemote: false,
  query: "software engineer",
  location: "Oakland, CA",
  maxResultsPerRun: 10,
  maxApplicationsPerRun: 1,
  minimumScore: 60,
  maxRuntimeMinutes: 90,
  requireApprovalBeforeSubmit: true,
  slowMoMs: 100,
  humanDelayMs: { min: 800, max: 2200 },
};

export function isEasyApplyMode(mode) {
  return (
    mode === APPLY_MODES.EASY_APPLY_LOCAL ||
    mode === APPLY_MODES.EASY_APPLY_REMOTE
  );
}

export function isCompanyApplyMode(mode) {
  return (
    mode === APPLY_MODES.COMPANY_APPLY_LOCAL ||
    mode === APPLY_MODES.COMPANY_APPLY_REMOTE
  );
}

export function normalizeApplyMode(raw) {
  const mode = String(raw || "").trim();
  if (APPLY_MODE_META[mode]) return mode;
  return APPLY_MODES.EASY_APPLY_LOCAL;
}

/**
 * Resolve which Glassdoor results URL to open from applyMode + searchUrls.
 * Legacy fallback: preferRemote / searchUrl / searchUrlRemote.
 */
export function resolveSearchUrl(cfg = {}) {
  const mode = normalizeApplyMode(cfg.applyMode);
  const urls = { ...DEFAULT_SEARCH_URLS, ...(cfg.searchUrls || {}) };

  // Migrate legacy dual-URL fields into slots when slots empty.
  if (!urls.easyApplyLocal && cfg.searchUrl) {
    urls.easyApplyLocal = String(cfg.searchUrl).trim();
  }
  if (!urls.easyApplyRemote && cfg.searchUrlRemote) {
    urls.easyApplyRemote = String(cfg.searchUrlRemote).trim();
  }

  const fromMode = (urls[mode] || "").trim();
  if (fromMode) return fromMode;

  // Legacy preferRemote path when mode slots empty.
  const local = (cfg.searchUrl || urls.easyApplyLocal || "").trim();
  const remote = (cfg.searchUrlRemote || urls.easyApplyRemote || "").trim();
  if (cfg.preferRemote || mode === APPLY_MODES.EASY_APPLY_REMOTE) {
    return remote || local || "";
  }
  return local || remote || "";
}

/**
 * Load services/agent/.env into process.env without overriding existing vars
 * (so Docker Compose / shell exports still win).
 */
export async function loadDotEnv() {
  const envPath =
    process.env.CV_AGENT_ENV_FILE ||
    path.join(__dirname, "..", ".env");
  let raw;
  try {
    raw = await fs.readFile(envPath, "utf8");
  } catch {
    return { loaded: false, path: envPath };
  }
  for (const line of raw.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq <= 0) continue;
    const key = trimmed.slice(0, eq).trim();
    let value = trimmed.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    if (process.env[key] === undefined) {
      process.env[key] = value;
    }
  }
  return { loaded: true, path: envPath };
}

export function envConfig() {
  return {
    port: Number.parseInt(process.env.CV_AGENT_PORT || "8010", 10),
    apiBase: (process.env.CV_API_BASE || "http://127.0.0.1:8000").replace(
      /\/$/,
      ""
    ),
    headless: process.env.CV_AGENT_HEADLESS !== "0",
    preview: process.env.CV_AGENT_PREVIEW !== "0",
    previewMaxWidth: Number.parseInt(
      process.env.CV_AGENT_PREVIEW_MAX_WIDTH || "960",
      10
    ),
    profileDir:
      process.env.CV_AGENT_PROFILE_DIR ||
      path.join(__dirname, "..", "browser-profile"),
    screenshotDir:
      process.env.CV_AGENT_SCREENSHOT_DIR ||
      path.join(__dirname, "..", "screenshots"),
    configPath:
      process.env.CV_AGENT_CONFIG ||
      path.join(__dirname, "..", "..", "..", "config", "agent.json"),
  };
}

export async function loadAgentConfig() {
  const { configPath } = envConfig();
  let file = {};
  try {
    const raw = await fs.readFile(configPath, "utf8");
    file = JSON.parse(raw);
  } catch {
    try {
      const fallback = path.join(__dirname, "..", "config.example.json");
      const raw = await fs.readFile(fallback, "utf8");
      file = JSON.parse(raw);
    } catch {
      file = {};
    }
  }
  const merged = {
    ...DEFAULTS,
    ...file,
    searchUrls: {
      ...DEFAULT_SEARCH_URLS,
      ...(file.searchUrls || {}),
    },
  };
  merged.applyMode = normalizeApplyMode(merged.applyMode);
  return merged;
}

export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function humanDelay(cfg) {
  const min = cfg?.humanDelayMs?.min ?? 800;
  const max = cfg?.humanDelayMs?.max ?? 2200;
  const ms = min + Math.floor(Math.random() * Math.max(1, max - min));
  return sleep(ms);
}
