"""asyncio DAG executor (spec §6 Scheduler, §8 Error handling)."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Iterable

from engine.config import ConfigError, EngineConfig, Route
from engine.core.cache import compute_fingerprints
from engine.core.executors import cost_params, execute
from engine.core.graph import Manifest, Node
from engine.core.ledger import Ledger
from engine.core.paths import resolve_inputs
from engine.core.store import ProjectStore
from engine.providers.base import (
    ASSEMBLY_TYPES,
    GENERATION_TYPES,
    CallContext,
    Provider,
    ProviderRefusal,
    TransientProviderError,
)

Outcome = tuple[str, str | None, str | None]  # (status, reason, message)

FINISHED = frozenset({"done", "failed", "needs_review", "blocked"})
HELD_EXTERNAL = frozenset({("needs_review", "refused")})  # failed retries; refused holds until revised


@dataclass
class RunReport:
    ran: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    needs_review: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    awaiting: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.failed or self.needs_review or self.blocked or self.awaiting)


class Scheduler:
    def __init__(
        self,
        manifest: Manifest,
        store: ProjectStore,
        config: EngineConfig,
        providers: dict[str, Provider],
        ledger: Ledger,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.manifest = manifest
        self.store = store
        self.config = config
        self.providers = providers
        self.ledger = ledger
        self.sleep = sleep
        self._sems: dict[str, asyncio.Semaphore] = {}

    def _sem(self, provider: str) -> asyncio.Semaphore:
        if provider not in self._sems:
            self._sems[provider] = asyncio.Semaphore(self.config.limit(provider))
        return self._sems[provider]

    async def run(self, targets: Iterable[str] | None = None) -> RunReport:
        m = self.manifest
        self._sems = {}
        fps = compute_fingerprints(m, self.config, self.store.dir, self.store.pins())
        scope = m.scope(targets)
        order = [nid for nid in m.topo_order() if nid in scope]
        report = RunReport()
        status: dict[str, str] = {}

        def block_downstream(nid: str, outcome: str) -> None:
            downstream = m.descendants([nid])
            for d in order:
                if d in downstream and status.get(d) == "pending" and m.nodes[d].type not in ASSEMBLY_TYPES:
                    status[d] = "blocked"
                    self.store.update(d, status="blocked", reason=f"upstream {nid} {outcome}", message=None)
                    report.blocked.append(d)

        stale = self.store.stale_nodes(m, fps, order)
        held: list[str] = []
        for nid in order:
            if nid not in stale:
                status[nid] = "done"
                report.skipped.append(nid)
                if self.store.get(nid).status != "done":
                    self.store.update(nid, status="done", reason=None, message=None)
            elif self._held_external(m.nodes[nid], fps[nid]):
                st = self.store.get(nid)
                status[nid] = st.status
                (report.failed if st.status == "failed" else report.needs_review).append(nid)
                held.append(nid)
            else:
                status[nid] = "pending"
                self.store.update(nid, status="pending", reason=None, message=None)
        for nid in held:
            block_downstream(nid, status[nid])

        running: dict[asyncio.Task, str] = {}

        def ready(nid: str) -> bool:
            node = m.nodes[nid]
            if node.type in ASSEMBLY_TYPES:  # spec §8: assemble with placeholders
                return all(status[d] in FINISHED for d in node.depends_on)
            return all(status[d] == "done" for d in node.depends_on)

        def launch_ready() -> None:
            for nid in order:
                if status[nid] == "pending" and ready(nid):
                    route = self.config.external_route(m.nodes[nid])
                    if route is not None:  # rendered outside the engine; wait for `adengine supply`
                        status[nid] = "awaiting_external"
                        self.store.update(
                            nid, status="awaiting_external", reason="external",
                            message=f"render in {route.provider}, then adengine supply",
                            expected_fingerprint=fps[nid],
                        )
                        report.awaiting.append(nid)
                        continue
                    status[nid] = "running"
                    self.store.update(nid, status="running")
                    running[asyncio.create_task(self._run_node(nid, fps[nid]))] = nid

        launch_ready()
        while running:
            finished, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
            for task in finished:
                nid = running.pop(task)
                exc = task.exception()
                if exc is not None:  # backstop: _run_node should never raise
                    outcome, reason, message = "failed", "error", f"{type(exc).__name__}: {exc}"
                else:
                    outcome, reason, message = task.result()
                status[nid] = outcome
                if outcome == "done":
                    report.ran.append(nid)
                    continue
                self.store.update(nid, status=outcome, reason=reason, message=message)
                (report.failed if outcome == "failed" else report.needs_review).append(nid)
                block_downstream(nid, outcome)
            launch_ready()
        return report

    def _held_external(self, node: Node, fingerprint: str) -> bool:
        """A refusal reported via `adengine supply --refused` stays put until the node changes
        (its fingerprint moves), instead of being re-listed as awaiting. A reported failure
        (`--failed`) is not held: the next run lists the node as awaiting again."""
        st = self.store.get(node.id)
        return (
            (st.status, st.reason) in HELD_EXTERNAL
            and st.expected_fingerprint == fingerprint
            and self.config.external_route(node) is not None
        )

    async def _run_node(self, nid: str, fingerprint: str) -> Outcome:
        node = self.manifest.nodes[nid]
        try:
            route = self.config.route(node)
        except ConfigError as e:
            return ("failed", "config", str(e))
        provider = self.providers.get(route.provider)
        if provider is None:
            return ("failed", "config", f"no provider registered as {route.provider!r}")
        retry = self.config.retry
        try:
            inputs = resolve_inputs(self.manifest, self.store.dir, node)
            sources = (
                {str(self.store.output(self.manifest.nodes[d])): d for d in node.depends_on}
                if node.type in ASSEMBLY_TYPES
                else {}
            )
            for attempt in range(1, retry.max_attempts + 1):
                ctx = CallContext(
                    node_id=nid, model=route.model, work_dir=self.store.work_dir(nid),
                    project_dir=self.store.dir, sources=sources,
                )
                try:
                    async with self._sem(route.provider):
                        started = time.monotonic()
                        produced = await execute(node, provider, ctx, inputs)
                except TransientProviderError as e:
                    self._log(node, route, provider, inputs, started, attempt, ok=False)
                    if attempt == retry.max_attempts:
                        return ("failed", "transient", str(e))
                    await self.sleep(min(retry.base_delay_s * 2 ** (attempt - 1), retry.max_delay_s))
                    continue
                except ProviderRefusal as e:
                    self._log(node, route, provider, inputs, started, attempt, ok=False)
                    return ("needs_review", "refused", str(e))
                except Exception as e:  # hard failure: isolate it to this node
                    self._log(node, route, provider, inputs, started, attempt, ok=False)
                    return ("failed", "error", f"{type(e).__name__}: {e}")
                try:
                    self.store.commit(node, produced, fingerprint)
                except Exception:
                    self._log(node, route, provider, inputs, started, attempt, ok=False)
                    raise
                self._log(node, route, provider, inputs, started, attempt, ok=True)
                return ("done", None, None)
        except Exception as e:  # anything unexpected stays isolated to this node
            return ("failed", "error", f"{type(e).__name__}: {e}")
        raise AssertionError("unreachable")

    def _log(self, node: Node, route: Route, provider: Provider, inputs: dict, started: float, attempt: int, ok: bool) -> None:
        if node.type not in GENERATION_TYPES:
            return
        self.ledger.record(
            node_id=node.id,
            provider=route.provider,
            model=route.model,
            cost_usd=provider.cost(node.type, cost_params(node, inputs)),
            seconds=round(time.monotonic() - started, 3),
            attempt=attempt,
            ok=ok,
        )
