/** Local-day helpers for application timeline / calendar / daily goals. */

const VIEW_MODE_KEY = "cv.applications.viewMode";

export function localDayKey(value = new Date()) {
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function todayLocalDayKey() {
  return localDayKey(new Date());
}

export function parseDayKey(dayKey) {
  if (!dayKey || typeof dayKey !== "string") return null;
  const match = dayKey.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]) - 1;
  const day = Number(match[3]);
  const d = new Date(year, month, day);
  if (
    d.getFullYear() !== year ||
    d.getMonth() !== month ||
    d.getDate() !== day
  ) {
    return null;
  }
  return d;
}

export function countToday(apps, dayKey = todayLocalDayKey()) {
  if (!Array.isArray(apps) || !dayKey) return 0;
  return apps.filter((app) => localDayKey(app.appliedAt) === dayKey).length;
}

/**
 * Group applications by local day key, newest first.
 * @returns {{ dayKey: string, apps: object[] }[]}
 */
export function groupByLocalDay(apps) {
  const map = new Map();
  for (const app of apps || []) {
    const key = localDayKey(app.appliedAt);
    if (!key) continue;
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(app);
  }
  const groups = Array.from(map.entries()).map(([dayKey, dayApps]) => ({
    dayKey,
    apps: dayApps.slice().sort((a, b) => {
      const ta = new Date(a.appliedAt).getTime() || 0;
      const tb = new Date(b.appliedAt).getTime() || 0;
      return tb - ta;
    }),
  }));
  groups.sort((a, b) => (a.dayKey < b.dayKey ? 1 : a.dayKey > b.dayKey ? -1 : 0));
  return groups;
}

/** Map dayKey -> count for calendar cells. */
export function dayCountMap(apps) {
  const map = new Map();
  for (const app of apps || []) {
    const key = localDayKey(app.appliedAt);
    if (!key) continue;
    map.set(key, (map.get(key) || 0) + 1);
  }
  return map;
}

export function formatDayHeading(dayKey) {
  const d = parseDayKey(dayKey);
  if (!d) return dayKey || "";
  const today = todayLocalDayKey();
  const yesterdayDate = new Date();
  yesterdayDate.setDate(yesterdayDate.getDate() - 1);
  const yesterday = localDayKey(yesterdayDate);
  if (dayKey === today) return "Today";
  if (dayKey === yesterday) return "Yesterday";
  return d.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: d.getFullYear() !== new Date().getFullYear() ? "numeric" : undefined,
  });
}

export function monthLabel(year, monthIndex) {
  const d = new Date(year, monthIndex, 1);
  return d.toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

/**
 * Build calendar cells for a month (includes leading/trailing days).
 * @returns {{ dayKey: string, day: number, inMonth: boolean, isToday: boolean }[]}
 */
export function buildMonthCells(year, monthIndex) {
  const first = new Date(year, monthIndex, 1);
  const startOffset = first.getDay(); // 0 = Sunday
  const daysInMonth = new Date(year, monthIndex + 1, 0).getDate();
  const prevMonthDays = new Date(year, monthIndex, 0).getDate();
  const todayKey = todayLocalDayKey();
  const cells = [];

  for (let i = 0; i < startOffset; i += 1) {
    const day = prevMonthDays - startOffset + i + 1;
    const d = new Date(year, monthIndex - 1, day);
    const dayKey = localDayKey(d);
    cells.push({
      dayKey,
      day,
      inMonth: false,
      isToday: dayKey === todayKey,
    });
  }

  for (let day = 1; day <= daysInMonth; day += 1) {
    const d = new Date(year, monthIndex, day);
    const dayKey = localDayKey(d);
    cells.push({
      dayKey,
      day,
      inMonth: true,
      isToday: dayKey === todayKey,
    });
  }

  while (cells.length % 7 !== 0) {
    const nextIndex = cells.length - startOffset - daysInMonth + 1;
    const d = new Date(year, monthIndex + 1, nextIndex);
    const dayKey = localDayKey(d);
    cells.push({
      dayKey,
      day: d.getDate(),
      inMonth: false,
      isToday: dayKey === todayKey,
    });
  }

  return cells;
}

export function loadViewMode() {
  if (typeof window === "undefined") return "timeline";
  try {
    const stored = window.localStorage.getItem(VIEW_MODE_KEY);
    if (stored === "calendar" || stored === "timeline") return stored;
  } catch {
    // ignore
  }
  return "timeline";
}

export function saveViewMode(mode) {
  if (typeof window === "undefined") return;
  if (mode !== "calendar" && mode !== "timeline") return;
  try {
    window.localStorage.setItem(VIEW_MODE_KEY, mode);
  } catch {
    // ignore
  }
}

export { VIEW_MODE_KEY };
