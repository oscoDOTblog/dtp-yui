/**
 * Detect ATS type from URL / page title.
 */

export const AtsType = {
  GLASSDOOR: "GLASSDOOR",
  GREENHOUSE: "GREENHOUSE",
  LEVER: "LEVER",
  WORKDAY: "WORKDAY",
  ASHBY: "ASHBY",
  ICIMS: "ICIMS",
  SMARTRECRUITERS: "SMARTRECRUITERS",
  INDEED_SMARTAPPLY: "INDEED_SMARTAPPLY",
  CUSTOM: "CUSTOM",
  UNKNOWN: "UNKNOWN",
};

export function detectAts(url = "", title = "") {
  const u = String(url).toLowerCase();
  const t = String(title).toLowerCase();
  if (
    /smartapply\.indeed\.com/i.test(u) ||
    /indeed\.com\/.*(indeedapply|apply)/i.test(u) ||
    /indeed apply/i.test(t)
  ) {
    return AtsType.INDEED_SMARTAPPLY;
  }
  if (/boards\.greenhouse\.io|greenhouse\.io\/embed/i.test(u)) return AtsType.GREENHOUSE;
  if (/jobs\.lever\.co|lever\.co/i.test(u)) return AtsType.LEVER;
  if (/ashbyhq\.com/i.test(u)) return AtsType.ASHBY;
  if (/myworkdayjobs\.com|workday/i.test(u) || /workday/i.test(t)) return AtsType.WORKDAY;
  if (/smartrecruiters\.com/i.test(u)) return AtsType.SMARTRECRUITERS;
  if (/icims\.com/i.test(u)) return AtsType.ICIMS;
  if (/glassdoor\.com/i.test(u)) return AtsType.GLASSDOOR;
  return AtsType.UNKNOWN;
}
