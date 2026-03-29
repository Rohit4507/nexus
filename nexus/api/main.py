"""Re-export app for uvicorn: `uvicorn nexus.api.main:app`"""

from nexus.api import app

__all__ = ["app"]
