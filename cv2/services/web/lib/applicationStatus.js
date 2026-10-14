/** Application pipeline statuses for job tracking. */

export const APPLICATION_TRACK = [
  { id: "apply", label: "Apply", short: "Apply" },
  { id: "pending", label: "Pending", short: "Pending" },
  { id: "round1", label: "Round 1", short: "R1" },
  { id: "round2", label: "Round 2", short: "R2" },
  { id: "round3", label: "Round 3", short: "R3" },
  { id: "round4", label: "Round 4", short: "R4" },
];

export const APPLICATION_REJECTED = {
  id: "rejected",
  label: "Rejected",
  short: "Rejected",
};

export const APPLICATION_STATUSES = [
  ...APPLICATION_TRACK.map((s) => s.id),
  APPLICATION_REJECTED.id,
];

const LEGACY = {
  interested: "apply",
  saved: "pending",
  drafted: "apply",
  draft: "apply",
  save: "pending",
  reject: "rejected",
  interview: "round1",
};

export function normalizeApplicationStatus(raw) {
  if (raw == null || raw === "") return null;
  let value = String(raw).trim().toLowerCase().replace(/[\s_]+/g, "");
  if (LEGACY[value]) return LEGACY[value];
  if (APPLICATION_STATUSES.includes(value)) return value;
  const round = value.match(/^r(?:ound)?([1-4])$/);
  if (round) return `round${round[1]}`;
  return null;
}

export function resolveApplicationStatus(job) {
  if (!job) return null;
  return (
    normalizeApplicationStatus(job.applicationStatus) ||
    normalizeApplicationStatus(job.status)
  );
}

export function applicationStatusLabel(id) {
  const track = APPLICATION_TRACK.find((s) => s.id === id);
  if (track) return track.label;
  if (id === APPLICATION_REJECTED.id) return APPLICATION_REJECTED.label;
  return id || "";
}

export function trackIndex(id) {
  return APPLICATION_TRACK.findIndex((s) => s.id === id);
}
