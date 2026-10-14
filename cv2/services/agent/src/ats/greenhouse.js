import {
  attachCoverLetterIfNeeded,
  collectUnknownQuestions,
  confirmSubmissionSignals,
  fillKnownContactFields,
  findSubmitButton,
  uploadResume,
  clickContinueIfPresent,
} from "./common.js";
import { AtsType } from "./detect.js";

export async function beginGreenhouse(page, ctx) {
  await page.waitForLoadState("domcontentloaded").catch(() => {});
  return { atsType: AtsType.GREENHOUSE, pageUrl: page.url() };
}

export async function fillGreenhouse(page, ctx) {
  const { profile, resumePath, coverLetter, events, cfg } = ctx;
  await fillKnownContactFields(page, profile, events);
  if (resumePath) {
    await uploadResume(page, resumePath, events).catch((err) =>
      events.emit("ERROR", {
        message: `Resume upload: ${err.message}`,
        recoverable: true,
      })
    );
  }
  const attach = await attachCoverLetterIfNeeded(page, coverLetter, events, cfg);
  await clickContinueIfPresent(page, cfg);
  const unknowns = await collectUnknownQuestions(page, {
    hasCoverLetter: Boolean(attach?.attached),
  });
  return { unknowns };
}

export async function submitGreenhouse(page, ctx) {
  const btn = await findSubmitButton(page);
  if (!btn) throw new Error("Submit button not found on Greenhouse");
  await btn.click();
  await page.waitForLoadState("domcontentloaded").catch(() => {});
  return confirmSubmissionSignals(page);
}
