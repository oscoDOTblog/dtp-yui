import path from "path";
import {
  classifyQuestionRisk,
  isCoverLetterQuestion,
  resolveQuestionAction,
} from "../policy.js";
import { humanDelay } from "../config.js";

const COVER_LETTER_ADD_SELECTORS = [
  'button:has-text("Add a cover letter")',
  'a:has-text("Add a cover letter")',
  'button:has-text("Add cover letter")',
  'a:has-text("Add cover letter")',
  'button:has-text("Upload cover letter")',
  'a:has-text("Upload cover letter")',
];

const CONTACT_FIELD_MAP = [
  { keys: [/first.?name/i, /given.?name/i], profileKey: "firstName" },
  { keys: [/last.?name/i, /family.?name/i, /surname/i], profileKey: "lastName" },
  { keys: [/^name$/i, /full.?name/i], profileKey: "fullName" },
  { keys: [/e-?mail/i], profileKey: "email" },
  { keys: [/phone|mobile|tel/i], profileKey: "phone" },
  { keys: [/linkedin/i], profileKey: "linkedin" },
  { keys: [/github/i], profileKey: "github" },
  { keys: [/city|location|where do you live/i], profileKey: "location" },
];

export async function fillKnownContactFields(page, profile, events) {
  const results = [];
  const inputs = page.locator(
    'input[type="text"], input[type="email"], input[type="tel"], input:not([type]), textarea'
  );
  const count = await inputs.count();

  for (let i = 0; i < count; i += 1) {
    const input = inputs.nth(i);
    const meta = await input.evaluate((el) => ({
      type: el.type || "text",
      name: el.name || "",
      id: el.id || "",
      placeholder: el.placeholder || "",
      ariaLabel: el.getAttribute("aria-label") || "",
      labelText: (() => {
        const id = el.id;
        if (!id) return "";
        const lab = document.querySelector(`label[for="${CSS.escape(id)}"]`);
        return lab ? lab.textContent.trim() : "";
      })(),
    }));

    const hay = `${meta.labelText} ${meta.ariaLabel} ${meta.name} ${meta.placeholder} ${meta.id}`;
    let value = null;
    let matched = null;
    for (const rule of CONTACT_FIELD_MAP) {
      if (rule.keys.some((re) => re.test(hay))) {
        value = profile[rule.profileKey];
        matched = rule.profileKey;
        break;
      }
    }
    if (!value) continue;

    try {
      await input.fill(String(value));
      results.push({ field: matched, ok: true });
      await events.emit("ACTION_COMPLETED", {
        action: "TYPE_APPROVED_VALUE",
        target: matched,
        message: `Filled ${matched}`,
      });
    } catch (err) {
      results.push({ field: matched, ok: false, error: err.message });
    }
  }
  return results;
}

export async function uploadResume(page, resumePath, events) {
  if (!resumePath) throw new Error("No resume path provided");
  const fileInputs = page.locator('input[type="file"]');
  const count = await fileInputs.count();
  if (count === 0) {
    await events.emit("ACTION_COMPLETED", {
      action: "UPLOAD_APPROVED_DOCUMENT",
      message: "No file input found for resume",
    });
    return { uploaded: false };
  }
  await events.emit("ACTION_STARTED", {
    action: "UPLOAD_APPROVED_DOCUMENT",
    target: path.basename(resumePath),
    message: "Uploading resume",
  });
  await fileInputs.first().setInputFiles(resumePath);
  await events.emit("ACTION_COMPLETED", {
    action: "UPLOAD_APPROVED_DOCUMENT",
    message: `Uploaded ${path.basename(resumePath)}`,
  });
  return { uploaded: true };
}

/**
 * Detect whether the current page exposes a cover-letter field, upload, or Add CTA.
 */
