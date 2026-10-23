"""Port Interface for the Computation Sub-Agent's Python Execution Sandbox."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ComputationSandboxPort(ABC):
    """Executes isolated Python code to compute derived physical/statistical signals."""

    @abstractmethod
    async def execute_python(
        self,
        code: str,
        input_variables: dict[str, Any],
        timeout_seconds: float = 5.0,
    ) -> dict[str, Any]:
        """
        Execute Python computation code with `input_variables` injected as `inputs`.
        The script populates a `results` dictionary which is returned to the caller.
        """
