# Hopewell — Flotilla plugin contributions

This directory turns Hopewell into a Flotilla plugin. When a downstream
project runs `flotilla install hopewell`, the Flotilla CLI:

1. `pip install hopewell`
2. Locates the manifest at `<repo>/flotilla.yaml`
3. Copies/symlinks `plugin/agents/*.md` -> `.claude/agents/`
4. Copies/symlinks `plugin/commands/*.md` -> `.claude/commands/`
5. Merges `plugin/hooks.yaml` into `.claude/settings.json`
6. Runs the `on_install` steps from the manifest

See `flotilla.yaml` (one level up) for the manifest. See
[github.com/ocgully/flotilla](https://github.com/ocgully/flotilla) for
the CLI itself.

## What ships

- `agents/hopewell-scribe.md` — the agent that queries the work ledger
- `commands/hw.md` — `/hw` Claude Code command for ready-queue context
- `hooks.yaml` — `SessionStart` hook to surface active claims
