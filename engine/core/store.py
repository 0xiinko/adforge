"""Per-project run state (state.json), versioned outputs, rollback."""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from engine.core.cache import pinned_fingerprint
from engine.core.graph import Node
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


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


class ProjectStore:
    def __init__(self, project_dir: Path):
        self.dir = Path(project_dir)
        self.state_path = self.dir / "state.json"
        self.nodes: dict[str, NodeState] = {}
        if self.state_path.exists():
            data = json.loads(self.state_path.read_text())
            self.nodes = {k: NodeState(**v) for k, v in data.get("nodes", {}).items()}

    def save(self) -> None:
        write_json_atomic(self.state_path, {"nodes": {k: asdict(v) for k, v in self.nodes.items()}})

    def get(self, node_id: str) -> NodeState:
        return self.nodes.setdefault(node_id, NodeState())

    def update(self, node_id: str, **fields) -> None:
        st = self.get(node_id)
        for key, value in fields.items():
            setattr(st, key, value)
        self.save()

    def output(self, node: Node) -> Path:
        return output_path(self.dir, node.id, node.type)

    def is_fresh(self, node: Node, fingerprint: str) -> bool:
        st = self.nodes.get(node.id)
        return st is not None and st.fingerprint == fingerprint and self.output(node).exists()

    def commit(self, node: Node, produced: Path, fingerprint: str) -> int:
        """Archive the current output (if any) to versions/, move `produced` into place."""
        out = self.output(node)
        st = self.get(node.id)
        if out.exists():
            archived = version_path(out, node.id, st.version)
            archived.parent.mkdir(parents=True, exist_ok=True)
            _remove(archived)
            shutil.move(str(out), str(archived))
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(produced), str(out))
        st.version += 1
        st.status = "done"
        st.fingerprint = fingerprint
        st.reason = None
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
        staged = self.work_dir(node.id) / f"rollback{out.suffix}"
        if src.is_dir():
            shutil.copytree(src, staged)
        else:
            shutil.copy2(src, staged)
        new_version = self.get(node.id).version + 1
        self.commit(node, staged, pinned_fingerprint(node.id, new_version))
        self.update(node.id, pinned_version=new_version)
        return new_version

    def pins(self) -> dict[str, int]:
        return {k: v.pinned_version for k, v in self.nodes.items() if v.pinned_version is not None}

    def unpin(self, node_id: str) -> None:
        if node_id in self.nodes and self.nodes[node_id].pinned_version is not None:
            self.update(node_id, pinned_version=None)

    def work_dir(self, node_id: str) -> Path:
        d = self.dir / ".tmp" / node_id
        _remove(d)
        d.mkdir(parents=True)
        return d
