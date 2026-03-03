"""AIPM core — orchestrator, config, utilities, and shared infrastructure."""


def __getattr__(name: str):  # noqa: N807
    """Lazy imports to avoid circular dependency with aipm.agents."""
    if name == "PipelineOrchestrator":
        from aipm.core.orchestrator import PipelineOrchestrator

        return PipelineOrchestrator
    if name == "load_policy":
        from aipm.core.policy import load_policy

        return load_policy
    if name == "load_bundle":
        from aipm.core.loader import load_bundle

        return load_bundle
    raise AttributeError(f"module 'aipm.core' has no attribute {name!r}")


__all__ = [
    "PipelineOrchestrator",
    "load_bundle",
    "load_policy",
]
