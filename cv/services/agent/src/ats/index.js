import { detectAts, AtsType } from "./detect.js";
import * as greenhouse from "./greenhouse.js";
import * as lever from "./lever.js";
import * as generic from "./generic.js";
import * as indeedSmartApply from "./indeedSmartApply.js";

export function getAdapter(atsType) {
  switch (atsType) {
    case AtsType.GREENHOUSE:
      return {
        begin: greenhouse.beginGreenhouse,
        fill: greenhouse.fillGreenhouse,
        submit: greenhouse.submitGreenhouse,
      };
    case AtsType.LEVER:
      return {
        begin: lever.beginLever,
        fill: lever.fillLever,
        submit: lever.submitLever,
      };
    case AtsType.INDEED_SMARTAPPLY:
      return {
        begin: indeedSmartApply.beginIndeedSmartApply,
        fill: indeedSmartApply.fillIndeedSmartApply,
        submit: indeedSmartApply.submitIndeedSmartApply,
      };
    default:
      return {
        begin: generic.beginGeneric,
        fill: generic.fillGeneric,
        submit: generic.submitGeneric,
      };
  }
}

export async function resolveAdapter(page) {
  const title = await page.title().catch(() => "");
  const atsType = detectAts(page.url(), title);
  return { atsType, adapter: getAdapter(atsType) };
}

export { AtsType, detectAts };
