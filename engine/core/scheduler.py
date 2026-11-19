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
    GENERATION_TYPES,
    CallContext,
    Provider,
    ProviderRefusal,
    TransientProviderError,
)

Outcome = tuple[str, str | None, str | None]  # (status, reason, message)


@dataclass
class RunReport:
    ran: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    needs_review: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.failed or self.needs_review or self.blocked)


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

        for nid in order:
            if self.store.is_fresh(m.nodes[nid], fps[nid]):
                status[nid] = "done"
                report.skipped.append(nid)
                if self.store.get(nid).status != "done":
                    self.store.update(nid, status="done", reason=None, message=None)
            else:
                status[nid] = "pending"
                self.store.update(nid, status="pending", reason=None, message=None)

        running: dict[asyncio.Task, str] = {}

        def launch_ready() -> None:
            for nid in order:
                if status[nid] == "pending" and all(status[d] == "done" for d in m.nodes[nid].depends_on):
                    status[nid] = "running"
                    self.store.update(nid, status="running")
                    running[asyncio.create_task(self._run_node(nid, fps[nid]))] = nid

        launch_ready()
        while running:
            finished, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
            for task in finished:
                nid = running.pop(task)
                outcome, reason, message = task.result()
                status[nid] = outcome
                if outcome == "done":
                    report.ran.append(nid)
                    continue
                self.store.update(nid, status=outcome, reason=reason, message=message)
                (report.failed if outcome == "failed" else report.needs_review).append(nid)
                downstream = m.descendants([nid])
                for d in order:
                    if d in downstream and status[d] == "pending":
                        status[d] = "blocked"
                        self.store.update(d, status="blocked", reason=f"upstream {nid} {outcome}", message=None)
                        report.blocked.append(d)
            launch_ready()
        return report

    async def _run_node(self, nid: str, fingerprint: str) -> Outcome:
        node = self.manifest.nodes[nid]
        try:
            route = self.config.route(node)
            provider = self.providers[route.provider]
        except ConfigError as e:
            return ("failed", "config", str(e))
        except KeyError:
            return ("failed", "config", f"no provider registered as {route.provider!r}")
        inputs = resolve_inputs(self.manifest, self.store.dir, node)
        retry = self.config.retry
        for attempt in range(1, retry.max_attempts + 1):
            ctx = CallContext(node_id=nid, model=route.model, work_dir=self.store.work_dir(nid))
            started = time.monotonic()
            try:
                async with self._sem(route.provider):
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
            self._log(node, route, provider, inputs, started, attempt, ok=True)
            self.store.commit(node, produced, fingerprint)
            return ("done", None, None)
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
