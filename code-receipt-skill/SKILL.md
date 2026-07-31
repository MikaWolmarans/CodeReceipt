---
name: code-receipt
description: >-
  Turn any codebase into a plain-English owner's manual and a universal
  agent-context file. Use when the user wants to understand a repo they (or an
  AI) built: "explain my codebase", "what did I actually ship", "document this
  repo", "make a CLAUDE.md / AGENTS.md", "onboard me to this project", "what
  breaks if I touch this". Scans the repo deterministically (no data leaves the
  machine), then writes MANUAL.md (for humans) plus AGENTS.md and CLAUDE.md (for
  any AI coding agent).
---

# CodeReceipt

You are producing an **owner's manual** for a codebase: what it actually is, how
it holds together, what breaks if you touch it, and how to keep it alive. The
reader is often the person who built it with an AI and doesn't fully understand
what they shipped. Your job is to hand it back to them in plain English.

This skill is free and runs entirely on the user's machine. The deterministic
scan gathers facts; **you** (the agent) supply the language. No API, no server.

## Voice

- **Plain English for a smart non-specialist.** No jargon without a one-line gloss.
- **Deadpan, direct, a little dry.** State what's true. Don't hype, don't hedge.
- **Never invent.** If the code doesn't show it, write "Not confidently detected."
  Do not guess at hosting providers, services, or dependencies that aren't in the
  files. A wrong confident claim is worse than an honest gap.
- **No first person, no filler.** Every sentence earns its place.
- **No em dashes or en dashes.** Use commas, colons, periods, or parentheses.

## Workflow

### 1. Scan the repo (deterministic, no AI)

From the repo root, run the bundled scanner:

```bash
python3 .claude/skills/code-receipt/scripts/scan.py . -o codereceipt-facts.json
```

(Adjust the path if the skill lives elsewhere.) This writes `codereceipt-facts.json`
containing: `repo_name`, `stack`, `entry_points`, `config_files`, `env_vars`, and a
size-ranked `file_map` (path, line count, and a first-line hint per file). Nothing
is sent anywhere.

### 2. Read the facts, then read the code that matters

Load `codereceipt-facts.json`. Then **open and actually read** the highest-signal
files. Don't work from the hints alone:

- The `entry_points` (where execution starts).
- The largest files in `file_map` (usually the core logic).
- Every `config_files` entry (dependencies, build, deploy).
- Any file whose hint suggests routing, auth, data models, or payments.

Read enough to describe each key system truthfully. Where the facts and the code
disagree, trust the code.

### 3. Write the universal agent-context file (concise)

Write **two identical files** to the repo root: `AGENTS.md` and `CLAUDE.md`.

- `AGENTS.md` is the emerging cross-tool standard, read by Cursor, Windsurf,
  GitHub Copilot, Zed, and others.
- `CLAUDE.md` is what Claude Code loads automatically.

Give them the **same content** so every agent gets the same briefing regardless of
which filename it looks for. Keep the wording tool-agnostic (say "the agent" or
"AI tools", not "Claude" specifically). If the repo already has one of these files,
show the user your proposed content and ask before overwriting.

Follow `references/manual-sections.md` for the exact sections. Keep it tight, it's
a working reference, not prose. Include the safe-to-touch traffic lights
(`references/safe-to-touch.md`), env-var names (names and purpose only, **never
values**), key systems, known risks, and conventions.

### 4. Write `MANUAL.md` (human owner's manual, fuller)

Write to the repo root. This is the readable manual: the same underlying facts,
expanded for a person who wants to understand what they own. Lead with a
plain-English "what you built" and a Quick Start, then architecture, key systems,
the safe-to-touch map, environment variables, running costs (only services
actually evidenced in the code), risks, and suggested next actions.

### 5. Report and clean up

Tell the user what you wrote, the stack you detected, and your overall confidence.
Offer to delete `codereceipt-facts.json` (it's an intermediate artifact) or keep it
if they want to re-run.

## Rules

- **Secrets never leave.** `.env*` files are excluded by the scanner by design.
  Emit env-var **names and purpose**, never values. If you happen to read a secret,
  do not reproduce it.
- **Confidence is a feature.** Mark each major section high, medium, or low, and use
  "Not confidently detected." freely. The user trusts this because it doesn't lie.
- **Two audiences, three files.** `AGENTS.md` and `CLAUDE.md` are terse, identical,
  and machine-facing. `MANUAL.md` is fuller and human-facing. Don't collapse them.
- **No em dashes or en dashes** anywhere in the output.
