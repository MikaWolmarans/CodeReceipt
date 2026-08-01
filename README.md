<div align="center">

# CodeReceipt

**Understand your code.**

A free, open Claude Code skill that reads a repository you built with AI and writes the owner's manual: what you actually shipped, how it holds together, and what breaks if you touch it.

[Website](https://codereceipt.site) · [Install the skill](#install) · [How it works](#how-it-works)

</div>

---

## What it does

You shipped something with an AI. You do not fully understand what you own. CodeReceipt closes that gap. Point your coding agent at any repo and it produces two things:

- **`MANUAL.md`** — a readable owner's manual for humans: architecture, key systems, a safe-to-touch map, environment variables, running costs, and known risks.
- **`AGENTS.md`** and **`CLAUDE.md`** — one universal agent-context file, written under both names, so Claude Code, Cursor, Windsurf, Copilot and other AI tools understand the codebase before they edit it.

It runs entirely on your machine. No account, no server, no API key. Your own agent does the writing; the skill supplies the method.

## How it works

1. A zero-dependency Python scanner (`code-receipt-skill/scripts/scan.py`) walks the repo and extracts objective facts — stack, file map, entry points, environment-variable names. No AI, no network. `.env` files are excluded by design, so secrets never leave.
2. Your agent reads those facts, opens the files that matter, and writes the manual in plain English, marking anything it cannot verify rather than guessing.

## Install

Copy the skill into your project (or your user-level `~/.claude/skills/` to use it everywhere):

```bash
git clone https://github.com/MikaWolmarans/CodeReceipt.git
mkdir -p .claude/skills
cp -r CodeReceipt/code-receipt-skill .claude/skills/code-receipt
```

Then ask your agent:

> Explain this codebase / document this repo / make me an AGENTS.md

Prefer to run the scanner directly? It is plain stdlib Python 3, no install required:

```bash
python3 .claude/skills/code-receipt/scripts/scan.py . -o codereceipt-facts.json
```

## Repository layout

| Path | Purpose |
| --- | --- |
| `code-receipt-skill/` | The Claude Code skill: instructions, scanner, and references. |
| `docs/` | The static landing page served at [codereceipt.site](https://codereceipt.site) via GitHub Pages. |
| `app/`, `frontend/` | The hosted service (FastAPI backend and web UI) that powers the optional paid features. |

## Privacy

The scanner never makes a network call and never reads `.env*` files. The manual lists environment-variable names and their purpose, never their values. Your code stays on your machine.

## License

Released under the [MIT License](LICENSE).
