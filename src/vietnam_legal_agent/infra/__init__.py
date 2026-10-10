"""Infrastructure adapters for persistence and external services."""

from .persistence import PersistenceStore, get_persistence_store

__all__ = ["PersistenceStore", "get_persistence_store"]
