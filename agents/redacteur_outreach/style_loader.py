"""Chargement et normalisation de l'exemple stylistique pour le rewriter LLM."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path


DEFAULT_STYLE_PATH = Path(__file__).parent / "style_examples" / "example_default.txt"

# Cache module-level : cle = chemin absolu resolu, valeur = texte normalise ou None
_CACHE: dict[str, str | None] = {}


def _normalize_ascii(txt: str) -> str:
    """
    Normalise un texte UTF-8 vers ASCII pur (safe Windows cp1252).

    Decomposition NFKD puis encode/decode ASCII ignore — couvre les accents
    et diacritiques. Remplacements explicites pour les ligatures non decomposables
    (oe, ae) avant la decomposition.
    """
    # Remplacements explicites de ligatures que NFKD ne decompose pas
    replacements = [
        ("œ", "oe"),   # oe ligature (comme dans 'coeur')
        ("Œ", "OE"),
        ("æ", "ae"),   # ae ligature
        ("Æ", "AE"),
        # Apostrophes typographiques : remplacer par apostrophe ASCII
        ("’", "'"),    # RIGHT SINGLE QUOTATION MARK
        ("‘", "'"),    # LEFT SINGLE QUOTATION MARK
        ("“", '"'),    # LEFT DOUBLE QUOTATION MARK
        ("”", '"'),    # RIGHT DOUBLE QUOTATION MARK
        ("–", "-"),    # EN DASH
        ("—", "-"),    # EM DASH
    ]
    for src, dst in replacements:
        txt = txt.replace(src, dst)

    return unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode("ascii")


def _strip_excess_blank_lines(txt: str) -> str:
    """Reduit les sequences de lignes vides consecutives a une seule."""
    # Remplace 2+ newlines consecutifs par exactement deux (une ligne vide)
    return re.sub(r"\n{3,}", "\n\n", txt).strip()


def _truncate_at_word(txt: str, max_chars: int) -> str:
    """Tronque au dernier saut de ligne ou espace avant max_chars."""
    if len(txt) <= max_chars:
        return txt
    # Cherche le dernier saut de ligne avant la limite
    cut = txt.rfind("\n", 0, max_chars)
    if cut == -1:
        # Pas de newline : coupe au dernier espace
        cut = txt.rfind(" ", 0, max_chars)
    if cut == -1:
        # Pas d'espace non plus : coupe dur
        cut = max_chars
    return txt[:cut].strip()


def load_style_example(path: Path | None = None, max_chars: int = 2000) -> str | None:
    """
    Charge, normalise et met en cache l'exemple stylistique.

    Args:
        path: chemin vers le fichier .txt. Si None, utilise DEFAULT_STYLE_PATH.
        max_chars: taille maximale en caracteres apres normalisation.
                   La troncature se fait au dernier saut de ligne avant la limite.

    Returns:
        Texte normalise ASCII pur, ou None si le fichier est absent/illisible.
    """
    resolved = str((path or DEFAULT_STYLE_PATH).resolve())

    if resolved in _CACHE:
        return _CACHE[resolved]

    try:
        raw = (path or DEFAULT_STYLE_PATH).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        _CACHE[resolved] = None
        return None

    normalized = _normalize_ascii(raw)
    normalized = _strip_excess_blank_lines(normalized)
    normalized = _truncate_at_word(normalized, max_chars)

    _CACHE[resolved] = normalized
    return normalized
