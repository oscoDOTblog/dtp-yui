import {
  collectUnknownQuestions,
  confirmSubmissionSignals,
  fillKnownContactFields,
  findSubmitButton,
  uploadResume,
  clickContinueIfPresent,
} from "./common.js";
import { AtsType } from "./detect.js";

export async function beginLever(page, ctx) {
  await page.waitForLoadState("domcontentloaded").catch(() => {});
  // Lever often has an "Apply for this job" that expands the form.
  const apply = page.locator('a:has-text("Apply for this job"), button:has-text("Apply for this job")').first();
  if ((await apply.count()) > 0) {
    await apply.click().catch(() => {});
  }
  return { atsType: AtsType.LEVER, pageUrl: page.url() };
}

export async function fillLever(page, ctx) {
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

export async function submitLever(page, ctx) {
  const btn = await findSubmitButton(page);
  if (!btn) throw new Error("Submit button not found on Lever");
  await btn.click();
  await page.waitForLoadState("domcontentloaded").catch(() => {});
  return confirmSubmissionSignals(page);
}
