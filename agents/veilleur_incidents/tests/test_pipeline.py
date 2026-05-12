"""
Tests du pipeline sans dépendance réseau : normalisation + stockage.

À lancer depuis `agents/` :
    python -m veilleur_incidents.tests.test_pipeline
Ou via pytest si installé :
    pytest agents/veilleur_incidents/tests
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ..normalize import normalize_record
from ..storage import Storage


FAKE_RECORDS = [
    {
        "numero_fiche": "2026-04-0123",
        "lien_vers_la_fiche_rappel": "https://rappel.conso.gouv.fr/fiche-rappel/2026-04-0123/",
        "categorie_produit": "Alimentation",
        "sous_categorie_produit": "Lait et produits laitiers",
        "marque_produit": "Lactéo Pro",
        "modeles_ou_references": "Camembert fermier 250g lot 24A",
        "nature_juridique_rappel": "Rappel",
        "motif_rappel": "Présence de Listeria monocytogenes détectée",
        "risques_encourus": "Listériose",
        "zone_geographique_de_vente": "France entière",
        "distributeurs": ["Carrefour", "Leclerc"],
        "date_publication": "2026-04-20",
    },
    {
        "numero_fiche": "2026-04-0122",
        "categorie_produit": "Alimentation",
        "marque_produit": "MeatCorp",
        "motif_rappel": "Contamination Salmonella spp.",
        "date_publication": "2026-04-18",
    },
]


def test_normalize_and_persist() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "incidents.sqlite"
        storage = Storage(db)
        incidents = [normalize_record(r) for r in FAKE_RECORDS]
        new, upd = storage.upsert_many(incidents)
        assert (new, upd) == (2, 0)

        # Idempotence : un second run ne crée pas de doublon
        new2, upd2 = storage.upsert_many(incidents)
        assert (new2, upd2) == (0, 2)
        assert storage.count() == 2

        recent = storage.list_recent(limit=5)
        assert recent[0]["date_publication"] == "2026-04-20"
        assert recent[0]["marque"] == "Lactéo Pro"
        assert recent[0]["distributeurs"] == "Carrefour, Leclerc"


if __name__ == "__main__":
    test_normalize_and_persist()
    print("[PASS] test_normalize_and_persist")
