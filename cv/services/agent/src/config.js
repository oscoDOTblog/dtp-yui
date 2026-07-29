import fs from "fs/promises";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const DEFAULTS = {
  searchUrl: "",
  searchUrlRemote: "",
  preferRemote: false,
  query: "software engineer",
  location: "Oakland, CA",
  maxResultsPerRun: 10,
  maxApplicationsPerRun: 1,
  minimumScore: 72,
  maxRuntimeMinutes: 90,
  requireApprovalBeforeSubmit: true,
  slowMoMs: 100,
  humanDelayMs: { min: 800, max: 2200 },
};

/**
 * Resolve which Glassdoor results URL to open.
 * preferRemote → searchUrlRemote (fallback searchUrl);
 * otherwise searchUrl (fallback searchUrlRemote).
 */
export function resolveSearchUrl(cfg = {}) {
  const local = (cfg.searchUrl || "").trim();
  const remote = (cfg.searchUrlRemote || "").trim();
  if (cfg.preferRemote) {
    return remote || local || "";
  }
  return local || remote || "";
}

export function envConfig() {
  return {
    port: Number.parseInt(process.env.CV_AGENT_PORT || "8010", 10),
    apiBase: (process.env.CV_API_BASE || "http://127.0.0.1:8000").replace(
      /\/$/,
      ""
    ),
    headless: process.env.CV_AGENT_HEADLESS !== "0",
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
  return { ...DEFAULTS, ...file };
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
