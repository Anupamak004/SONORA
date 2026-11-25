"""Optional AI engine interfaces and lazy registry.

Importing this package does not import model frameworks or download checkpoints.
"""

from app.ai.base import AIEngine, EngineDescriptor
from app.ai.registry import EngineRegistry, engine_registry

__all__ = ["AIEngine", "EngineDescriptor", "EngineRegistry", "engine_registry"]
