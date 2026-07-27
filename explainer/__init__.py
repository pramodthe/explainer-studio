"""Explainer Studio — generate educational explainer videos from a topic string."""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["Pipeline", "Scene", "SceneKind", "Script"]


def __getattr__(name: str) -> object:
    """Lazy imports for public API symbols."""
    if name == "Pipeline":
        from explainer.core.pipeline import Pipeline

        return Pipeline
    if name == "Script":
        from explainer.core.schema import Script

        return Script
    if name == "Scene":
        from explainer.core.schema import Scene

        return Scene
    if name == "SceneKind":
        from explainer.core.schema import SceneKind

        return SceneKind
    raise AttributeError(f"module 'explainer' has no attribute {name!r}")
