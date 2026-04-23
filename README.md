# Hopewell

**Flow-framework tool for AI-agent-driven work.** Composition-over-typing
node graph, parallel scheduler, orchestrator, GitHub-issues ingestion, and
(soon) a web UI. Tickets and work items are the same thing here: typed
components riding a DAG that agents can execute.

Named after a ship in *Gulliver's Travels*. Work *sails* through a network
of ports (nodes), carrying cargo (artifacts).

> **Status: v0.1–v0.3 (MVP).** CLI + Python library + basic orchestrator
> + GitHub ingestion. Web UI, attestation + agent fingerprinting, and
> LLM-driven graph evolution land in v0.4–v0.6. See **Roadmap** below.

---

## Why this exists

Existing trackers (Jira, Linear, GitHub Projects) are built for humans
clicking. Existing markdown-in-git trackers (`tk`, Backlog.md) are built
for one project, one list. **Hopewell is built for agents and humans to
share the same graph** — every work item is a typed node; every dependency
is an edge; the orchestrator runs ready nodes; the LLM can evolve the graph.

Three principles make it different:

1. **Composition over typing.** A node IS the components it HAS.
   `feature = {work-item, deliverable, user-facing}`. Projects add custom
   components (e.g., `playtest-feedback`) without forking.
2. **Graph-first, not list-first.** The backlog is a DAG. Parallel waves
   are the default; serialization happens when edges force it.
3. **Humans read markdown, agents query the CLI.** `.hopewell/` is
   Claude-ignored. Agents go through `hopewell query ...`; never grep.

---

## Install

```bash
pip install hopewell
# or from source:
git clone https://github.com/ocgully/Hopewell
pip install -e hopewell/

# Optional extras:
pip install 'hopewell[web]'      # FastAPI + SSE (v0.6)
pip install 'hopewell[github]'   # uses `requests` for cleaner HTTP errors
pip install 'hopewell[full]'     # everything
```

Python 3.10+.

---

## Quick start

```bash
cd my-project/
hopewell init                    # scaffolds .hopewell/ + .claudeignore

# Create some nodes
hopewell new --components work-item,deliverable,user-facing \
             --title "Implement login flow" --owner @alice

# List what you've got
hopewell list
hopewell ready                   # just the actionable ones

# Link dependencies
hopewell link HW-0001 blocks HW-0002
hopewell link HW-0002 consumes design/login.figma --from HW-0001

# Check health
hopewell check                   # cycles, dangling refs, schema
hopewell query waves             # who can work in parallel

# Close with evidence
hopewell close HW-0001 --commit abc123 --reason "tests pass, shipped"

# Keep it fresh on every commit
hopewell hooks install
```

## GitHub ingestion

One-way sync: GitHub issues → Hopewell nodes.

```toml
# .hopewell/config.toml
[github]
repo = "ocgully/my-project"
default_components = ["work-item"]
sync_interval_minutes = 60

[github.label_to_components]
bug = "defect"
feature = "user-facing"
security = "risk"
```

Then:

```bash
export GITHUB_TOKEN=ghp_xxxxx
hopewell github sync                       # incremental
hopewell github pull ocgully/foo#42        # one-shot
```

Issues with `closed` state become nodes with `done` status. Re-opened
issues transition back to `doing`. Labels map to components (unknowns
pass silently; still visible in `component_data.github-issue.labels`).

## Orchestrator

```bash
hopewell orch plan               # show wave schedule + critical path
hopewell orch run --dry-run      # preview
hopewell orch run                # execute; ready nodes dispatched to processors
hopewell orch status             # last run summary
```

