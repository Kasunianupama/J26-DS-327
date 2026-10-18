# Claude Code instructions for the dairy intelligence monorepo

## ⛔ No database access for Claude (overrides everything else)

- Never connect to any database (`farmx_app`, `farmx_research`, DelPro / SQL Server or any
  other), never read `.env`, never read real row-level data, and never ask for passwords.
- When a check is needed, write aggregate-only SQL or a command; the user runs it and
  sends back the numbers.
- You may edit code and docs and run unit tests and builds on synthetic data.

Component folders have their own `CLAUDE.md`; read it when working inside that folder.

## Full rules for all components

@AGENTS.md
