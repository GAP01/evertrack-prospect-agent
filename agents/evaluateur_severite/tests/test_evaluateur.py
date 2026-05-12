"""
Tests de l'agent 2 (sans dependance reseau).

Lancer :
    python -m evaluateur_severite.tests.test_evaluateur
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from ..evaluateur import score_incident
from ..llm_scorer import _fallback_score
from ..models import score_to_tier
from ..rules import (
    score_ampleur_geo, score_population_vulnerable,
    score_volume_distributeurs, score_structured_dimensions,
)
from ..storage import ScoreStorage


# --- Fixtures issues des vrais incidents recuperes le 2026-04-22 ---

INCIDENT_LISTERIA_LOCAL = {
    "source": "rappelconso",
    "source_id": "2026-04-0196",
    "categorie": "alimentation",
    "sous_categorie": "lait et produits laitiers",
    "marque": "sans marque",
    "motif": "presence de listeria",
    "risques": "listeriose",
    "zone_geographique": "carrefour contact laventie uniquement",
    "distributeurs": "carrefour contact laventie uniquement",
    "date_publication": "2026-04-16",
}

INCIDENT_HISTAMINE_LOCAL = {
    "source": "rappelconso",
    "source_id": "2026-04-0265",
    "categorie": "alimentation",
    "sous_categorie": "produits de la peche et d'aquaculture",
    "marque": "sans marques",
    "motif": "taux eleve histamine",
    "risques": "",
    "zone_geographique": "33160 st medard en jalles",
    "distributeurs": "intermarche st medard en jalles",
    "date_publication": "2026-04-22",
}

INCIDENT_PHYTO_NATIONAL = {
    "source": "rappelconso",
    "source_id": "2026-04-0199",
    "categorie": "alimentation",
    "sous_categorie": "cacao, cafe et the",
    "marque": "sweet tea",
    "motif": "presence de residus de produits phytosanitaires a une teneur superieure aux limites autorisees.",
    "risques": "",
    "zone_geographique": "ain (01)|bouches-du-rhone (13)|charente-maritime (17)|meurthe-et-moselle (54)|moselle (57)|nord (59)|puy-de-dome (63)|paris (75)|seine-et-marne (77)|val-de-marne (94)",
    "distributeurs": "epicerie asiatique (voir la liste ci-joint)",
    "date_publication": "2026-04-15",
}

INCIDENT_HISTAMINE_NATIONAL = {
    "source": "rappelconso",
    "source_id": "2026-04-0224",
    "categorie": "alimentation",
    "sous_categorie": "produits de la peche et d'aquaculture",
    "marque": "sans",
    "motif": "taux eleve histamine",
    "risques": "",
    "zone_geographique": "france entiere",
    "distributeurs": "intermarche agen",
    "date_publication": "2026-04-18",
}


# --- Tests des regles deterministes ----------------------------------------

def test_ampleur_geo_national() -> None:
    d = score_ampleur_geo(INCIDENT_HISTAMINE_NATIONAL)
    assert d.raw == 100, f"attendu 100, obtenu {d.raw}"


def test_ampleur_geo_multidep() -> None:
    d = score_ampleur_geo(INCIDENT_PHYTO_NATIONAL)
    # 10 codes departementaux dans la zone -> >=3 -> 70
    assert d.raw == 70, f"attendu 70, obtenu {d.raw}"


def test_ampleur_geo_local() -> None:
    d = score_ampleur_geo(INCIDENT_LISTERIA_LOCAL)
    # "uniquement" detecte -> 15
    assert d.raw == 15, f"attendu 15, obtenu {d.raw}"


def test_population_vulnerable_listeria() -> None:
    d = score_population_vulnerable(INCIDENT_LISTERIA_LOCAL)
    # listeria + listeriose + lait (lait n'est pas dans le mapping infantile)
    assert d.raw >= 60


def test_population_vulnerable_aucun_signal() -> None:
    d = score_population_vulnerable(INCIDENT_HISTAMINE_LOCAL)
    assert d.raw == 0


def test_volume_distributeurs_carrefour() -> None:
    d = score_volume_distributeurs(INCIDENT_LISTERIA_LOCAL)
    # carrefour contact -> 1 enseigne nationale -> 60
    assert d.raw == 60


def test_volume_distributeurs_pas_enseigne_national() -> None:
    d = score_volume_distributeurs(INCIDENT_PHYTO_NATIONAL)
    # "epicerie asiatique" -> distributeurs presents mais pas d'enseigne nationale
    assert d.raw == 30


# --- Test fallback table mots-cles ----------------------------------------

def test_fallback_listeria() -> None:
    score, _, _ = _fallback_score(INCIDENT_LISTERIA_LOCAL)
    assert score >= 90, f"listeria devrait etre >= 90, obtenu {score}"


def test_fallback_histamine() -> None:
    score, _, _ = _fallback_score(INCIDENT_HISTAMINE_LOCAL)
    assert 50 <= score <= 70, f"histamine devrait etre 50-70, obtenu {score}"


def test_fallback_phyto() -> None:
    score, _, _ = _fallback_score(INCIDENT_PHYTO_NATIONAL)
    assert 30 <= score <= 50, f"phyto devrait etre 30-50, obtenu {score}"


# --- Test du score global agrege ------------------------------------------

def test_score_incident_listeria_local_no_llm() -> None:
    """Listeria locale : sanitaire eleve mais ampleur faible.
    Attendu : tier eleve (le sanitaire compte 50%, donc ~46 + 4 + 9 + 6 = ~65)."""
    s = score_incident(INCIDENT_LISTERIA_LOCAL, use_llm=False)
    assert s.tier in ("eleve", "critique"), f"attendu eleve/critique, obtenu {s.tier} ({s.score})"
    assert not s.llm_used


def test_score_incident_histamine_national_no_llm() -> None:
    """Histamine France entiere : sanitaire moyen + ampleur max."""
    s = score_incident(INCIDENT_HISTAMINE_NATIONAL, use_llm=False)
    # 60*0.5 + 100*0.25 + 0*0.15 + 60*0.10 = 30 + 25 + 0 + 6 = 61 -> eleve
    assert s.score >= 50
    assert s.tier in ("modere", "eleve")


def test_score_components_sum_to_total() -> None:
    s = score_incident(INCIDENT_LISTERIA_LOCAL, use_llm=False)
    expected = sum(d.weighted for d in s.dimensions)
    assert abs(s.score - round(expected, 1)) < 0.1


# --- Tests utilitaires -----------------------------------------------------

def test_tier_bounds() -> None:
    assert score_to_tier(85) == "critique"
    assert score_to_tier(70) == "eleve"
    assert score_to_tier(45) == "modere"
    assert score_to_tier(20) == "faible"


# --- Test du storage ------------------------------------------------------

def test_storage_top_and_history() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "scores.sqlite"
        storage = ScoreStorage(db)

        s1 = score_incident(INCIDENT_LISTERIA_LOCAL, use_llm=False)
        s2 = score_incident(INCIDENT_HISTAMINE_NATIONAL, use_llm=False)
        storage.upsert_many([s1, s2])

        top = storage.top(limit=10)
        assert len(top) == 2
        # Tri DESC sur score
        assert top[0]["score"] >= top[1]["score"]


# --- Runner manuel --------------------------------------------------------

if __name__ == "__main__":
    funcs = [
        test_ampleur_geo_national,
        test_ampleur_geo_multidep,
        test_ampleur_geo_local,
        test_population_vulnerable_listeria,
        test_population_vulnerable_aucun_signal,
        test_volume_distributeurs_carrefour,
        test_volume_distributeurs_pas_enseigne_national,
        test_fallback_listeria,
        test_fallback_histamine,
        test_fallback_phyto,
        test_score_incident_listeria_local_no_llm,
        test_score_incident_histamine_national_no_llm,
        test_score_components_sum_to_total,
        test_tier_bounds,
        test_storage_top_and_history,
    ]
    failed = 0
    for f in funcs:
        try:
            f()
            print(f"[PASS] {f.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"[FAIL] {f.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"[ERROR] {f.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(funcs)-failed}/{len(funcs)} tests passes")
    raise SystemExit(0 if failed == 0 else 1)
