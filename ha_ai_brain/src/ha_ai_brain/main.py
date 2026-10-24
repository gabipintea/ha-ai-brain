"""Entrypoint for HA AI Brain server and interactive prototype runner."""

from __future__ import annotations

import os
import uvicorn


def run() -> None:
    """Start the HA AI Brain FastAPI server (default port 8099 for HA Ingress)."""
    port = int(os.getenv("BRAIN_PORT", "8099"))
    host = os.getenv("BRAIN_HOST", "0.0.0.0")
    uvicorn.run("ha_ai_brain.api.app:create_app", factory=True, host=host, port=port, reload=False)


if __name__ == "__main__":
    run()
