const PLACEHOLDER_TITLES = new Set([
  "",
  "untitled",
  "untitled role",
  "unknown",
  "n/a",
  "na",
  "none",
]);

const PLACEHOLDER_COMPANIES = new Set([
  "",
  "unknown",
  "n/a",
  "na",
  "none",
  "untitled",
]);

export function isPlaceholderTitle(value) {
  return PLACEHOLDER_TITLES.has(String(value || "").trim().toLowerCase());
}

export function isPlaceholderCompany(value) {
  return PLACEHOLDER_COMPANIES.has(String(value || "").trim().toLowerCase());
}

export function jobTitleLabel(job) {
  const title = job?.title;
  if (!isPlaceholderTitle(title)) return String(title).trim();
  return "Title pending";
}

export function jobCompanyLabel(job) {
  const company = job?.company;
  if (!isPlaceholderCompany(company)) return String(company).trim();
  return "";
}

/** "Role — Company" without leaking Untitled/Unknown placeholders. */
export function jobHeadline(job) {
  const title = isPlaceholderTitle(job?.title)
    ? null
    : String(job.title).trim();
  const company = isPlaceholderCompany(job?.company)
    ? null
    : String(job.company).trim();
  if (title && company) return `${title} — ${company}`;
  if (title) return title;
  if (company) return company;
  return "Details still filling in";
}

/** Location · workMode · status — skip empty/unknown defaults. */
export function jobMetaLine(job) {
  const parts = [];
  const location = String(job?.location || "").trim();
  if (location && location.toLowerCase() !== "n/a") {
    parts.push(location);
  }
  const mode = String(job?.workMode || "").trim().toLowerCase();
  if (mode && mode !== "unknown") {
    parts.push(mode);
  }
  if (job?.status) {
    parts.push(`status: ${job.status}`);
  }
  if (!parts.length) {
    return job?.status === "analyzed" || job?.status === "new"
      ? "Location and work mode still filling in"
      : "";
  }
  return parts.join(" · ");
}