export async function detectCoverLetterNeed(page) {
  const urlHint = /cover[-_]?letter|supporting[-_]?doc/i.test(page.url() || "");
  const scan = await page.evaluate(() => {
    const coverRe = /cover\s*letter/i;
    const resumeOnlyRe = /\b(resume|cv)\b/i;

    const fieldHay = (el) => {
      const id = el.id || "";
      let label = "";
      if (id) {
        const lab = document.querySelector(`label[for="${CSS.escape(id)}"]`);
        label = lab ? lab.textContent.trim() : "";
      }
      const wrap = el.closest(
        "label, fieldset, section, [class*='question'], [class*='document'], [data-testid]"
      );
      return [
        label,
        el.name || "",
        el.id || "",
        el.placeholder || "",
        el.getAttribute("aria-label") || "",
        el.accept || "",
        wrap ? wrap.textContent.trim().slice(0, 400) : "",
      ].join(" ");
    };

    let coverFileIndex = -1;
    const files = document.querySelectorAll('input[type="file"]');
    files.forEach((el, i) => {
      const hay = fieldHay(el);
      if (!coverRe.test(hay)) return;
      // Prefer explicit cover letter over a generic resume+cover combo input
      if (coverFileIndex < 0 || !resumeOnlyRe.test(hay.replace(coverRe, ""))) {
        coverFileIndex = i;
      }
    });

    let coverTextareaIndex = -1;
    document.querySelectorAll("textarea").forEach((el, i) => {
      if (coverRe.test(fieldHay(el))) coverTextareaIndex = i;
    });

    let hasAddCta = false;
    for (const el of document.querySelectorAll("a, button, [role='button']")) {
      const t = (el.textContent || "").replace(/\s+/g, " ").trim();
      if (/add (a )?cover letter|upload cover letter|attach cover letter/i.test(t)) {
        hasAddCta = true;
        break;
      }
      // Supporting documents row: "No cover letter…" + Add
      if (/^add$/i.test(t)) {
        const block = (el.closest("section, li, tr, div")?.textContent || "").slice(
          0,
          500
        );
        if (coverRe.test(block) || /supporting\s*documents?/i.test(block)) {
          hasAddCta = true;
          break;
        }
      }
    }

    const body = (document.body?.innerText || "").slice(0, 6000);
    const required =
      /cover\s*letter.{0,60}(required|\*)/i.test(body) ||
      [...document.querySelectorAll("[required], [aria-required='true']")].some(
        (el) => coverRe.test(fieldHay(el))
      );

    const needed =
      coverFileIndex >= 0 ||
      coverTextareaIndex >= 0 ||
      hasAddCta ||
      required;

    return {
      needed,
      coverFileIndex,
      coverTextareaIndex,
      hasAddCta,
      required,
    };
  });

  return { ...scan, needed: Boolean(scan.needed || urlHint), urlHint };
}

async function clickCoverLetterAddCta(page) {
  for (const sel of COVER_LETTER_ADD_SELECTORS) {
    const loc = page.locator(sel).first();
    if ((await loc.count()) > 0) {
      await loc.click({ timeout: 4000 }).catch(() => {});
      return true;
    }
  }
  // Supporting-documents row: Add near "cover letter" / "No cover letter"
  const candidates = page.locator("a, button, [role='button']");
  const count = await candidates.count();
  for (let i = 0; i < Math.min(count, 40); i += 1) {
    const el = candidates.nth(i);
    const meta = await el
      .evaluate((node) => {
        const t = (node.textContent || "").replace(/\s+/g, " ").trim();
        const block = (
          node.closest("section, li, tr, article, div")?.textContent || ""
        )
          .replace(/\s+/g, " ")
          .trim()
          .slice(0, 400);
        return { t, block };
      })
      .catch(() => null);
    if (!meta) continue;
    if (/add (a )?cover letter|upload cover letter/i.test(meta.t)) {
      await el.click({ timeout: 4000 }).catch(() => {});
      return true;
    }
    if (
      /^add$/i.test(meta.t) &&
      (/cover\s*letter/i.test(meta.block) ||
        /supporting\s*documents?/i.test(meta.block))
    ) {
      await el.click({ timeout: 4000 }).catch(() => {});
      return true;
    }
  }
  return false;
}

/**
 * When the page asks for a cover letter, upload PDF/DOCX or paste generated text.
 * Uses artifacts from generate-package (OpenAI or Ollama per Settings documentProvider).
 */
