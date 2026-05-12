"""
Registre pluggable des collectors de sources.

Chaque module source (google_news.py, reddit.py, signalconso.py, ...)
expose une fonction `collect(cfg: SourceConfig) -> Iterator[SignalSource]`
décorée avec `@register("nom")`.

L'orchestrateur dans detecteur.py n'a plus besoin de connaître les noms
de sources individuellement : il itère sur les noms demandés et délègue
au collector correspondant.

Pattern :

    from .registry import register
    from .config import SourceConfig

    @register("ma_source")
    def collect(cfg: SourceConfig) -> Iterator[SignalSource]:
        ...
"""

from __future__ import annotations

import logging
from typing import Callable, Iterator

from ..models import SignalSource
from .config import SourceConfig

logger = logging.getLogger(__name__)


SourceCollector = Callable[[SourceConfig], Iterator[SignalSource]]

# Registre global. Peuplé au moment du décorateur @register.
COLLECTORS: dict[str, SourceCollector] = {}


def register(name: str) -> Callable[[SourceCollector], SourceCollector]:
    """Décorateur d'enregistrement d'un collector."""
    def deco(fn: SourceCollector) -> SourceCollector:
        if name in COLLECTORS:
            logger.warning("Collector %r déjà enregistré, écrasement", name)
        COLLECTORS[name] = fn
        return fn
    return deco


def _ensure_collectors_loaded() -> None:
    """
    Force l'import des modules source pour déclencher leurs @register.
    Appelé paresseusement par get_collector / list_collectors pour éviter
    un cycle d'import au chargement de registry.py.
    """
    # Imports différés : chaque module se déclare lui-même via @register.
    # Ajouter un import ici pour chaque nouvelle source (signalconso, rasff, ...).
    from . import google_news  # noqa: F401
    from . import reddit  # noqa: F401
    from . import signalconso  # noqa: F401


def get_collector(name: str) -> SourceCollector | None:
    """Retourne le collector enregistré pour `name`, ou None si inconnu."""
    _ensure_collectors_loaded()
    return COLLECTORS.get(name)


def list_collectors() -> list[str]:
    """Liste les noms de tous les collectors enregistrés."""
    _ensure_collectors_loaded()
    return sorted(COLLECTORS.keys())
