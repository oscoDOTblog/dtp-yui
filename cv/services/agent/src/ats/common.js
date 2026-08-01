import path from "path";
import {
  classifyQuestionRisk,
  resolveQuestionAction,
} from "../policy.js";
import { humanDelay } from "../config.js";

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
 * Scan form questions that look unknown / high-risk.
 */
export async function collectUnknownQuestions(page) {
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
      { knownContact }
    );
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
