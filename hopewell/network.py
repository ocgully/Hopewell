"""Flow-network storage + validation (HW-0027).

Layout on disk, rooted at `.hopewell/network/`:

    executors/<id>.json          one file per executor
    routes.jsonl                 append-only routes log (merge-driver-friendly)
    components/*.json            project-custom executor components (optional)

Semantics:
* Executors are full JSON documents (full rewrite on every mutation).
  Append-only doesn't fit — an executor's component set mutates.
* Routes are append-only records with a soft tombstone: removal appends
  `{"tombstone": true, "from": ..., "to": ..., "condition": ...}`, and
  the loader filters tombstoned keys when building the live view.
* Cycles are legal in the flow graph (review loops). `validate` does NOT
  reject cycles — it only flags unreachable executors, unknown
  components, dangling route endpoints, and dead-end non-target
  executors.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from hopewell.executor import (
    Executor,
    ExecutorComponent,
    ExecutorComponentRegistry,
    Route,
    read_executor_file,
    validate_executor_id,
    write_executor_file,
    _now,
)
from hopewell.executor_components import BUILTIN_EXECUTOR_COMPONENTS


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def network_dir(project_root: Path) -> Path:
    return project_root / ".hopewell" / "network"


def executors_dir(project_root: Path) -> Path:
    return network_dir(project_root) / "executors"


def routes_path(project_root: Path) -> Path:
    return network_dir(project_root) / "routes.jsonl"


def components_dir(project_root: Path) -> Path:
    return network_dir(project_root) / "components"


def ensure_network_dir(project_root: Path) -> Path:
    d = network_dir(project_root)
    d.mkdir(parents=True, exist_ok=True)
    executors_dir(project_root).mkdir(parents=True, exist_ok=True)
    components_dir(project_root).mkdir(parents=True, exist_ok=True)
    rp = routes_path(project_root)
    if not rp.is_file():
        rp.write_text("", encoding="utf-8")
    return d


# ---------------------------------------------------------------------------
# .gitattributes — own managed block so we don't touch project.py's
# ---------------------------------------------------------------------------


_GITATTR_LINES = [
    ".hopewell/network/routes.jsonl  merge=hopewell-jsonl",
]
_GITATTR_MARKER = "# --- hopewell network jsonl merge driver (managed) ---"
_GITATTR_END = "# --- /hopewell network jsonl merge driver ---"


def install_gitattributes(project_root: Path) -> bool:
    """Ensure `routes.jsonl` gets the hopewell-jsonl merge driver.

    Idempotent. Writes its own managed block, distinct from the v0.5
    block in `project.py`, so nothing else in the project is touched.
    The merge driver itself is installed by `hopewell init`; we rely
    on that config being present.

    Returns True if the block was (re)written.
    """
    gitattr = project_root / ".gitattributes"
    existing = gitattr.read_text(encoding="utf-8") if gitattr.is_file() else ""
    if _GITATTR_MARKER in existing:
        return False
    block = (
        ("\n" if existing and not existing.endswith("\n") else "")
        + f"{_GITATTR_MARKER}\n"
        + "\n".join(_GITATTR_LINES) + "\n"
        + f"{_GITATTR_END}\n"
    )
    gitattr.write_text(existing + block, encoding="utf-8")

    # Best-effort: ensure driver config is set (normally done by
    # `hopewell init`, but `network init` may be the first entry point).
    if (project_root / ".git").exists():
        try:
            subprocess.run(
                ["git", "config", "merge.hopewell-jsonl.driver",
                 "hopewell merge-driver jsonl %O %A %B"],
                cwd=str(project_root), check=True, capture_output=True, timeout=10,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            pass
    return True


# ---------------------------------------------------------------------------
# Registry loader — built-ins + project-custom JSON
# ---------------------------------------------------------------------------


def default_executor_registry() -> ExecutorComponentRegistry:
    reg = ExecutorComponentRegistry()
    for c in BUILTIN_EXECUTOR_COMPONENTS:
        reg.register(c)
    return reg


def load_registry(project_root: Path) -> Tuple[ExecutorComponentRegistry, List[Dict[str, str]]]:
    """Built-ins + project-custom JSON components. Returns (registry, errors)."""
    reg = default_executor_registry()
    errors: List[Dict[str, str]] = []
    cdir = components_dir(project_root)
    if not cdir.is_dir():
        return reg, errors
    for path in sorted(cdir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError(f"top-level of {path.name} must be an object")
            name = data.get("name")
            if not isinstance(name, str) or not name:
                raise ValueError(f"{path.name}: missing string `name`")
            schema = data.get("schema", {}) or {}
            if not isinstance(schema, dict):
                raise ValueError(f"{path.name}: `schema` must be an object")
            req = data.get("required_fields", []) or []
            if not isinstance(req, list):
                raise ValueError(f"{path.name}: `required_fields` must be a list")
            reg.register(ExecutorComponent(
                name=name,
                description=str(data.get("description", "") or ""),
                schema=schema,
                required_fields=[str(x) for x in req],
            ))
        except Exception as e:  # noqa: BLE001 — surface every bad file
            errors.append({
                "file": str(path),
                "error": f"{type(e).__name__}: {e}",
            })
    return reg, errors


# ---------------------------------------------------------------------------
# Network — loaded view
# ---------------------------------------------------------------------------


@dataclass
class Network:
    executors: Dict[str, Executor] = field(default_factory=dict)
    routes: List[Route] = field(default_factory=list)
    registry: ExecutorComponentRegistry = field(default_factory=default_executor_registry)
    registry_errors: List[Dict[str, str]] = field(default_factory=list)

    # ---- lookups ----
    def get(self, eid: str) -> Optional[Executor]:
        return self.executors.get(eid)

    def routes_from(self, eid: str) -> List[Route]:
        return [r for r in self.routes if r.from_id == eid]

    def routes_to(self, eid: str) -> List[Route]:
        return [r for r in self.routes if r.to_id == eid]

    def children_of(self, gid: str) -> List[Executor]:
        return [e for e in self.executors.values() if e.parent == gid]


def load_network(project_root: Path) -> Network:
    registry, reg_errors = load_registry(project_root)
    net = Network(registry=registry, registry_errors=reg_errors)

    edir = executors_dir(project_root)
    if edir.is_dir():
        for path in sorted(edir.glob("*.json")):
            try:
                ex = read_executor_file(path)
            except Exception:  # noqa: BLE001
                continue
            net.executors[ex.id] = ex

    rpath = routes_path(project_root)
    if rpath.is_file():
        # Apply tombstones: a tombstone removes any prior route with the
        # same key. Last line wins.
        live: Dict[str, Route] = {}
        for line in rpath.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = f"{rec.get('from','')}|{rec.get('to','')}|{rec.get('condition','') or ''}"
            if rec.get("tombstone"):
                live.pop(key, None)
                continue
            try:
                live[key] = Route.from_dict(rec)
            except Exception:  # noqa: BLE001
                continue
        net.routes = list(live.values())
    return net


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


def add_executor(project_root: Path, executor: Executor, *, overwrite: bool = False) -> Path:
    validate_executor_id(executor.id)
    ensure_network_dir(project_root)
    path = executors_dir(project_root) / f"{_safe_filename(executor.id)}.json"
    if path.is_file() and not overwrite:
        raise FileExistsError(f"executor {executor.id!r} already exists at {path}")
    write_executor_file(path, executor)
    return path


def remove_executor(project_root: Path, eid: str) -> bool:
    path = executors_dir(project_root) / f"{_safe_filename(eid)}.json"
    if not path.is_file():
        return False
    path.unlink()
    # Also tombstone routes touching this executor so loads stay clean.
    net = load_network(project_root)
    for r in list(net.routes):
        if r.from_id == eid or r.to_id == eid:
            _append_route_record(project_root, {
                "tombstone": True,
                "from": r.from_id, "to": r.to_id,
                "condition": r.condition or "",
                "ts": _now(),
            })
    return True


def add_route(project_root: Path, route: Route) -> None:
    ensure_network_dir(project_root)
    _append_route_record(project_root, route.to_dict())


def remove_route(project_root: Path, from_id: str, to_id: str,
                 condition: Optional[str] = None) -> None:
    ensure_network_dir(project_root)
    _append_route_record(project_root, {
        "tombstone": True,
        "from": from_id, "to": to_id,
        "condition": condition or "",
        "ts": _now(),
    })


def _append_route_record(project_root: Path, rec: Dict[str, Any]) -> None:
    rp = routes_path(project_root)
    rp.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(rec, sort_keys=True, ensure_ascii=False)
    with rp.open("a", encoding="utf-8", newline="\n") as f:
        f.write(line + "\n")


def _safe_filename(eid: str) -> str:
    """@planner -> at-planner (keep filesystem happy)."""
    return eid.replace("@", "at-").replace("/", "-")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate(net: Network) -> List[str]:
    """Return a list of problem strings. Empty = clean.

    Rules implemented:
      1. Unknown executor components (per registry).
      2. Required-field violations on component_data.
      3. Route endpoints must exist.
      4. Dangling parent pointers (group nesting).
      5. Unreachable executors (no source can reach them).
      6. Dead ends — non-target, non-group executors with no outgoing routes.
      7. Registry load errors (bad JSON component files).

    Deferred (by design):
      * Cycle detection — cycles are legal (review loops).
      * Schema-type enforcement beyond required_fields — kept permissive
        to match the WorkItem component model.
      * Duplicate ids — impossible here because each id is one file.
    """
    problems: List[str] = []

    for e in net.registry_errors:
        problems.append(f"component load error: {e.get('file','?')}: {e.get('error','?')}")

    # 1 + 2 — component validity
    for ex in net.executors.values():
        unknown = net.registry.validate_executor_components(ex.components)
        problems.extend(f"executor {ex.id!r}: {u}" for u in unknown)
        for comp_name, data in (ex.component_data or {}).items():
            if comp_name not in ex.components:
                problems.append(
                    f"executor {ex.id!r}: component_data for "
                    f"{comp_name!r} but component not declared"
                )
                continue
            comp = net.registry.get(comp_name)
            if comp is None:
                continue
            for err in comp.validate_data(data or {}):
                problems.append(f"executor {ex.id!r}: {err}")

    # 3 — route endpoints exist
    known = set(net.executors.keys())
    for r in net.routes:
        if r.from_id not in known:
            problems.append(f"route {r.from_id}->{r.to_id}: unknown `from`")
        if r.to_id not in known:
            problems.append(f"route {r.from_id}->{r.to_id}: unknown `to`")

    # 4 — parents exist + are groups
    for ex in net.executors.values():
        if ex.parent and ex.parent not in known:
            problems.append(f"executor {ex.id!r}: unknown parent {ex.parent!r}")
            continue
        if ex.parent:
            parent_ex = net.executors.get(ex.parent)
            if parent_ex is not None and not parent_ex.has_component("group"):
                problems.append(
                    f"executor {ex.id!r}: parent {ex.parent!r} is not a `group` "
                    f"executor"
                )

    # 5 — reachability from any source
    sources = [ex.id for ex in net.executors.values() if ex.has_component("source")]
    if sources:
        reachable: Set[str] = set()
        stack = list(sources)
        adj: Dict[str, List[str]] = {}
        for r in net.routes:
            adj.setdefault(r.from_id, []).append(r.to_id)
        while stack:
            cur = stack.pop()
            if cur in reachable:
                continue
            reachable.add(cur)
            for nxt in adj.get(cur, []):
                if nxt not in reachable:
                    stack.append(nxt)
        for ex in net.executors.values():
            # Skip groups — they're structural, not in the flow graph.
            if ex.has_component("group"):
                continue
            # Sources are trivially reachable (they're roots).
            if ex.has_component("source"):
                continue
            if ex.id not in reachable:
                problems.append(f"executor {ex.id!r}: unreachable from any source")

    # 6 — dead ends (no outgoing routes where we'd expect one).
    # Exempt: targets (terminal by design), groups (structural), gates
    # (routing is driven by on_pass/on_fail component_data — may be
    # declarative without explicit routes yet).
    has_out: Set[str] = {r.from_id for r in net.routes}
    for ex in net.executors.values():
        if ex.has_any(["target", "group", "gate"]):
            continue
        if ex.id not in has_out:
            problems.append(
                f"executor {ex.id!r}: dead end (no outgoing routes and not a target)"
            )

    return problems


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def to_mermaid(net: Network) -> str:
    """Flowchart. Groups render as subgraphs."""
    lines: List[str] = ["flowchart LR"]

    def _label(ex: Executor) -> str:
        comps = ",".join(ex.components) if ex.components else "-"
        disp = ex.label or ex.id
        return f'{_mid(ex.id)}["{disp}<br/>({comps})"]'

    top_level = [ex for ex in net.executors.values() if not ex.parent]
    rendered: Set[str] = set()

    def emit(ex: Executor, indent: str = "  ") -> None:
        if ex.has_component("group"):
            lines.append(f'{indent}subgraph {_mid(ex.id)}["{ex.label or ex.id}"]')
            for child in sorted(_that_group_children(ex), key=lambda c: c.id):
                emit(child, indent + "  ")
            lines.append(f"{indent}end")
        else:
            lines.append(f"{indent}{_label(ex)}")
        rendered.add(ex.id)

    def _that_group_children(group: Executor) -> List[Executor]:
        return [e for e in net.executors.values() if e.parent == group.id]

    for ex in sorted(top_level, key=lambda e: e.id):
        emit(ex)

    # Defensive fallback for executors with missing parents
    for ex in sorted(net.executors.values(), key=lambda e: e.id):
        if ex.id not in rendered:
            lines.append(f"  {_label(ex)}")
            rendered.add(ex.id)

    for r in sorted(net.routes, key=lambda r: (r.from_id, r.to_id, r.condition or "")):
        arrow = "==>" if r.required else "-->"
        anno_text = r.condition or r.label
        if anno_text:
            lines.append(
                f"  {_mid(r.from_id)} {arrow}|{anno_text}| {_mid(r.to_id)}"
            )
        else:
            lines.append(f"  {_mid(r.from_id)} {arrow} {_mid(r.to_id)}")
    return "\n".join(lines) + "\n"


def _mid(eid: str) -> str:
    """mermaid-safe node id."""
    out = []
    for ch in eid:
        if ch.isalnum() or ch == "_":
            out.append(ch)
        else:
            out.append("_")
    s = "".join(out)
    # Mermaid ids can't start with a digit; prefix underscore if so.
    if s and s[0].isdigit():
        s = "_" + s
    return s or "_"


def to_json(net: Network) -> Dict[str, Any]:
    return {
        "executors": [ex.to_dict() for ex in sorted(net.executors.values(), key=lambda e: e.id)],
        "routes": [r.to_dict() for r in sorted(net.routes, key=lambda r: (r.from_id, r.to_id, r.condition or ""))],
    }
