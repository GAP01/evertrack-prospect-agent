"""
Déduplication et génération de signal_id.

Le signal_id est un hash stable construit sur (marque + symptome_famille + semaine).
Si marque est None, on fallback sur produit, puis symptome seul, puis titre.

Objectif : plusieurs articles de presse qui parlent du MÊME événement (même
rappel) doivent partager le même signal_id. Sans ça, chaque article se
retrouve isolé et la récurrence stagne à 1 source.

Stratégie :
- Fenêtre temporelle = semaine ISO (7 jours glissants) — articles publiés
  sur Marmiton J0, TF1 J+1, Femme Actuelle J+3 fusionnent tous
- Symptôme = famille pathogène (listeria/salmonelle/e.coli/...) — le LLM
  renvoie parfois "contamination bactérienne", parfois "listeria"
  spécifiquement ; on normalise tout vers une clé de famille

Le merge par rappelconso_url (règle dure, a posteriori) est géré dans
`merger.py` et complète ce hash initial.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime
from typing import Optional


def _strip_accents(s: str) -> str:
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _normalize(s: str) -> str:
    """Lowercase, strip accents, squeeze whitespace, alphanum only."""
    if not s:
        return ""
    s = _strip_accents(s.lower())
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_title(titre: str) -> str:
    """Tronque à 80 chars après normalisation."""
    return _normalize(titre)[:80]


# --- Familles de symptômes -----------------------------------------------

# Normalise un symptôme libre (du LLM) vers une clé de famille stable.
# Ex : "listeriose", "Listeria monocytogenes", "listeria" → "listeria"
#      "contamination bactérienne", "bactérie" → "bacterie_generique"
# Deux signaux avec des symptomes synonymes auront la même famille → même
# signal_id (si marque + semaine identiques aussi).
_SYMPTOME_FAMILY: list[tuple[str, list[str]]] = [
    # Pathogènes spécifiques (testés en 1er, priorité absolue)
    ("listeria", ["listeria", "listeriose", "monocytogenes"]),
    ("salmonelle", ["salmonel", "salmonella"]),
    ("ecoli", ["escherichia coli", "e coli", "e.coli", "stec", "enterohemorra", "shu"]),
    ("botulisme", ["botulisme", "clostridium botulinum"]),
    ("norovirus", ["norovirus"]),
    ("staphylocoque", ["staphylo", "staphylococc"]),
    ("campylobacter", ["campylobacter"]),
    ("hepatite_a", ["hepatite a", "hepatite virale"]),
    ("histamine", ["histamine"]),
    ("moisissure", ["moisissure", "levures"]),
    ("allergene", ["allergene", "allergen"]),
    ("verre", ["verre", "morceau de verre"]),
    ("plastique", ["plastique", "fragment de plastique"]),
    ("metal", ["metal", "fragment de metal"]),
    ("corps_etranger", ["corps etranger", "inertes", "fragment"]),
    ("pesticides", ["pesticide", "phytosanitaire", "residu"]),
    ("metaux_lourds", ["plomb", "cadmium", "mercure", "arsenic"]),
    ("etouffement", ["etouffement", "suffocation", "petites pieces"]),
    # Génériques — testés en dernier, bucket "fourre-tout bactérien"
    ("bacterie_generique", [
        "contamination bacterienne", "contamination microbiologique",
        "toxi infection", "toxi-infection", "intoxication",
        "bacterie", "bacteries", "pathogene",
    ]),
]


def symptome_family(symptome: Optional[str]) -> Optional[str]:
    """
    Retourne la clé de famille pour un symptôme, ou None si pas de match.

    On normalise + on cherche un pattern dans la liste (ordre important :
    spécifique avant générique).
    """
    if not symptome:
        return None
    n = _normalize(symptome)
    if not n:
        return None
    for family, patterns in _SYMPTOME_FAMILY:
        for p in patterns:
            if _normalize(p) in n:
                return family
    return None


# --- Fenêtre temporelle : semaine ISO ------------------------------------

def iso_week_bucket(dt: datetime) -> str:
    """
    Retourne la semaine ISO au format 'YYYY-Www' (ex: '2026-W17').
    Deux dates dans la même semaine calendaire → même bucket.

    Trade-off vs 'jour' :
    - Pour : fusionne les articles publiés sur plusieurs jours (cas normal
      de la couverture presse qui s'étale).
    - Contre : deux incidents distincts sur la même marque + même symptome
      la même semaine fusionneraient à tort. Rare en pratique, et le
      merge-URL a posteriori corrige la majorité des faux positifs.
    """
    if not dt:
        return ""
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


# --- Computation du signal_id --------------------------------------------

def compute_signal_id(
    marque: Optional[str],
    symptome: Optional[str],
    titre: str,
    detected_at: datetime,
    produit: Optional[str] = None,
) -> str:
    """
    Hash stable 16 chars.

    Stratégie de dédup par ordre de priorité :
    - Marque + symptome présents    → "brand|marque|famille|semaine"
    - Produit + symptome présents   → "prod|produit|famille|semaine"
    - Symptome seul présent         → "sympt|famille|semaine"
    - Fallback                      → "title|titre|semaine"

    La fenêtre temporelle (semaine ISO) + la normalisation symptôme vers
    une famille pathogène assurent que les articles d'une même affaire
    fusionnent en un seul signal même s'ils sont publiés sur plusieurs
    jours ou avec des variantes LLM ("listeria" vs "contamination
    bactérienne").
    """
    week = iso_week_bucket(detected_at)
    # Famille pathogène (fallback sur symptome normalisé si inconnue)
    family = symptome_family(symptome) or _normalize(symptome or "")

    if marque and family:
        key = f"brand|{_normalize(marque)}|{family}|{week}"
    elif produit and family:
        key = f"prod|{_normalize(produit)}|{family}|{week}"
    elif family:
        key = f"sympt|{family}|{week}"
    else:
        key = f"title|{normalize_title(titre)}|{week}"

    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return digest[:16]
