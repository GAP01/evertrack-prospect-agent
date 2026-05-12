"""Modeles de donnees de l'evaluateur de severite."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Optional


# Bornes des tiers - score 0 a 100.
TIER_BOUNDS = [
    ("critique", 80),
    ("eleve", 60),
    ("modere", 40),
    ("faible", 0),
]


def score_to_tier(score: float) -> str:
    for tier, threshold in TIER_BOUNDS:
        if score >= threshold:
            return tier
    return "faible"


@dataclass
class DimensionScore:
    """Resultat de scoring sur une dimension."""
    name: str                       # ex: "risque_sanitaire"
    raw: float                      # 0-100
    weight: float                   # 0-1, somme = 1 entre dimensions
    rationale: str                  # justification courte humaine

    @property
    def weighted(self) -> float:
        return self.raw * self.weight


@dataclass
class IncidentScore:
    """Score global d'un incident, decompose par dimension."""
    source: str
    source_id: str
    score: float                              # 0-100
    tier: str                                 # faible/modere/eleve/critique
    dimensions: list[DimensionScore] = field(default_factory=list)
    scored_at: datetime = field(default_factory=datetime.utcnow)
    scorer_version: str = "v0.1"
    llm_used: bool = False                    # True si l'API LLM a ete appelee

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["scored_at"] = self.scored_at.isoformat()
        return d

    @classmethod
    def from_dimensions(
        cls,
        source: str,
        source_id: str,
        dimensions: list[DimensionScore],
        llm_used: bool = False,
        scorer_version: str = "v0.1",
    ) -> "IncidentScore":
        # Verification de coherence : la somme des poids doit etre ~= 1.
        total_weight = sum(d.weight for d in dimensions)
        if abs(total_weight - 1.0) > 0.01:
            raise ValueError(
                f"Poids des dimensions = {total_weight:.3f}, attendu 1.0. "
                "Verifier la configuration des poids."
            )
        score = sum(d.weighted for d in dimensions)
        return cls(
            source=source,
            source_id=source_id,
            score=round(score, 1),
            tier=score_to_tier(score),
            dimensions=dimensions,
            llm_used=llm_used,
            scorer_version=scorer_version,
        )
