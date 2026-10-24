"""LangGraph StateGraph engine wrapper (uses langgraph.graph when installed, with native async fallback)."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

try:
    from langgraph.graph import END, START, StateGraph  # type: ignore[import-untyped]

    LANGGRAPH_INSTALLED = True
except ImportError:
    LANGGRAPH_INSTALLED = False
    START = "__start__"
    END = "__end__"

    class _CompiledStateGraph:
        """Async state graph executor matching LangGraph's CompiledGraph.ainvoke interface."""

        def __init__(
            self,
            nodes: dict[str, Callable[[Any], Any]],
            edges: dict[str, list[str]],
            conditional_edges: dict[str, tuple[Callable[[Any], str], dict[str, str] | None]],
        ) -> None:
            self._nodes = nodes
            self._edges = edges
            self._conditional_edges = conditional_edges

        async def ainvoke(self, initial_state: dict[str, Any]) -> dict[str, Any]:
            state = dict(initial_state)
            current_targets = self._edges.get(START, [])
            visited_steps = 0
            while current_targets and visited_steps < 50:
                visited_steps += 1
                next_targets: list[str] = []
                for node_name in current_targets:
                    if node_name == END:
                        continue
                    fn = self._nodes[node_name]
                    res = fn(state)
                    if inspect.isawaitable(res):
                        res = await res
                    if isinstance(res, dict):
                        state.update(res)

                    if node_name in self._conditional_edges:
                        cond_fn, mapping = self._conditional_edges[node_name]
                        branch = cond_fn(state)
                        if inspect.isawaitable(branch):
                            branch = await branch
                        target = mapping[branch] if mapping else branch
                        if target != END:
                            next_targets.append(target)
                    else:
                        for dst in self._edges.get(node_name, []):
                            if dst != END:
                                next_targets.append(dst)
                current_targets = next_targets
            return state

    class StateGraph:  # type: ignore[no-redef]
        """Compatible StateGraph builder used when langgraph package is not installed in current Python env."""

        def __init__(self, state_schema: Any) -> None:
            self.state_schema = state_schema
            self._nodes: dict[str, Callable[[Any], Any]] = {}
            self._edges: dict[str, list[str]] = {}
            self._conditional_edges: dict[str, tuple[Callable[[Any], str], dict[str, str] | None]] = {}

        def add_node(self, name: str, action: Callable[[Any], Any]) -> None:
            self._nodes[name] = action

        def add_edge(self, start_key: str, end_key: str) -> None:
            self._edges.setdefault(start_key, []).append(end_key)

        def add_conditional_edges(
            self,
            source: str,
            path: Callable[[Any], str],
            path_map: dict[str, str] | None = None,
        ) -> None:
            self._conditional_edges[source] = (path, path_map)

        def compile(self) -> _CompiledStateGraph:
            return _CompiledStateGraph(self._nodes, self._edges, self._conditional_edges)


__all__ = ["StateGraph", "START", "END", "LANGGRAPH_INSTALLED"]
