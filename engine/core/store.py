"""Per-project run state (state.json), versioned outputs, rollback."""
from __future__ import annotations

import fcntl
import json
import os
import shutil
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Iterator, Iterable

from engine.core.cache import pinned_fingerprint
from engine.core.graph import Manifest, Node
from engine.core.jsonio import write_json_atomic
from engine.core.paths import output_path, version_path


@dataclass
class NodeState:
    status: str = "pending"
    version: int = 0
    fingerprint: str | None = None
    reason: str | None = None
    message: str | None = None
    pinned_version: int | None = None
    built_from: dict[str, int] | None = None  # dependency versions at commit; None in old state files
    expected_fingerprint: str | None = None  # set while awaiting_external (spec: ellora §3.3)
    external: dict | None = None             # {"provider", "ref", "id"} of the current version, if supplied
    external_history: dict[str, dict] | None = None  # str(version) → external metadata, for rollback


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


class ProjectStore:
    """state.json may be written by several processes at once (parallel `adengine supply`,
    a supply during a run). Every save merges: under an exclusive lock it re-reads the file,
    writes back only the nodes this store changed since its last save, and refreshes the
    rest from disk."""

    def __init__(self, project_dir: Path):
        self.dir = Path(project_dir).resolve()
        self.state_path = self.dir / "state.json"
        self.lock_path = self.dir / ".state.lock"
        self.nodes: dict[str, NodeState] = self._read()
        self._dirty: set[str] = set()
        self._lock_depth = 0
        self._lock_fd: int | None = None

    def _read(self) -> dict[str, NodeState]:
        if not self.state_path.exists():
            return {}
        data = json.loads(self.state_path.read_text())
        return {k: NodeState(**v) for k, v in data.get("nodes", {}).items()}

    def _refresh(self) -> None:
        """Take every node this store has not changed from disk, in place, so
        NodeState objects already handed out stay current."""
        for k, disk in self._read().items():
            if k in self._dirty:
                continue
            mine = self.nodes.get(k)
            if mine is None:
                self.nodes[k] = disk
            else:
                for f in dataclass_fields(NodeState):
                    setattr(mine, f.name, getattr(disk, f.name))

    @contextmanager
    def lock(self) -> Iterator[None]:
        """Exclusive lock on the project's state across processes. Re-entrant within this
        store. Taking it refreshes untouched nodes, so checks made inside see current state."""
        if self._lock_depth == 0:
            self.dir.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
            except BaseException:
                os.close(fd)
                raise
            self._lock_fd = fd
        self._lock_depth += 1
        try:
            if self._lock_depth == 1:
                self._refresh()
            yield
        finally:
            self._lock_depth -= 1
            if self._lock_depth == 0 and self._lock_fd is not None:
                fd, self._lock_fd = self._lock_fd, None
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def save(self) -> None:
        with self.lock():
            nodes = {k: asdict(v) for k, v in self.nodes.items()}
            write_json_atomic(self.state_path, {"nodes": nodes})
            self._dirty.clear()

    def get(self, node_id: str) -> NodeState:
        return self.nodes.setdefault(node_id, NodeState())

    def _touch(self, node_id: str) -> NodeState:
        """The node's state, marked as changed by this store (written on the next save).
        Call with lock() held, so the node was refreshed from disk before it is marked."""
        self._dirty.add(node_id)
        return self.get(node_id)

    def update(self, node_id: str, **fields) -> None:
        with self.lock():  # refresh first, then mark dirty: only these fields override disk
            st = self._touch(node_id)
            for key, value in fields.items():
                setattr(st, key, value)
            self.save()

    def output(self, node: Node) -> Path:
        return output_path(self.dir, node.id, node.type)

    def is_fresh(self, node: Node, fingerprint: str) -> bool:
        st = self.nodes.get(node.id)
        return st is not None and st.fingerprint == fingerprint and self.output(node).exists()

    def stale_nodes(self, manifest: Manifest, fingerprints: dict[str, str], order: Iterable[str]) -> set[str]:
        """The freshness rule, shared by run and dry-run. `order` must be topological.
        A node is stale unless its fingerprint matches, its output exists, no
        dependency is stale, and every dependency is still at the version it was
        built from. Pinned (rolled-back) nodes only need fingerprint + output."""
        pins = self.pins()
        stale: set[str] = set()
        for nid in order:
            node = manifest.nodes[nid]
            fresh = self.is_fresh(node, fingerprints[nid])
            if fresh and nid not in pins:
                built_from = self.nodes[nid].built_from
                fresh = not any(d in stale for d in node.depends_on) and (
                    built_from is None
                    or all(built_from.get(d) == self._version(d) for d in node.depends_on)
                )
            if not fresh:
                stale.add(nid)
        return stale

    def _version(self, node_id: str) -> int:
        st = self.nodes.get(node_id)
        return st.version if st else 0

    def commit(
        self, node: Node, produced: Path, fingerprint: str | None = None, *,
        pin: bool = False, external: dict | None = None,
    ) -> int:
        """Archive the current output (if any) to versions/, move `produced` into place.
        An existing archive is never overwritten, even if state.json was lost.
        pin=True (rollback) pins the new version and gives it the pinned fingerprint.
        external: provider metadata of a file rendered outside the engine; recorded for the
        new version in the same save, so the node is never done without it."""
        if fingerprint is None and not pin:
            raise ValueError("commit needs a fingerprint unless pin=True")
        produced = Path(produced)
        if not produced.exists():
            raise FileNotFoundError(f"{node.id}: provider output {produced} does not exist")
        with self.lock():  # current versions of this node and its dependencies
            out = self.output(node)
            st = self._touch(node.id)
            archived = self.versions(node)
            top = max([st.version, *archived])
            if out.exists():
                n = max(st.version, max(archived, default=0) + 1)
                target = version_path(out, node.id, n)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(out), str(target))
                top = n
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(produced), str(out))
            st.version = top + 1
            st.status = "done"
            st.built_from = {d: self._version(d) for d in node.depends_on}
            if pin:
                st.fingerprint = pinned_fingerprint(node.id, st.version)
                st.pinned_version = st.version
            else:
                st.fingerprint = fingerprint
            st.reason = None
            st.expected_fingerprint = None
            st.external = external
            if external is not None:
                st.external_history = {**(st.external_history or {}), str(st.version): external}
            st.message = None
            self.save()
            return st.version

    def versions(self, node: Node) -> list[int]:
        out = self.output(node)
        vdir = out.parent / "versions"
        if not vdir.exists():
            return []
        prefix, suffix = f"{node.id}_v", out.suffix
        nums: list[int] = []
        for p in vdir.iterdir():
            name = p.name
            if suffix:
                if not name.endswith(suffix):
                    continue
                name = name[: -len(suffix)]
            tail = name[len(prefix):]
            if name.startswith(prefix) and tail.isdigit():
                nums.append(int(tail))
        return sorted(nums)

    def rollback(self, node: Node, version: int) -> int:
        """Restore versions/<id>_v<version> as a new current version and pin it, so
        re-runs keep it until the node is revised. Dependents rebuild against it."""
        out = self.output(node)
        src = version_path(out, node.id, version)
        if not src.exists():
            raise ValueError(f"{node.id} has no version {version} (archived: {self.versions(node)})")
        with self.lock():
            staged = self.work_dir(node.id) / f"rollback{out.suffix}"
            if src.is_dir():
                shutil.copytree(src, staged)
            else:
                shutil.copy2(src, staged)
            # a supplied file: later external nodes need its provider-side ref
            ext = (self.get(node.id).external_history or {}).get(str(version))
            return self.commit(node, staged, pin=True, external=ext)

    def pins(self) -> dict[str, int]:
        return {k: v.pinned_version for k, v in self.nodes.items() if v.pinned_version is not None}

    def unpin(self, node_id: str) -> None:
        with self.lock():  # decide on the current pin, not the one this store loaded
            if node_id in self.nodes and self.nodes[node_id].pinned_version is not None:
                self.update(node_id, pinned_version=None)

    def work_dir(self, node_id: str) -> Path:
        d = self.dir / ".tmp" / node_id
        _remove(d)
        d.mkdir(parents=True)
        return d
