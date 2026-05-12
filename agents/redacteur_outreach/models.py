"""Modeles de donnees du redacteur outreach (Agent 5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


REDACTEUR_VERSION = "1.0"

# Statuts du cycle de vie d'un message outreach
STATUS_CHOICES = ("brouillon", "a_valider", "valide", "envoye", "rejete")

# Canaux de diffusion — V1 email uniquement, schema extensible
CANAL_CHOICES = ("email",)


@dataclass
class OutreachMessage:
    """Un message outreach genere pour un incident/prospect donne."""

    # Identite
    message_id: str
    source: str        # origine du contexte, ex. "rappelconso"
    source_id: str     # identifiant de l'incident ou du prospect source

    # Canal
    canal: str = "email"

    # Contenu
    objet: Optional[str] = None
    body_md: Optional[str] = None          # corps au format Markdown
    body_fallback: Optional[str] = None    # corps texte brut (si LLM indisponible)

    # Tracabilite generation
    llm_used: bool = False
    redacteur_version: str = field(default_factory=lambda: REDACTEUR_VERSION)
    # JSON serialise du contexte incident+prospect ayant servi a la generation (audit)
    context_json: Optional[str] = None
    pitch_version: Optional[str] = None   # variante de prompt/template utilisee

    # Statut workflow
    status: str = "brouillon"

    # Timestamps ISO-8601
    generated_at: Optional[str] = None
    validated_at: Optional[str] = None
    sent_at: Optional[str] = None

    # Notes libres (reviewer humain)
    notes: Optional[str] = None
