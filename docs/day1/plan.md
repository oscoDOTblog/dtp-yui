Perfect. The implementation is almost identical on macOS, and honestly it's a bit easier because Homebrew makes installation straightforward.

---

# Day 1 (macOS Version)

Goal:

```txt
User
↓
"Inspect sample.mp4"
↓
Local Ollama model chooses a tool
↓
Your Node app executes ffprobe
↓
Ollama summarizes the result
```

This is the exact same agent primitive used by MCP and coding agents.

---

# 1. Install Homebrew (if needed)

Check if you already have it:

```bash
brew --version
```

If not:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

---

# 2. Install Ollama

```bash
brew install ollama
```

Start Ollama:

```bash
ollama serve
```

Leave this terminal running.

Alternatively, if you install the Ollama macOS app, it runs in the background automatically.

---

# 3. Pull a Model

Since you're on an M1 Pro:

### Recommended

```bash
ollama pull qwen3:8b
```

Good balance of:

* speed
* reasoning
* tool use

---

### Alternative (better coding)

```bash
ollama pull qwen2.5-coder:7b
```

Slightly more coding-focused.

---

# 4. Install ffmpeg

macOS doesn't include ffprobe by default.

Install via Homebrew:

```bash
brew install ffmpeg
```

Verify:

```bash
ffprobe -version
```

You should see something like:

```txt
ffprobe version ...
```

---

# 5. Create the Project

```bash
mkdir agent-week1-ollama
cd agent-week1-ollama

npm init -y
npm install ollama
```

---

# 6. Enable ES Modules

Edit `package.json`:

```json
{
  "type": "module"
}
```

Example:

```json
{
  "name": "agent-week1-ollama",
  "version": "1.0.0",
  "type": "module",
  "dependencies": {
    "ollama": "^0.x"
  }
}
```

---

# 7. Create `index.js`

```js
import ollama from "ollama";
import { execFile } from "child_process";
import { promisify } from "util";

const execFileAsync = promisify(execFile);

async function inspectVideo({ path }) {
  const { stdout } = await execFileAsync("ffprobe", [
    "-v", "error",
    "-print_format", "json",
    "-show_format",
    "-show_streams",
    path,
  ]);

  return JSON.parse(stdout);
}

const tools = [
  {
    type: "function",
    function: {
      name: "inspect_video",
      description:
        "Inspect a local video file and return codec, duration, resolution, and stream metadata.",
      parameters: {
        type: "object",
        properties: {
          path: {
            type: "string",
            description: "Local file path (e.g. ./sample.mp4)",
          },
        },
        required: ["path"],
      },
    },
  },
];

const availableTools = {
  inspect_video: inspectVideo,
};

async function main() {
  const userMessage =
    process.argv.slice(2).join(" ") ||
    "Inspect ./sample.mp4 and summarize it.";

  const messages = [
    {
      role: "user",
      content: userMessage,
    },
  ];

  const response = await ollama.chat({
    model: "qwen3:8b",
    messages,
    tools,
  });

  messages.push(response.message);

  const toolCalls = response.message.tool_calls || [];

  if (toolCalls.length === 0) {
    console.log(response.message.content);
    return;
  }

  for (const toolCall of toolCalls) {
    const name = toolCall.function.name;
    const args = toolCall.function.arguments;

    console.log("Tool chosen:", name);
    console.log("Arguments:", args);

    const toolFn = availableTools[name];

    if (!toolFn) {
      throw new Error(`Unknown tool: ${name}`);
    }

    const result = await toolFn(args);

    messages.push({
      role: "tool",
      tool_name: name,
      content: JSON.stringify(result),
    });
  }

  const finalResponse = await ollama.chat({
    model: "qwen3:8b",
    messages,
  });

  console.log("\nFinal answer:\n");
  console.log(finalResponse.message.content);
}

main().catch(console.error);
```

---

# 8. Add a Test Video

Put any MP4 into the folder:

```txt
agent-week1-ollama/
├── sample.mp4
├── index.js
└── package.json
```

---

# 9. Run It

```bash
node index.js "Inspect ./sample.mp4 and tell me the codec, duration, and resolution."
```

Expected output:

```txt
Tool chosen: inspect_video
Arguments: { path: './sample.mp4' }

Final answer:

The video is 1920×1080 using H.264 encoding.
Its duration is 23.8 seconds...
```

---

# What You Actually Learned on Day 1

Without realizing it, you've already touched the core of modern agent systems:

```txt
JSON Schemas
↓
Tool Definitions
↓
LLM Decision Making
↓
Executing Real Code
↓
Passing Results Back
↓
Multi-step Reasoning
```

This is literally the foundation underneath:

* MCP servers
* Claude Code
* OpenAI Codex
* Cursor agents
* enterprise AI workflows
* Forward Deployed Engineering

---

# Bonus Challenge (30 minutes)

Add a second tool:

```js
get_current_time()
```

Then try prompts like:

```txt
What time is it right now?

Inspect sample.mp4 and tell me whether it's longer than 30 seconds.
```

Once the model reliably chooses between **multiple tools**, you've crossed from "calling an LLM" into **building agent systems**. That's the first major milestone on the FDE path.
