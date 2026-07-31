# CodeReceipt (Claude Code Skill)

**Understand your code.** Point your AI agent at any repo and get back a
plain-English owner's manual: what you actually shipped, how it holds together,
what breaks if you touch it, and how to keep it alive.

Built for people who shipped something with an AI and don't fully understand what
they own. Free, open, and runs entirely on your machine. No account, no server,
no API key. Your existing agent (Claude Code, Cursor, etc.) does the writing;
this skill supplies the method.

## What you get

Run it in a repo and the agent writes two files to the project root:

- **`MANUAL.md`**: a readable owner's manual for humans: architecture, key
  systems, a safe-to-touch map, environment variables, running costs, and risks.
- **`AGENTS.md` and `CLAUDE.md`**: one universal agent-context file, written under both names so Claude Code, Cursor, Windsurf, Copilot and other
  tools understand the codebase *before* they edit it.

## How it works

1. A zero-dependency Python scanner (`scripts/scan.py`) walks the repo and
   extracts objective facts: stack, file map, env-var names, entry points. **No
   AI, no network.** `.env*` files are excluded by design; secrets never leave.
2. Your agent reads those facts, opens the files that matter, and writes the
   manual in plain English, marking anything it can't verify as "Not confidently
   detected." rather than guessing.

## Install

Copy the `code-receipt` folder into your project's skills directory:

```bash
mkdir -p .claude/skills
cp -r code-receipt .claude/skills/code-receipt
```

(Or drop it in your user-level `~/.claude/skills/` to use it in every project.)

## Use

In Claude Code, just ask:

> Explain this codebase / document this repo / make me an AGENTS.md

The agent invokes the skill, scans, and writes `MANUAL.md` plus `AGENTS.md` and
`CLAUDE.md` (identical agent-context content, under both names, so any agent picks
it up).

## Run the scanner on its own

The scan is useful by itself. It's plain stdlib Python 3:

```bash
python3 .claude/skills/code-receipt/scripts/scan.py . -o codereceipt-facts.json
```

## Why free

Plenty of tools got me here as a developer. This is one back. Learn from your own
codebase, and from how the scan and the manual are put together.
