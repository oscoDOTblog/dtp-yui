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

/** Autofill policies for form questions. */
export const QUESTION_ACTION = {
  AUTOFILL: "AUTOFILL",
  AUTO_YES: "AUTO_YES",
  ASK_USER: "ASK_USER",
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

const TECH_YES_NO_PATTERNS = [
  /do you (have|know|possess|use).{0,40}(experience|skill|knowledge|familiar)/i,
  /experience with .{2,80}\?/i,
  /familiar with .{2,80}\?/i,
  /proficien(t|cy) (in|with)/i,
  /have you (used|worked with|built)/i,
  /\b(selenium|python|java|javascript|typescript|react|aws|docker|kubernetes|sql|jira|agile|ci\/?cd|testing|automation)\b/i,
];

export function isCoverLetterQuestion(questionText = "") {
  return /cover\s*letter/i.test(String(questionText || ""));
}

export function classifyQuestionRisk(questionText = "") {
  const q = String(questionText);
  for (const re of HIGH_RISK_PATTERNS) {
    if (re.test(q)) return RISK.LEGAL;
  }
  if (/salary|compensation|expect/i.test(q)) return RISK.MEDIUM;
  // Cover letter is autofilled from the generated package when available;
  // without a package it stays MEDIUM so Copilot Input can supply text.
  if (/why (are you|do you)/i.test(q)) return RISK.MEDIUM;
  if (isCoverLetterQuestion(q)) return RISK.MEDIUM;
  return RISK.LOW;
}

/**
 * True when the question is a tech/skill Yes-No we should auto-answer Yes.
 */
export function isTechYesNoQuestion(questionText = "", options = []) {
  const q = String(questionText);
  if (!q.trim()) return false;
  if (classifyQuestionRisk(q) === RISK.LEGAL) return false;
  if (/salary|compensation|sponsor|visa|authorized to work/i.test(q)) {
    return false;
  }

  const opts = (options || []).map((o) => String(o).trim().toLowerCase());
  const looksBinary =
    opts.length === 0 ||
    (opts.includes("yes") && opts.includes("no")) ||
    opts.every((o) => /^(yes|no)$/i.test(o));

  if (!looksBinary) return false;
  return TECH_YES_NO_PATTERNS.some((re) => re.test(q));
}

/**
 * Decide autofill policy for a collected form question.
 */
export function resolveQuestionAction(
  question = {},
  { knownContact = false, hasCoverLetter = false } = {}
) {
  if (knownContact) {
    return { action: QUESTION_ACTION.AUTOFILL, confidence: 0.95 };
  }
  if (hasCoverLetter && isCoverLetterQuestion(question.question)) {
    return { action: QUESTION_ACTION.AUTOFILL, confidence: 0.92 };
  }
  const risk = question.risk || classifyQuestionRisk(question.question);
  if (risk === RISK.LEGAL || risk === RISK.HIGH) {
    return { action: QUESTION_ACTION.ASK_USER, confidence: 0.15 };
  }
  if (
    isTechYesNoQuestion(question.question, question.options) &&
    (question.fieldType === "radio" ||
      question.fieldType === "radiogroup" ||
      question.fieldType === "checkbox" ||
      (question.options || []).some((o) => /^yes$/i.test(String(o))))
  ) {
    return { action: QUESTION_ACTION.AUTO_YES, confidence: 0.9 };
  }
  if (risk === RISK.MEDIUM) {
    return { action: QUESTION_ACTION.ASK_USER, confidence: 0.3 };
  }
  return { action: QUESTION_ACTION.ASK_USER, confidence: 0.4 };
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

/** Application statuses that mean we should not Easy Apply again. */
export const ALREADY_HANDLED_APPLICATION_STATUSES = new Set([
  "apply",
  "pending",
  "round1",
  "round2",
  "round3",
  "round4",
  "rejected",
]);

export function isAlreadyAppliedStatus(status) {
  if (!status) return false;
  return ALREADY_HANDLED_APPLICATION_STATUSES.has(
    String(status).trim().toLowerCase()
  );
}
