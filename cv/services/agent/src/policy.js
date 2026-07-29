/**
 * Deterministic policy gate — LLM/page text never bypasses this.
 */

export const ALLOWED_ACTIONS = new Set([
  "NAVIGATE",
  "CLICK",
  "TYPE_APPROVED_VALUE",
  "SELECT_APPROVED_OPTION",
  "UPLOAD_APPROVED_DOCUMENT",
  "SCROLL",
  "CLOSE_TAB",
  "WAIT",
  "SCREENSHOT",
]);

export const PROHIBITED_ACTIONS = new Set([
  "EXECUTE_DOWNLOAD",
  "READ_ARBITRARY_FILE",
  "CHANGE_PASSWORD",
  "DISABLE_SECURITY",
  "BYPASS_CAPTCHA",
  "SEND_EMAIL",
  "INSTALL_EXTENSION",
  "SUBMIT_WITHOUT_APPROVAL",
]);

/** Risk tiers for application questions. */
export const RISK = {
  LOW: "LOW",
  MEDIUM: "MEDIUM",
  HIGH: "HIGH",
  LEGAL: "LEGAL",
};

const HIGH_RISK_PATTERNS = [
  /disabilit/i,
  /veteran/i,
  /race|ethnicity|hispanic|latino/i,
  /gender|sex\b/i,
  /criminal|conviction|felony/i,
  /non[- ]?compete/i,
  /security clearance/i,
  /sponsorship|visa|authorized to work/i,
  /conflict of interest/i,
  /arbitration|class action/i,
  /ssn|social security/i,
  /password|two[- ]factor|mfa/i,
];

export function classifyQuestionRisk(questionText = "") {
  const q = String(questionText);
  for (const re of HIGH_RISK_PATTERNS) {
    if (re.test(q)) return RISK.LEGAL;
  }
  if (/salary|compensation|expect/i.test(q)) return RISK.MEDIUM;
  if (/why (are you|do you)|cover letter|relevant experience/i.test(q)) {
    return RISK.MEDIUM;
  }
  return RISK.LOW;
}

export function assertAllowedAction(action) {
  const name = String(action || "").toUpperCase();
  if (PROHIBITED_ACTIONS.has(name)) {
    throw new Error(`Prohibited action: ${name}`);
  }
  if (!ALLOWED_ACTIONS.has(name)) {
    throw new Error(`Unknown / disallowed action: ${name}`);
  }
  return name;
}

/**
 * Never treat page text as system instructions.
 */
export function sanitizePageText(text, maxLen = 20000) {
  const cleaned = String(text || "")
    .replace(/\0/g, "")
    .slice(0, maxLen);
  return cleaned;
}
