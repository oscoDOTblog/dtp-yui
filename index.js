/**
 * Day 1 Canonical Agent
 *
 * Goal:
 * - User asks about a local video file
 * - Ollama decides whether to call a tool
 * - Your app executes the real tool using ffprobe
 * - Tool result goes back to Ollama
 * - Ollama writes a human-friendly summary
 */

import ollama from "ollama";
import { execFile } from "child_process";
import { promisify } from "util";
import fs from "fs/promises";

const execFileAsync = promisify(execFile);

const MODEL = "qwen3:8b";

const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

/**
 * Simple console spinner for long-running model calls.
 * Uses stderr so it doesn't mix with the final answer on stdout.
 */
function createSpinner(label) {
  let frame = 0;
  let timer;

  return {
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
    stop(doneLabel) {
      if (timer) {
        clearInterval(timer);
        timer = undefined;
      }

      if (process.stderr.isTTY) {
        process.stderr.write(`\r${doneLabel ?? `${label}... done`}\n`);
      }
    },
    update(nextLabel) {
      label = nextLabel;
    },
  };
}

/**
 * Stream a chat response from Ollama while showing a spinner during thinking.
 * qwen3 emits `message.thinking` chunks before tool calls or the final answer.
 */
async function chatWithSpinner({ label, ...request }) {
  const spinner = createSpinner(label);
  spinner.start();

  const stream = await ollama.chat({ ...request, stream: true, think: true });

  let message = { role: "assistant", content: "", thinking: "" };
  let toolCalls = [];
  let sawThinking = false;
  let sawContent = false;

  for await (const chunk of stream) {
    if (chunk.message.thinking) {
      if (!sawThinking) {
        sawThinking = true;
        spinner.update("Reasoning");
      }
      message.thinking += chunk.message.thinking;
    }

    if (chunk.message.content) {
      if (!sawContent) {
        sawContent = true;
        spinner.update("Writing answer");
      }
      message.content += chunk.message.content;
    }

    if (chunk.message.tool_calls?.length) {
      spinner.update("Choosing tool");
      toolCalls = chunk.message.tool_calls;
    }
  }

  spinner.stop(sawThinking ? "Reasoning complete" : `${label}... done`);

  if (message.thinking && process.env.SHOW_THINKING === "1") {
    process.stderr.write("\n--- thinking ---\n");
    process.stderr.write(`${message.thinking.trim()}\n`);
    process.stderr.write("----------------\n\n");
  }

  message.tool_calls = toolCalls.length ? toolCalls : undefined;

  return { message };
}

/**
 * TOOL: inspectVideo
 *
 * The LLM does NOT run this directly.
 * It only requests that this function be called.
 * Your application decides whether to trust and execute it.
 */
async function inspectVideo(args) {
  const { path } = args;

  if (!path || typeof path !== "string") {
    throw new Error("inspect_video requires a string path.");
  }

  try {
    await fs.access(path);
  } catch {
    throw new Error(`File does not exist: ${path}`);
  }

  try {
    const { stdout } = await execFileAsync("ffprobe", [
      "-v",
      "error",
      "-print_format",
      "json",
      "-show_format",
      "-show_streams",
      path,
    ]);

    return JSON.parse(stdout);
  } catch (error) {
    throw new Error(`ffprobe failed: ${error.message}`);
  }
}

/**
 * Tool schema given to Ollama.
 *
 * This tells the model:
 * - what tools exist
 * - what each tool does
 * - what arguments are valid
 */
const tools = [
  {
    type: "function",
    function: {
      name: "inspect_video",
      description:
        "Inspect a local video file and return duration, codec, resolution, audio/video streams, and container metadata.",
      parameters: {
        type: "object",
        properties: {
          path: {
            type: "string",
            description: "Local file path, for example ./sample.mp4",
          },
        },
        required: ["path"],
      },
    },
  },
];

/**
 * Tool registry.
 *
 * This maps the model-facing tool name:
 *
 * inspect_video
 *
 * to the real JavaScript function:
 *
 * inspectVideo()
 */
const availableTools = {
  inspect_video: inspectVideo,
};

/**
 * Executes a tool call requested by the model.
 */
async function runToolCall(toolCall) {
  const name = toolCall.function?.name;
  const args = toolCall.function?.arguments || {};

  console.log("\nTool chosen:", name);
  console.log("Arguments:", args);

  const toolFn = availableTools[name];

  if (!toolFn) {
    throw new Error(`Unknown tool requested by model: ${name}`);
  }

  return await toolFn(args);
}

/**
 * Main agent loop.
 */
async function main() {
  const userMessage =
    process.argv.slice(2).join(" ") ||
    "Inspect ./sample.mp4 and summarize its codec, duration, and resolution.";

  /**
   * Conversation history.
   *
   * LLMs are stateless.
   * Every call must include the context we want the model to know.
   */
  const messages = [
    {
      role: "user",
      content: userMessage,
    },
  ];

  /**
   * First model call.
   *
   * The model decides:
   * - answer directly
   * - or request one/more tools
   */
  const firstResponse = await chatWithSpinner({
    label: "Agent thinking",
    model: MODEL,
    messages,
    tools,
  });

  messages.push(firstResponse.message);

  const toolCalls = firstResponse.message.tool_calls || [];

  if (toolCalls.length === 0) {
    console.log(firstResponse.message.content);
    return;
  }

  /**
   * Execute all requested tool calls.
   */
  for (const toolCall of toolCalls) {
    try {
      const result = await runToolCall(toolCall);

      /**
       * Feed tool output back into the conversation.
       *
       * This is where the LLM gets access to real-world data.
       */
      messages.push({
        role: "tool",
        tool_name: toolCall.function.name,
        content: JSON.stringify(result),
      });
    } catch (error) {
      /**
       * Tool errors are also useful context.
       *
       * Instead of crashing silently, give the model the error.
       */
      messages.push({
        role: "tool",
        tool_name: toolCall.function?.name || "unknown_tool",
        content: JSON.stringify({
          error: error.message,
        }),
      });
    }
  }

  /**
   * Second model call.
   *
   * Now the model has:
   * - original user request
   * - tool result or tool error
   *
   * It can produce the final answer.
   */
  const finalResponse = await chatWithSpinner({
    label: "Summarizing",
    model: MODEL,
    messages,
  });

  console.log("\nFinal answer:\n");
  console.log(finalResponse.message.content);
}

/**
 * Start the app.
 *
 * Common failure here:
 * - Ollama is not running
 * - model has not been pulled
 * - ffmpeg/ffprobe is not installed
 */
main().catch((error) => {
  console.error("\nFatal error:");
  console.error(error.message);
});