"""
Package des sources de signaux faibles.

Chaque module ajoute une fonction `collect(cfg: SourceConfig)` décorée
avec `@register("nom_source")`. Le module orchestrateur (detecteur.py)
récupère les collectors via `get_collector()` du registry.
"""

from .config import SourceConfig
from .registry import (
    COLLECTORS,
    SourceCollector,
    get_collector,
    list_collectors,
    register,
)

__all__ = [
    "COLLECTORS",
    "SourceCollector",
    "SourceConfig",
    "get_collector",
    "list_collectors",
    "register",
]