Built-in processors (v0.3):
- `noop` — marks done. Useful for graph-only nodes.
- `shell-cmd` — runs a command from `component_data.shell-cmd.cmd`.
- `codemap-check` — invokes `codemap check` as a structural gate (needs
  [codemap](https://github.com/ocgully/codemap) installed).

Rich agent-dispatching processors land in v0.4 (they need the attestation
system). Custom Python processors land in v0.7.

---

## Data model (composition-over-typing)

A node is a markdown file with YAML front-matter:

```markdown
---
id: HW-0042
status: ready
priority: P2
owner: "@alice"
components:
  - work-item
  - deliverable
  - user-facing
  - flagged
inputs:
  - from_node: HW-0010
    artifact: specs/042-api/contracts.json
    required: true
outputs:
  - path: src/api/login.ts
    kind: code
blocks: [HW-0050]
blocked_by: [HW-0010]
component_data:
  flagged:
    flag_name: auth.v2
---

# HW-0042: Implement login flow

## Why
...

## Notes (append-only)
- 2026-04-22T19:30Z [@alice]  Started.
```

**18 built-in components**: `work-item`, `deliverable`, `user-facing`,
`internal`, `defect`, `risk`, `debt`, `test`, `documentation`, `screenshot`,
`design`, `code-map`, `grouping`, `deployment-target`, `approval-gate`,
`flagged`, `retriable`, `github-issue`.

Traditional types → component sets:

| Type | Components |
|------|-----------|
| Feature | `work-item, deliverable, user-facing` |
| Bug | `work-item, defect, deliverable` |
| Epic | `grouping, user-facing` |
| Release | `grouping, deployment-target, approval-gate` |
| Test | `work-item, test` |
| ADR | `documentation, design` |
| Imported GH issue | `work-item, github-issue, ...labels` |

Extend by adding YAML to `.hopewell/components/` (v0.7) — no fork needed.

---

## State machine (strict)

```
idea ──► blocked ──► ready ──► doing ──► review ──► done ──► archived
  │         │          │         │          │
  └─────────┴──────────┴─────────┴──────────┴──► cancelled
```

Transitions enforced by the library. Illegal transitions return a typed
error listing what's allowed.

**"Done" semantics depend on the `deployment-target` component**:
- `deployment-target: customer` → done = reached end users
- `deployment-target: internal` → done = merged to main
- No target → `definition_of_done` predicates all green

---

## Hide-from-Claude convention

`hopewell init` writes `.claudeignore` at the project root with
`/.hopewell/` so Claude Code skips the directory during context-gathering.
It also adds a block to your `CLAUDE.md` (if present) telling agents to
use `hopewell query ...` rather than grep.

**For hard enforcement**, add to `.claude/settings.json`:

```json
{
  "permissions": {
    "deny": [
      { "tool": "Read", "path_pattern": "**/.hopewell/**" },
      { "tool": "Grep", "path_pattern": "**/.hopewell/**" },
      { "tool": "Glob", "path_pattern": "**/.hopewell/**" }
    ]
  }
}
```

---

## CLI reference

```
hopewell init [--prefix HW] [--name <name>]
hopewell new --components c1,c2,... --title "..." [--owner @x] [--parent HW-N]
hopewell show <id> [--format text|json]
hopewell list [--status S] [--component C] [--has-all A,B] [--owner @x]
hopewell ready [--owner @x]
hopewell touch <id> --note "..."
hopewell link <from> {blocks|produces|consumes|parent|related} <to> [--artifact <p>]
hopewell close <id> [--commit <sha>] [--reason "..."]
hopewell check
hopewell graph                   # mermaid source
hopewell render                  # regenerate .hopewell/views/*
hopewell info                    # JSON summary

hopewell query ready | deps <id> [--transitive] | waves | critical-path
            | component <name> | metrics [--by component|status|owner] | graph | show <id>

hopewell orch {plan|run|status} [--dry-run] [--max N]

hopewell github {sync|pull|config} [ref] [--since <ts>] [--state open|closed|all]

hopewell hooks {install|uninstall}
```

`hw` is an alias for `hopewell`.

---

## Python library

```python
from hopewell import Project, NodeStatus
from hopewell.query import ready, deps, waves, metrics
from hopewell.orchestrator import Runner
from hopewell.github import sync_from_github

project = Project.load(".")                 # walks up to find .hopewell/

# Query
for n in ready(project)["nodes"]:
    print(n["id"], n["title"])

# Mutate
project.touch("HW-0042", "Reviewed; merging.", actor="@alice")

# Orchestrate
Runner(project).execute(max_parallel=4)

# Sync
sync_from_github(project)
```

The CLI is argparse over this library — everything the CLI does, your
scripts can do without shelling out.

---

## Roadmap

| Version | Contents |
|---------|----------|
| **v0.1** | Foundations: model, storage, CLI (init/new/show/list/touch/link/close/check/graph/render), library, hooks, .claudeignore |
| **v0.2** | Query + Scheduler: ready/deps/waves/critical-path/metrics |
| **v0.3** | Orchestrator basic + **GitHub ingestion** |
| v0.4 | Attestation + agent fingerprinting; agent-dispatch processor |
| v0.5 | LLM-driven graph evolution (`hopewell evolve ...`), loops |
| v0.6 | Web UI (FastAPI + SSE + zero-build tree/canvas/timeline) |
| v0.7 | Custom Python processors + YAML component loader |
| v0.8 | Replace SpecKit planning artefacts |

---

## Relationship to other tools

- **[codemap](https://github.com/ocgully/codemap)** — structural view of
  code. Hopewell's `code-map` component cites codemap queries
  (e.g., `codemap check`) as acceptance gates.
- **[AgentFactory](https://github.com/ocgully/agentfactory)** — marketplaces
  + patterns + bootstrap. AgentFactory consumes Hopewell; `/bootstrap-from-roadmap`
  installs it as part of onboarding.
- **SpecKit `specs/{NNN}/`** — feature-design artefacts. In v0.8 Hopewell
  nodes with `design` + `documentation` + `grouping` components replace
  the SpecKit directory structure; until then, Hopewell references them.

---

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
