/**
 * Indeed Smart Apply (Glassdoor Easy Apply) multi-step wizard.
 * Modules from screenshots: qualification-questions → resume → relevant-experience → review.
 */

import {
  clickContinueIfPresent,
  confirmSubmissionSignals,
  findSubmitButton,
  uploadResume,
} from "./common.js";
import { AtsType } from "./detect.js";
import {
  classifyQuestionRisk,
  isTechYesNoQuestion,
  QUESTION_ACTION,
  resolveQuestionAction,
  RISK,
} from "../policy.js";
import { humanDelay, sleep } from "../config.js";

function moduleFromUrl(url = "") {
  const u = String(url).toLowerCase();
  if (/qualification-questions/.test(u)) return "questions";
  if (/resume-selection|resume-module/.test(u) && !/relevant-experience/.test(u)) {
    return "resume";
  }
  if (/relevant-experience/.test(u)) return "relevantExperience";
  if (/review-module|\/review/.test(u)) return "review";
  if (/form\//.test(u)) return "form";
  return "unknown";
}

async function clickContinue(page, cfg) {
  const clicked = await clickContinueIfPresent(page, cfg);
  if (clicked) {
    await page.waitForLoadState("domcontentloaded").catch(() => {});
    await sleep(600);
  }
  return clicked;
}

/**
 * Select Yes on Yes/No radio groups for tech questions.
 */
async function answerTechQuestionsYes(page, events) {
  const answered = await page.evaluate(() => {
    const results = [];
    const groups = document.querySelectorAll(
      '[role="radiogroup"], fieldset, [class*="question"], [data-testid*="question"]'
    );
    const roots = groups.length
      ? groups
      : [document.body];

    for (const root of roots) {
      const text = (root.textContent || "").replace(/\s+/g, " ").trim().slice(0, 400);
      if (!text) continue;
      const radios = root.querySelectorAll('input[type="radio"]');
      if (!radios.length) continue;

      let yesInput = null;
      for (const r of radios) {
        const id = r.id;
        let label = "";
        if (id) {
          const lab = document.querySelector(`label[for="${CSS.escape(id)}"]`);
          label = lab ? lab.textContent.trim() : "";
        }
        if (!label) {
          label = r.getAttribute("aria-label") || r.value || "";
        }
        if (/^yes$/i.test(label.trim()) || /^yes$/i.test(String(r.value || ""))) {
          yesInput = r;
          break;
        }
      }
      if (!yesInput) continue;
      if (!yesInput.checked) {
        yesInput.click();
        results.push({ question: text.slice(0, 200), value: "Yes" });
      }
    }
    return results;
  });

  for (const item of answered) {
    if (!isTechYesNoQuestion(item.question, ["Yes", "No"])) {
      // Still Yes if binary tech-ish; legal patterns skipped by isTechYesNo
      if (classifyQuestionRisk(item.question) === RISK.LEGAL) continue;
    }
    await events.emit("DECISION_MADE", {
      decision: "AUTO_YES",
      reason: "tech_default_yes",
      message: `Answered Yes: ${item.question.slice(0, 120)}`,
      confidence: 0.9,
      question: item.question,
    });
  }
  return answered;
}

/**
 * Collect remaining questions that need human input on the current page.
 */
async function collectAskUserQuestions(page) {
  const raw = await page.evaluate(() => {
    const out = [];
    const fields = document.querySelectorAll(
      "input, select, textarea, [role='radiogroup']"
    );
    for (const el of fields) {
      if (el.type === "hidden" || el.type === "file" || el.type === "submit") continue;
      if (el.type === "radio" && el.checked) continue;
      const id = el.id;
      let label = "";
      if (id) {
        const lab = document.querySelector(`label[for="${CSS.escape(id)}"]`);
        label = lab ? lab.textContent.trim() : "";
      }
      if (!label) {
        const wrap = el.closest(
          "label, .field, .form-group, [class*='question'], [role='radiogroup'], fieldset"
        );
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
      if (el.tagName === "SELECT") {
        for (const opt of el.options) options.push(opt.textContent.trim());
      }
      if (el.getAttribute("role") === "radiogroup" || el.tagName === "FIELDSET") {
        el.querySelectorAll('input[type="radio"]').forEach((r) => {
          const rid = r.id;
          let l = "";
          if (rid) {
            const lab = document.querySelector(`label[for="${CSS.escape(rid)}"]`);
            l = lab ? lab.textContent.trim() : r.value || "";
          } else {
            l = r.value || "";
          }
          if (l) options.push(l);
        });
      }
      out.push({
        question: label.slice(0, 300),
        fieldType:
          el.getAttribute("role") === "radiogroup"
            ? "radiogroup"
            : el.tagName.toLowerCase() === "select"
              ? "select"
              : el.type || "text",
        name: el.name || el.id || "",
        options,
        checked: Boolean(el.checked),
        value: el.value || "",
      });
    }
    return out;
  });

  return raw
    .map((q) => {
      const risk = classifyQuestionRisk(q.question);
      const { action, confidence } = resolveQuestionAction({ ...q, risk });
      return { ...q, risk, action, confidence };
    })
    .filter((q) => q.action === QUESTION_ACTION.ASK_USER);
}

async function fillRelevantExperience(page, latestRole, events) {
  const title = latestRole?.title || "";
  const company = latestRole?.company || "";
  if (!title && !company) {
    return { filled: false, reason: "no_latest_role" };
  }

  const filled = await page.evaluate(
    ({ title: t, company: c }) => {
      const inputs = Array.from(
        document.querySelectorAll(
          'input[type="text"], input:not([type]), textarea'
        )
      );
      const result = { title: false, company: false };
      for (const el of inputs) {
        const id = el.id;
        let label = "";
        if (id) {
          const lab = document.querySelector(`label[for="${CSS.escape(id)}"]`);
          label = lab ? lab.textContent.trim() : "";
        }
        const hay = `${label} ${el.name || ""} ${el.placeholder || ""} ${el.getAttribute("aria-label") || ""}`.toLowerCase();
        if (/job title|title/.test(hay) && t) {
          el.focus();
          el.value = t;
          el.dispatchEvent(new Event("input", { bubbles: true }));
          el.dispatchEvent(new Event("change", { bubbles: true }));
          result.title = true;
        }
        if (/company|employer|organization/.test(hay) && c) {
          el.focus();
          el.value = c;
          el.dispatchEvent(new Event("input", { bubbles: true }));
          el.dispatchEvent(new Event("change", { bubbles: true }));
          result.company = true;
        }
      }
      return result;
    },
    { title, company }
  );

  await events.emit("ACTION_COMPLETED", {
    action: "TYPE_APPROVED_VALUE",
    message: `Prefilled relevant experience: ${title} @ ${company}`,
    target: "latestRole",
  });
  return { filled: filled.title || filled.company, ...filled };
}

async function resumeAlreadySelected(page) {
  const text = await page.locator("body").innerText().catch(() => "");
  return /uploaded (today|just now|on)|resume options|\.docx|\.pdf/i.test(text);
}

export async function beginIndeedSmartApply(page, ctx) {
  await page.waitForLoadState("domcontentloaded").catch(() => {});
  await sleep(500);
  return {
    atsType: AtsType.INDEED_SMARTAPPLY,
    pageUrl: page.url(),
    module: moduleFromUrl(page.url()),
  };
}

/**
 * Drive Smart Apply modules until review (or ask-user unknowns remain).
 */
export async function fillIndeedSmartApply(page, ctx) {
  const { profile, resumePath, events, cfg } = ctx;
  const latestRole = profile?.latestRole || null;
  const unknowns = [];
  const maxSteps = 12;

  for (let step = 0; step < maxSteps; step += 1) {
    await page.waitForLoadState("domcontentloaded").catch(() => {});
    const url = page.url();
    const mod = moduleFromUrl(url);

    await events.emit("ACTION_COMPLETED", {
      message: `Smart Apply module: ${mod}`,
      pageUrl: url,
      atsType: AtsType.INDEED_SMARTAPPLY,
    });

    if (mod === "review") {
      break;
    }

    if (mod === "questions" || mod === "form" || mod === "unknown") {
      await answerTechQuestionsYes(page, events);
      const ask = await collectAskUserQuestions(page);
      // Only surface legal / unanswered non-auto fields
      for (const q of ask) {
        if (q.risk === RISK.LEGAL || q.risk === RISK.HIGH || q.risk === RISK.MEDIUM) {
          unknowns.push(q);
        } else if (
          q.fieldType === "text" ||
          q.fieldType === "textarea" ||
          q.fieldType === "select"
        ) {
          // Skip empty contact-like; ask free-text
          if (
            !/first.?name|last.?name|e-?mail|phone|linkedin|github/i.test(
              q.question
            )
          ) {
            unknowns.push(q);
          }
        }
      }
      if (unknowns.length) {
        // Pause fill so runner can ask; do not Continue past legal questions
        const hasLegal = unknowns.some(
          (u) => u.risk === RISK.LEGAL || u.risk === RISK.HIGH
        );
        if (hasLegal) {
          return { unknowns, module: mod, awaitingUser: true };
        }
      }
      await clickContinue(page, cfg);
      continue;
    }

    if (mod === "resume") {
      const selected = await resumeAlreadySelected(page);
      if (!selected && resumePath) {
        await uploadResume(page, resumePath, events).catch((err) =>
          events.emit("ERROR", {
            message: `Resume upload: ${err.message}`,
            recoverable: true,
          })
        );
        await humanDelay(cfg);
      } else {
        await events.emit("ACTION_COMPLETED", {
          message: selected
            ? "Resume already selected — continuing"
            : "No resume file to upload",
        });
      }
      await clickContinue(page, cfg);
      continue;
    }

    if (mod === "relevantExperience") {
      const result = await fillRelevantExperience(page, latestRole, events);
      if (!result.filled) {
        unknowns.push({
          question: "Enter a job that shows relevant experience (Job title / Company)",
          fieldType: "text",
          name: "relevantExperience",
          options: [],
          risk: RISK.MEDIUM,
          action: QUESTION_ACTION.ASK_USER,
          confidence: 0.2,
        });
        return { unknowns, module: mod, awaitingUser: true };
      }
      await humanDelay(cfg);
      await clickContinue(page, cfg);
      continue;
    }

    // Unknown module: try Continue, else stop
    const advanced = await clickContinue(page, cfg);
    if (!advanced) break;
  }

  return {
    unknowns,
    module: moduleFromUrl(page.url()),
    awaitingUser: false,
  };
}

export async function submitIndeedSmartApply(page, ctx) {
  const { events, cfg } = ctx;
  const btn = await findSubmitButton(page);
  // Indeed often uses "Submit your application" on review
  let submit = btn;
  if (!submit) {
    const alt = page.locator(
      'button:has-text("Submit your application"), button:has-text("Submit application"), button:has-text("Submit")'
    ).first();
    if ((await alt.count()) > 0) submit = alt;
  }
  if (!submit) throw new Error("Submit button not found on Indeed Smart Apply");

  await submit.click();
  await page.waitForLoadState("domcontentloaded").catch(() => {});
  await humanDelay(cfg);

  // Glassdoor confirmation modal: "Your application was sent!"
  const body = await page.locator("body").innerText().catch(() => "");
  if (/your application was sent|application (has been )?submitted/i.test(body)) {
    await events.emit("ACTION_COMPLETED", {
      message: "Application sent confirmation detected",
    });
    // Dismiss modal (X or Close)
    const closeSelectors = [
      'button[aria-label="Close"]',
      'button:has-text("Close")',
      '[data-test="closeButton"]',
      'button.modal_close',
    ];
    for (const sel of closeSelectors) {
      const loc = page.locator(sel).first();
      if ((await loc.count()) > 0) {
        await loc.click({ timeout: 3000 }).catch(() => {});
        break;
      }
    }
    return {
      submissionStatus: "CONFIRMED",
      confirmationSignals: [
        { type: "PAGE_TEXT", value: "application_was_sent" },
      ],
      confirmedAt: new Date().toISOString(),
      pageUrl: page.url(),
    };
  }

  return confirmSubmissionSignals(page);
}
