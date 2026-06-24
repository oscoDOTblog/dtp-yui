/**
 * Simple travel research CLI.
 *
 * This is "part 1" of the travel agent project:
 * - Read local trip criteria from travel/criteria.json.
 * - Ask a local Ollama model for a research plan.
 * - Save the response to travel/outputs/research.md.
 *
 * This file intentionally does not browse the web or check live prices yet.
 */

import ollama from "ollama";
import fs from "fs/promises";

/**
 * The local Ollama model to use.
 *
 * You can override this without editing code:
 * TRAVEL_MODEL="llama3.1:8b" node travel-research.js "your request"
 */
const MODEL = process.env.TRAVEL_MODEL || "qwen3:8b";

/**
 * Frames used by the terminal loading animation.
 *
 * These are the same braille spinner frames used in index.js so both CLIs
 * feel consistent while Ollama is working.
 */
const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

/**
 * The criteria file is the stable memory for the trip.
 *
 * Keeping it separate from the code makes it easy to edit your travel
 * preferences without touching JavaScript.
 */
const CRITERIA_PATH = "travel/criteria.json";

/**
 * The output path is intentionally simple for part 1.
 *
 * Later, we can make one file per request or one folder per trip.
 */
const OUTPUT_PATH = "travel/outputs/research.md";

/**
 * Create a small terminal spinner.
 *
 * The spinner writes to stderr instead of stdout. That keeps the loading
 * animation separate from the final research answer, which prints to stdout.
 */
function createSpinner(label) {
  let frame = 0;
  let timer;

  return {
    /**
     * Start the animation.
     *
     * If stderr is not an interactive terminal, print a plain line instead of
     * using carriage returns that might look messy in logs.
     */
    start() {
      if (!process.stderr.isTTY) {
        process.stderr.write(`${label}...\n`);
        return;
      }

      timer = setInterval(() => {
        process.stderr.write(
          `\r${SPINNER_FRAMES[frame++ % SPINNER_FRAMES.length]} ${label}`
        );
      }, 80);
    },

    /**
     * Stop the animation and optionally print a completion label.
     */
    stop(doneLabel) {
      if (timer) {
        clearInterval(timer);
        timer = undefined;
      }

      if (process.stderr.isTTY) {
        process.stderr.write(`\r${doneLabel ?? `${label}... done`}\n`);
      }
    },

    /**
     * Change the visible label while the spinner is running.
     */
    update(nextLabel) {
      label = nextLabel;
    },
  };
}

/**
 * Stream a chat response from Ollama while showing a loading animation.
 *
 * Streaming gives us progress signals:
 * - qwen3 may send thinking chunks first.
 * - then it sends final answer chunks.
 *
 * The CLI still returns one complete string so the rest of the code stays
 * beginner-friendly.
 */
async function chatWithSpinner({ label, ...request }) {
  const spinner = createSpinner(label);
  spinner.start();

  const stream = await ollama.chat({ ...request, stream: true, think: true });

  let content = "";
  let thinking = "";
  let sawThinking = false;
  let sawContent = false;

  for await (const chunk of stream) {
    if (chunk.message.thinking) {
      if (!sawThinking) {
        sawThinking = true;
        spinner.update("Reasoning");
      }

      thinking += chunk.message.thinking;
    }

    if (chunk.message.content) {
      if (!sawContent) {
        sawContent = true;
        spinner.update("Writing answer");
      }

      content += chunk.message.content;
    }
  }

  spinner.stop(sawThinking ? "Reasoning complete" : `${label}... done`);

  /**
   * The model's private reasoning is hidden by default.
   *
   * Set SHOW_THINKING=1 if you want to inspect it while learning.
   */
  if (thinking && process.env.SHOW_THINKING === "1") {
    process.stderr.write("\n--- thinking ---\n");
    process.stderr.write(`${thinking.trim()}\n`);
    process.stderr.write("----------------\n\n");
  }

  return content;
}

/**
 * Read and parse the trip criteria JSON file.
 *
 * This gives the model specific constraints instead of asking it to invent
 * your budget, dates, or priorities.
 */
async function readCriteria() {
  const criteriaRaw = await fs.readFile(CRITERIA_PATH, "utf8");
  return JSON.parse(criteriaRaw);
}

/**
 * Ask Ollama for a plain research plan.
 *
 * The prompt is strict about honesty: the model should not claim it checked
 * live prices because this part 1 CLI has no live search tool yet.
 */
async function askOllamaForResearchPlan({ userRequest, criteria }) {
  return await chatWithSpinner({
    label: "Researching",
    model: MODEL,
    messages: [
      {
        role: "system",
        content:
          "You are a careful travel research assistant. Do not book anything. Do not claim you checked live prices. Use the user's criteria and produce practical next steps.",
      },
      {
        role: "user",
        content: `
My trip criteria:
${JSON.stringify(criteria, null, 2)}

My travel research request:
${userRequest}

Please respond with:
1. A short summary of the research goal.
2. Search queries I should run manually.
3. A comparison checklist for options I find.
4. Red flags or tradeoffs to watch for.
5. Three questions for me before deeper research.
`,
      },
    ],
  });
}

/**
 * Write the model response to a Markdown file.
 *
 * Saving the output makes each run reviewable, which is useful while learning
 * how the agent behaves.
 */
async function saveResearchOutput({ userRequest, result }) {
  const output = `# Travel Research

## Request

${userRequest}

## Result

${result}
`;

  await fs.mkdir("travel/outputs", { recursive: true });
  await fs.writeFile(OUTPUT_PATH, output);
}

/**
 * Main command-line entry point.
 *
 * Node passes command-line words through process.argv. The first two entries
 * are Node internals, so the actual user request starts at index 2.
 */
async function main() {
  const userRequest = process.argv.slice(2).join(" ").trim();

  if (!userRequest) {
    console.log("Usage:");
    console.log(
      'npm run travel:research -- "make me a lodging research plan for Amsterdam during SDF"'
    );
    return;
  }

  const criteria = await readCriteria();
  const result = await askOllamaForResearchPlan({ userRequest, criteria });

  await saveResearchOutput({ userRequest, result });

  console.log(result);
  console.log(`\nSaved to ${OUTPUT_PATH}`);
}

/**
 * Report errors in a beginner-friendly way.
 *
 * Common causes are:
 * - Ollama is not running.
 * - The configured model has not been pulled.
 * - travel/criteria.json contains invalid JSON.
 */
main().catch((error) => {
  console.error("\nTravel research failed:");
  console.error(error.message);
  console.error("\nTry starting Ollama with: ollama serve");
  process.exitCode = 1;
});
