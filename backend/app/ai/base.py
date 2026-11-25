"""Stable contract shared by optional audio AI engines."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


AudioArray = NDArray[np.float32]


@dataclass(frozen=True, slots=True)
class EngineDescriptor:
    """Static engine metadata; describing an engine never loads its model."""

    id: str
    name: str
    category: str
    description: str
    experimental: bool = True


class AIEngine(ABC):
    """Base contract for optional, explicitly loaded audio separation engines.

    Implementations must not download weights implicitly. Model acquisition and
    consent belong to a separate setup workflow; construction may validate local
    files and load already-installed weights.
    """

    descriptor: EngineDescriptor

    @abstractmethod
    def separate(
        self,
        audio: AudioArray,
        sample_rate: int,
        query: str,
    ) -> AudioArray:
        """Return a target estimate with the same frame count and channel layout.

        The caller owns resampling, channel normalization, chunking, output
        validation, and residual construction. Implementations must document
        any model-specific constraints.
        """
        raise NotImplementedError
