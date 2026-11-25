"""Thread-safe registry for lazily constructed optional AI engines."""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock

from app.ai.base import AIEngine, EngineDescriptor


EngineFactory = Callable[[], AIEngine]


class EngineRegistry:
    """Register engine factories and instantiate them only when requested.

    Registration and descriptor listing are safe in offline environments:
    factories are never called until get() is explicitly invoked.
    """

    def __init__(self) -> None:
        self._factories: dict[str, tuple[EngineDescriptor, EngineFactory]] = {}
        self._instances: dict[str, AIEngine] = {}
        self._lock = RLock()

    def register(
        self,
        descriptor: EngineDescriptor,
        factory: EngineFactory,
    ) -> None:
        """Register a factory without constructing its engine."""
        if not descriptor.id.strip():
            raise ValueError("Engine id must not be empty.")
        with self._lock:
            if descriptor.id in self._factories:
                raise ValueError(f"Engine already registered: {descriptor.id}")
            self._factories[descriptor.id] = (descriptor, factory)

    def descriptors(self) -> list[EngineDescriptor]:
        """Return metadata without importing or constructing model code."""
        with self._lock:
            return [item[0] for item in self._factories.values()]

    def get(self, engine_id: str) -> AIEngine:
        """Construct and cache an engine on first explicit request."""
        with self._lock:
            try:
                descriptor, factory = self._factories[engine_id]
            except KeyError as exc:
                raise KeyError(f"Unknown AI engine: {engine_id}") from exc

            if engine_id not in self._instances:
                engine = factory()
                if not isinstance(engine, AIEngine):
                    raise TypeError(
                        f"Factory for {engine_id!r} did not return an AIEngine."
                    )
                if engine.descriptor.id != descriptor.id:
                    raise ValueError(
                        f"Factory for {engine_id!r} returned engine "
                        f"{engine.descriptor.id!r}."
                    )
                self._instances[engine_id] = engine

            return self._instances[engine_id]


engine_registry = EngineRegistry()
