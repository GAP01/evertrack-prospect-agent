"""Chargement de la configuration pitch editeur depuis pitch.json."""

from __future__ import annotations

import json
import os
from typing import Any


DEFAULT_PITCH: dict[str, Any] = {
    "version": "0.0",
    "editeur_nom": "EverTrack",
    "pitch_court": "",
    "valeur_immediate": "",
    "cta": "",
    "signature": "Cordialement,\nEquipe EverTrack",
    "opt_out_placeholder": "",
}


def load_pitch(path: str | None = None) -> dict[str, Any]:
    """
    Charge la config pitch depuis un fichier JSON.

    Retourne une copie de DEFAULT_PITCH completee/ecrasee par les valeurs du
    fichier. Les cles absentes du fichier sont remplies par les defaults.
    Ne leve jamais d'exception : fichier absent ou JSON invalide => defaults.

    Args:
        path: chemin vers pitch.json. Si None, utilise pitch.json co-localise
              avec ce module.

    Returns:
        Dict avec au minimum les cles de DEFAULT_PITCH.
    """
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "pitch.json")

    result = dict(DEFAULT_PITCH)

    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return result
    except (json.JSONDecodeError, OSError):
        return result

    # Les cles presentes dans le fichier ecrasent les defaults
    result.update(data)
    return result
