"""Persistent Memory Gateway: a small, model-agnostic memory layer for AI tools."""

__version__ = "0.2.0"

from .store import Memory  # noqa: E402,F401

__all__ = ["Memory", "__version__"]
