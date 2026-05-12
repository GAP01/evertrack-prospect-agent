"""
Regles deterministes pour les dimensions structurees du scoring.

Trois dimensions sont scorees ici (sans LLM) :
- Ampleur geographique  (a partir de zone_geographique + distributeurs)
- Population vulnerable (a partir de sous_categorie + risques + motif)
- Volume distributeurs  (a partir de distributeurs)

Le risque sanitaire est traite a part par llm_scorer.py.

Toutes les valeurs sont normalisees en minuscule (cf. mapping RappelConso V2).
"""

from __future__ import annotations

import re
from typing import Any

from .models import DimensionScore


# --- Ampleur geographique --------------------------------------------------

# Marqueurs textuels classes du plus large au plus etroit.
GEO_NATIONAL_PATTERNS = [
    "france entiere",
    "france entière",
    "national",
    "tout le territoire",
]

# Departement / region : on detecte numeros (01-95, 971-976) ou noms.
GEO_DEPT_REGEX = re.compile(r"\(\d{2,3}\)|\bdepartement\b|\bregion\b")

GEO_LOCAL_HINTS = [
    "magasin",
    "uniquement",
    "exclusivement",
    "ville de",
    "commune de",
]


def score_ampleur_geo(incident: dict[str, Any]) -> DimensionScore:
    """
    100 = France entiere ou multi-regional
     60 = plusieurs departements / regions
     30 = un departement ou une zone localisee
     15 = un seul magasin / commune
      0 = aucune info exploitable (par defaut prudent : 30)
    """
    zone = (incident.get("zone_geographique") or "").lower()
    distrib = (incident.get("distributeurs") or "").lower()
    blob = f"{zone} | {distrib}"

    if any(p in blob for p in GEO_NATIONAL_PATTERNS):
        return DimensionScore("ampleur_geo", 100, 0.25,
                              "Diffusion nationale (France entiere ou equivalent)")

    # Compter les marqueurs departementaux : "(75)", "(13)", etc.
    dept_codes = re.findall(r"\((\d{2,3})\)", blob)
    if len(dept_codes) >= 3:
        return DimensionScore("ampleur_geo", 70, 0.25,
                              f"Diffusion multi-departementale ({len(dept_codes)} dep.)")
    if len(dept_codes) >= 1:
        return DimensionScore("ampleur_geo", 45, 0.25,
                              f"Diffusion sur {len(dept_codes)} departement(s)")

    if any(h in blob for h in GEO_LOCAL_HINTS):
        return DimensionScore("ampleur_geo", 15, 0.25,
                              "Diffusion locale (un magasin ou commune unique)")

    return DimensionScore("ampleur_geo", 30, 0.25,
                          "Aucune indication geographique exploitable, defaut prudent")


# --- Population vulnerable -------------------------------------------------

VULNERABLE_KEYWORDS = {
    # Sous-categorie / type de produit
    "lait infantile": "Produit destine aux nourrissons",
    "alimentation infantile": "Produit destine aux nourrissons",
    "babyfood": "Produit destine aux nourrissons",
    "petits pots": "Produit destine aux nourrissons",
    "premier age": "Produit destine aux nourrissons",
    "deuxieme age": "Produit destine aux nourrissons",
    # Pathologies / pathogenes touchant des populations sensibles
    "listeria": "Listeriose - femmes enceintes, immunodeprimes, personnes agees",
    "listeriose": "Listeriose - femmes enceintes, immunodeprimes, personnes agees",
    "botulisme": "Botulisme - tres grave, populations sensibles particulierement vulnerables",
    "clostridium botulinum": "Botulisme",
    "salmonel": "Salmonellose - enfants en bas age plus exposes",
    "e. coli": "E. coli - SHU chez l'enfant, risque vital",
    "escherichia coli": "E. coli - SHU chez l'enfant",
    "shu": "Syndrome hemolytique et uremique - enfant",
    # Categorie jouet
    "etouffement": "Risque etouffement - jeunes enfants",
    "petites pieces": "Petites pieces detachables - jeunes enfants",
}


def score_population_vulnerable(incident: dict[str, Any]) -> DimensionScore:
    """
    Bonus appliquant un poids modere (15%).
    100 = population tres vulnerable identifiee (nourrisson, immunodeprime)
     60 = population sensible (enfant, personne agee)
      0 = pas de signal de vulnerabilite particuliere
    """
    blob = " ".join(filter(None, [
        (incident.get("sous_categorie") or "").lower(),
        (incident.get("motif") or "").lower(),
        (incident.get("risques") or "").lower(),
    ]))

    matches = []
    for kw, label in VULNERABLE_KEYWORDS.items():
        if kw in blob:
            matches.append(label)

    if not matches:
        return DimensionScore("population_vulnerable", 0, 0.15,
                              "Aucun signal de population particulierement vulnerable")

    # On prend la note max (un seul match suffit a flagger la fiche)
    # mais on peut moduler par le nombre de signaux concordants.
    base = 100 if any("nourrisson" in m.lower() or "botulisme" in m.lower() or "shu" in m.lower()
                      for m in matches) else 60
    rationale = matches[0] + (f" (+{len(matches)-1} autre signal)" if len(matches) > 1 else "")
    return DimensionScore("population_vulnerable", base, 0.15, rationale)


# --- Volume distributeurs --------------------------------------------------

# Grandes enseignes a fort volume = signal d'amplification.
ENSEIGNES_NATIONALES = [
    "carrefour", "leclerc", "auchan", "intermarche", "intermarché",
    "lidl", "aldi", "casino", "monoprix", "franprix",
    "super u", "hyper u", "u express", "systeme u", "système u",
    "cora", "match", "naturalia", "biocoop", "amazon",
]


def score_volume_distributeurs(incident: dict[str, Any]) -> DimensionScore:
    """
    100 = >= 3 grandes enseignes nationales
     60 = 1-2 grandes enseignes nationales
     30 = distributeurs presents mais pas d'enseigne nationale identifiee
     10 = pas de distributeur listee ou liste vide
    """
    distrib = (incident.get("distributeurs") or "").lower()
    if not distrib.strip():
        return DimensionScore("volume_distributeurs", 10, 0.10,
                              "Aucun distributeur identifie")

    enseignes_touchees = [e for e in ENSEIGNES_NATIONALES if e in distrib]
    n = len(set(enseignes_touchees))

    if n >= 3:
        return DimensionScore("volume_distributeurs", 100, 0.10,
                              f"{n} grandes enseignes nationales touchees")
    if n >= 1:
        sample = ", ".join(sorted(set(enseignes_touchees))[:3])
        return DimensionScore("volume_distributeurs", 60, 0.10,
                              f"Enseigne(s) nationale(s) touchee(s) : {sample}")

    return DimensionScore("volume_distributeurs", 30, 0.10,
                          "Distributeurs listes mais aucune enseigne nationale identifiee")


# --- Aggregation ------------------------------------------------------------

def score_structured_dimensions(incident: dict[str, Any]) -> list[DimensionScore]:
    """Score les 3 dimensions deterministes a partir du dict incident (issu de Storage)."""
    return [
        score_ampleur_geo(incident),
        score_population_vulnerable(incident),
        score_volume_distributeurs(incident),
    ]
