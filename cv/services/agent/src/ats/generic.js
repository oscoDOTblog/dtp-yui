import {
  collectUnknownQuestions,
  confirmSubmissionSignals,
  fillKnownContactFields,
  findSubmitButton,
  uploadResume,
  clickContinueIfPresent,
} from "./common.js";
import { AtsType } from "./detect.js";

/**
 * Generic fallback — Playwright heuristics only (Stagehand can replace later).
 */
export async function beginGeneric(page, ctx) {
  await page.waitForLoadState("domcontentloaded").catch(() => {});
  return { atsType: AtsType.UNKNOWN, pageUrl: page.url() };
}

export async function fillGeneric(page, ctx) {
  const { profile, resumePath, events, cfg } = ctx;
  await fillKnownContactFields(page, profile, events);
  if (resumePath) {
    await uploadResume(page, resumePath, events).catch((err) =>
      events.emit("ERROR", {
        message: `Resume upload: ${err.message}`,
        recoverable: true,
      })
    );
  }
  await clickContinueIfPresent(page, cfg);
  const unknowns = await collectUnknownQuestions(page);
  return { unknowns };
}

export async function submitGeneric(page, ctx) {
  const btn = await findSubmitButton(page);
  if (!btn) throw new Error("Submit button not found");
  await btn.click();
  await page.waitForLoadState("domcontentloaded").catch(() => {});
  return confirmSubmissionSignals(page);
}
