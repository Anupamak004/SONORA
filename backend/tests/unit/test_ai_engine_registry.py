"""Unit tests for the optional AI engine contract and lazy registry."""

from __future__ import annotations

import numpy as np
import pytest

from app.ai.base import AIEngine, AudioArray, EngineDescriptor
from app.ai.registry import EngineRegistry


class FakeEngine(AIEngine):
    descriptor = EngineDescriptor(
        id="fake",
        name="Fake test engine",
        category="test",
        description="Test-only engine.",
    )

    def separate(
        self,
        audio: AudioArray,
        sample_rate: int,
        query: str,
    ) -> AudioArray:
        return audio.copy()


def test_register_and_list_do_not_construct_engine() -> None:
    registry = EngineRegistry()
    constructions = 0

    def factory() -> AIEngine:
        nonlocal constructions
        constructions += 1
        return FakeEngine()

    registry.register(FakeEngine.descriptor, factory)

    assert constructions == 0
    assert [item.id for item in registry.descriptors()] == ["fake"]
    assert constructions == 0


def test_get_constructs_once_and_caches_instance() -> None:
    registry = EngineRegistry()
    constructions = 0

    def factory() -> AIEngine:
        nonlocal constructions
        constructions += 1
        return FakeEngine()

    registry.register(FakeEngine.descriptor, factory)

    first = registry.get("fake")
    second = registry.get("fake")

    assert first is second
    assert constructions == 1


def test_duplicate_registration_is_rejected() -> None:
    registry = EngineRegistry()
    registry.register(FakeEngine.descriptor, FakeEngine)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(FakeEngine.descriptor, FakeEngine)


def test_unknown_engine_is_reported() -> None:
    registry = EngineRegistry()

    with pytest.raises(KeyError, match="Unknown AI engine"):
        registry.get("missing")


def test_factory_must_return_matching_ai_engine() -> None:
    registry = EngineRegistry()
    registry.register(FakeEngine.descriptor, lambda: object())  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="did not return an AIEngine"):
        registry.get("fake")


def test_engine_contract_preserves_shape_for_test_implementation() -> None:
    engine = FakeEngine()
    audio = np.zeros((480, 2), dtype=np.float32)

    result = engine.separate(audio, 48_000, "ukulele")

    assert result.shape == audio.shape
    assert result.dtype == np.float32
    assert result is not audio