export async function attachCoverLetterIfNeeded(page, coverLetter, events, cfg) {
  const text = String(coverLetter?.text || "").trim();
  const filePath = coverLetter?.pdfPath || coverLetter?.docxPath || null;
  if (!text && !filePath) {
    return { attached: false, reason: "no_cover_letter_artifact" };
  }

  let need = await detectCoverLetterNeed(page);
  if (!need.needed) {
    return { attached: false, reason: "not_requested" };
  }

  await events.emit("ACTION_STARTED", {
    action: "UPLOAD_APPROVED_DOCUMENT",
    message: "Cover letter requested — attaching generated letter",
  });

  if (need.hasAddCta) {
    const clicked = await clickCoverLetterAddCta(page);
    if (clicked) {
      await humanDelay(cfg);
      need = await detectCoverLetterNeed(page);
    }
  }

  if (filePath && need.coverFileIndex >= 0) {
    const inputs = page.locator('input[type="file"]');
    await inputs.nth(need.coverFileIndex).setInputFiles(filePath);
    await events.emit("ACTION_COMPLETED", {
      action: "UPLOAD_APPROVED_DOCUMENT",
      message: `Uploaded cover letter ${path.basename(filePath)}`,
    });
    await events.emit("DECISION_MADE", {
      decision: "AUTOFILL",
      reason: "generated_cover_letter",
      message: "Attached generated cover letter file",
      confidence: 0.92,
    });
    return { attached: true, method: "upload", path: filePath };
  }

  // After Add CTA, a new file input may appear without cover-specific labeling
  if (filePath && need.hasAddCta) {
    const inputs = page.locator('input[type="file"]');
    const count = await inputs.count();
    if (count > 0) {
      // Prefer the last file input (often the newly revealed cover upload)
      await inputs.nth(count - 1).setInputFiles(filePath);
      await events.emit("ACTION_COMPLETED", {
        action: "UPLOAD_APPROVED_DOCUMENT",
        message: `Uploaded cover letter ${path.basename(filePath)}`,
      });
      await events.emit("DECISION_MADE", {
        decision: "AUTOFILL",
        reason: "generated_cover_letter",
        message: "Attached generated cover letter file",
        confidence: 0.9,
      });
      return { attached: true, method: "upload", path: filePath };
    }
  }

  if (text && need.coverTextareaIndex >= 0) {
    await page.locator("textarea").nth(need.coverTextareaIndex).fill(text);
    await events.emit("ACTION_COMPLETED", {
      action: "TYPE_APPROVED_VALUE",
      message: "Filled cover letter textarea from generated package",
    });
    await events.emit("DECISION_MADE", {
      decision: "AUTOFILL",
      reason: "generated_cover_letter",
      message: "Pasted generated cover letter",
      confidence: 0.92,
    });
    return { attached: true, method: "textarea" };
  }

  // Fallback: any empty textarea whose label mentions cover letter (re-scan)
  if (text) {
    const filled = await page.evaluate((letter) => {
      const coverRe = /cover\s*letter/i;
      for (const el of document.querySelectorAll("textarea")) {
        const id = el.id;
        let label = "";
        if (id) {
          const lab = document.querySelector(`label[for="${CSS.escape(id)}"]`);
          label = lab ? lab.textContent.trim() : "";
        }
        const hay = [
          label,
          el.name || "",
          el.placeholder || "",
          el.getAttribute("aria-label") || "",
        ].join(" ");
        if (!coverRe.test(hay)) continue;
        if (el.value && el.value.trim().length > 40) continue;
        el.focus();
        el.value = letter;
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
      }
      return false;
    }, text);
    if (filled) {
      await events.emit("ACTION_COMPLETED", {
        action: "TYPE_APPROVED_VALUE",
        message: "Filled cover letter textarea from generated package",
      });
      await events.emit("DECISION_MADE", {
        decision: "AUTOFILL",
        reason: "generated_cover_letter",
        message: "Pasted generated cover letter",
        confidence: 0.9,
      });
      return { attached: true, method: "textarea" };
    }
  }

  await events.emit("ACTION_COMPLETED", {
    action: "UPLOAD_APPROVED_DOCUMENT",
    message: "Cover letter UI detected but could not attach automatically",
  });
  return { attached: false, reason: "attach_failed" };
}

/**
 * Scan form questions that look unknown / high-risk.
 */
