"""MAS production entrypoint.

Keep this module intentionally boring: FastAPI must see the exact same dependency
graph in development, tests and production. Runtime monkey-patching here caused
Pydantic/FastAPI dependency-inspection failures.
"""

from mas_app.main import app

__all__ = ["app"]
