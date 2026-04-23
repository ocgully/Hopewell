"""Default flow-network template (HW-0027).

Installed by `hopewell network defaults bootstrap`. A starting point for a
typical Hopewell-consuming repo: inbox -> planner -> architect -> engineers
(+ writer + QA) -> code review -> main -> CI -> UAT -> prod -> archive.

Back-edges are intentional (failure loops). Projects are expected to edit.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from hopewell.executor import Executor, Route


def default_template() -> Tuple[List[Executor], List[Route]]:
    executors: List[Executor] = [
        # --- sources ---
        Executor(
            id="inbox",
            label="Inbox",
            components=["source"],
            component_data={"source": {"source_kind": "inbox"}},
        ),

        # --- agents (each with its own queue buffer) ---
        Executor(
            id="@planner",
            label="Planner",
            components=["agent", "queue"],
            component_data={
                "agent": {"agent_id": "@planner", "kind": "llm",
                          "role": "triage + scope"},
            },
        ),
        Executor(
            id="@architect",
            label="Architect",
            components=["agent", "queue"],
            component_data={
                "agent": {"agent_id": "@architect", "kind": "llm",
                          "role": "design + decomposition"},
            },
        ),
        Executor(
            id="@engineer",
            label="Engineer",
            components=["agent", "queue"],
            component_data={
                "agent": {"agent_id": "@engineer", "kind": "llm",
                          "role": "implementation"},
            },
        ),
        Executor(
            id="@technical-writer",
            label="Technical Writer",
            components=["agent", "queue"],
            component_data={
                "agent": {"agent_id": "@technical-writer", "kind": "llm",
                          "role": "user-facing docs"},
            },
        ),
        Executor(
            id="@testing-qa",
            label="Testing / QA",
            components=["agent", "queue"],
            component_data={
                "agent": {"agent_id": "@testing-qa", "kind": "llm",
                          "role": "test authorship + manual QA"},
            },
        ),

        # --- services (some double as gates) ---
        Executor(
            id="code-review",
            label="Code Review",
            components=["service", "gate"],
            component_data={
                "service": {"service_kind": "code-review"},
                "gate": {"predicate_kind": "review-pass"},
            },
        ),
        Executor(
            id="github-main",
            label="GitHub main",
            components=["service"],
            component_data={
                "service": {"service_kind": "github", "endpoint": "main"},
            },
        ),
        Executor(
            id="ci-pipeline",
            label="CI Pipeline",
            components=["service", "gate"],
            component_data={
                "service": {"service_kind": "ci"},
                "gate": {"predicate_kind": "ci-green"},
            },
        ),

        # --- gates ---
        Executor(
            id="uat-gate",
            label="UAT Gate",
            components=["gate"],
            component_data={"gate": {"predicate_kind": "uat-status"}},
        ),

        # --- targets ---
        Executor(
            id="prod-deploy",
            label="Production",
            components=["target"],
            component_data={"target": {"target_kind": "customer",
                                       "deployment_env": "prod"}},
        ),
        Executor(
            id="archived",
            label="Archive",
            components=["target"],
            component_data={"target": {"target_kind": "archived"}},
        ),
    ]

    routes: List[Route] = [
        Route("inbox", "@planner", required=True),
        Route("@planner", "@architect", required=True),
        Route("@architect", "@engineer", required=True),
        Route("@architect", "@technical-writer"),
        Route("@architect", "@testing-qa"),
        Route("@engineer", "code-review", required=True),
        Route("@technical-writer", "code-review"),
        Route("@testing-qa", "code-review"),
        Route("code-review", "github-main", condition="on_pass", required=True),
        Route("code-review", "@engineer", condition="on_fail", label="rework"),
        Route("github-main", "ci-pipeline", required=True),
        Route("ci-pipeline", "uat-gate", condition="on_pass", required=True),
        Route("ci-pipeline", "@engineer", condition="on_fail", label="fix"),
        Route("uat-gate", "prod-deploy", condition="on_pass", required=True),
        Route("uat-gate", "@engineer", condition="on_fail", label="rework"),
        Route("prod-deploy", "archived", required=True),
    ]

    return executors, routes


def write_default_template(project_root) -> Dict[str, int]:
    """Install the default template under `.hopewell/network/`.

    Idempotent in a sense: adding an executor that already exists is
    rewritten (overwrite=True) so re-bootstrapping brings divergent
    projects back to baseline. Existing routes are preserved — we only
    ADD the template's routes (so human-added routes survive).
    """
    from pathlib import Path
    from hopewell import network as net_mod

    root = Path(project_root)
    net_mod.ensure_network_dir(root)
    executors, routes = default_template()
    for ex in executors:
        net_mod.add_executor(root, ex, overwrite=True)
    # Dedup against existing routes so re-bootstrap is idempotent.
    existing = {r.key() for r in net_mod.load_network(root).routes}
    added = 0
    for r in routes:
        if r.key() in existing:
            continue
        net_mod.add_route(root, r)
        added += 1
    return {"executors": len(executors), "routes_added": added,
            "routes_in_template": len(routes)}