export async function collectUnknownQuestions(page, { hasCoverLetter = false } = {}) {
  const unknowns = await page.evaluate(() => {
    const out = [];
    const seen = new Set();
    const fields = document.querySelectorAll(
      "input, select, textarea, [role='radiogroup']"
    );
    for (const el of fields) {
      if (el.type === "hidden" || el.type === "file" || el.type === "submit") continue;
      // Dedupe radio groups by name
      if (el.type === "radio") {
        const key = `radio:${el.name || el.id}`;
        if (seen.has(key)) continue;
        seen.add(key);
      }
      const id = el.id;
      let label = "";
      if (id) {
        const lab = document.querySelector(`label[for="${CSS.escape(id)}"]`);
        label = lab ? lab.textContent.trim() : "";
      }
      if (!label) {
        const wrap = el.closest("label, .field, .form-group, [class*='question'], fieldset, [role='radiogroup']");
        label = wrap ? wrap.textContent.trim().slice(0, 240) : "";
      }
      if (!label) {
        label =
          el.getAttribute("aria-label") ||
          el.getAttribute("placeholder") ||
          el.getAttribute("name") ||
          "";
      }
      const options = [];
      let fieldType =
        el.tagName.toLowerCase() === "select" ? "select" : el.type || "text";
      if (el.tagName === "SELECT") {
        for (const opt of el.options) options.push(opt.textContent.trim());
      }
      if (el.type === "radio" || el.getAttribute("role") === "radiogroup") {
        fieldType = "radiogroup";
        const name = el.name;
        const radios = name
          ? document.querySelectorAll(`input[type="radio"][name="${CSS.escape(name)}"]`)
          : el.querySelectorAll?.('input[type="radio"]') || [];
        for (const r of radios) {
          const rid = r.id;
          let l = "";
          if (rid) {
            const lab = document.querySelector(`label[for="${CSS.escape(rid)}"]`);
            l = lab ? lab.textContent.trim() : "";
          }
          if (!l) l = r.value || "";
          if (l) options.push(l);
        }
      }
      out.push({
        question: label.slice(0, 300),
        fieldType,
        name: el.name || el.id || "",
        options,
      });
    }
    return out;
  });

  return unknowns.map((q) => {
    const risk = classifyQuestionRisk(q.question);
    const knownContact =
      /first.?name|last.?name|e-?mail|phone|linkedin|github|full.?name/i.test(
        q.question
      );
    const { action, confidence } = resolveQuestionAction(
      { ...q, risk },
      { knownContact, hasCoverLetter }
    );
    // Already-filled cover letter fields should not re-enter Copilot Input
    if (
      hasCoverLetter &&
      isCoverLetterQuestion(q.question) &&
      action === "AUTOFILL"
    ) {
      return { ...q, risk, confidence, action };
    }
    return {
      ...q,
      risk,
      confidence,
      action,
    };
  });
}

export async function findSubmitButton(page) {
  const selectors = [
    'button[type="submit"]',
    'input[type="submit"]',
    'button:has-text("Submit Application")',
    'button:has-text("Submit")',
    'button:has-text("Send Application")',
  ];
  for (const sel of selectors) {
    const loc = page.locator(sel).first();
    if ((await loc.count()) > 0) return loc;
  }
  return null;
}

export async function confirmSubmissionSignals(page) {
  const url = page.url();
  const text = (await page.locator("body").innerText().catch(() => "")).slice(
    0,
    5000
  );
  const signals = [];
  if (/thank you for (your )?applying|application (has been )?submitted|we.ve received your application/i.test(text)) {
    signals.push({ type: "PAGE_TEXT", value: "thank_you_or_submitted" });
  }
  if (/confirmation|submitted|success|thank/i.test(url)) {
    signals.push({ type: "URL", value: url });
  }
  return {
    submissionStatus: signals.length ? "CONFIRMED" : "UNCERTAIN",
    confirmationSignals: signals,
    confirmedAt: signals.length ? new Date().toISOString() : null,
    pageUrl: url,
  };
}

export async function clickContinueIfPresent(page, cfg) {
  const selectors = [
    'button:has-text("Continue")',
    'button:has-text("Next")',
    'button:has-text("Save and Continue")',
  ];
  for (const sel of selectors) {
    const loc = page.locator(sel).first();
    if ((await loc.count()) > 0) {
      try {
        await loc.click({ timeout: 5000 });
        await humanDelay(cfg);
        return true;
      } catch {
        /* ignore */
      }
    }
  }
  return false;
}
