/**
 * Generic travel CLI entry point.
 *
 * This file is the future hub for the travel planning toolset. For now, it
 * has one command: "research". Later, we can plug in more scripts here, such
 * as lodging search, transport comparison, shortlist saving, or report export.
 */

import { main as runResearch } from "./scripts/research.js";
import {
  main as runLodgingSearch,
  redditLoginMain,
} from "./scripts/lodging-search.js";

/**
 * Print a small help message when the user does not provide a command.
 */
function printUsage() {
  console.log("Usage:");
  console.log(
    'npm run travel -- research "make me a lodging research plan for Amsterdam during SDF"'
  );
  console.log("npm run travel -- lodging Amsterdam");
  console.log("npm run travel -- reddit-login");
  console.log("");
  console.log("Commands:");
  console.log("  lodging   Search browser pages for lodging candidates.");
  console.log("  reddit-login  Open a browser so you can log into Reddit once.");
  console.log("  research  Create a local Ollama-powered travel research plan.");
}

/**
 * Route command-line input to the right travel script.
 *
 * process.argv starts with Node internals, so slice(2) gives us the user
 * command and the words that follow it.
 */
async function main() {
  const [command, ...args] = process.argv.slice(2);

  if (!command) {
    printUsage();
    return;
  }

  if (command === "research") {
    await runResearch(args);
    return;
  }

  if (command === "lodging") {
    await runLodgingSearch(args);
    return;
  }

  if (command === "reddit-login") {
    await redditLoginMain();
    return;
  }

  console.error(`Unknown travel command: ${command}`);
  console.error("");
  printUsage();
  process.exitCode = 1;
}

/**
 * Keep command failures readable while still returning a failing exit code.
 */
main().catch((error) => {
  console.error("\nTravel command failed:");
  console.error(error.message);
  process.exitCode = 1;
});
