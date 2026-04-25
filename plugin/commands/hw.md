---
description: Quick Hopewell context — show ready queue, active claims, and the orchestrator-routing hint
---

Run `hopewell resume` and surface the ready queue + active claims. If the user's request mentions a node id (e.g. `HW-0042`), also run `hopewell show <id>` and `hopewell query deps <id>` so the downstream agent has the full context bundle. After surfacing context, propose the next action (route to the right specialist, claim a ready node, or create a new node via `hopewell new`).

Do not modify the ledger; this command is read-only. To advance work, use `@hopewell-scribe` directly or invoke `@orchestrator` if the project has one installed.
