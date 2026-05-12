"""
Mapping d'un record brut RappelConso vers un Incident normalisé.

Les noms de champs RappelConso V2 peuvent varier légèrement : on tente plusieurs
clés connues et on tombe proprement si rien ne matche. Tout le record d'origine
est conservé dans `incident.raw`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from dateutil import parser as date_parser

from .models import Incident


# Quand plusieurs noms de champs sont plausibles (évolution V1 -> V2,
# ou variantes d'exports), on teste dans l'ordre.
FIELD_MAP = {
    # Noms reels du dataset rappelconso-v2-gtin-espaces (avril 2026).
    # Les alias V1 sont conserves pour rester tolerant si on cible un autre dataset.
    "source_id": ["numero_fiche", "ndeg_de_la_fiche", "reference_fiche", "rappel_guid"],
    "source_url": ["lien_vers_la_fiche_rappel"],
    "categorie": ["categorie_produit", "categorie_de_produit"],
    "sous_categorie": ["sous_categorie_produit", "sous_categorie_de_produit"],
    "marque": ["marque_produit", "nom_de_la_marque_du_produit"],
    "marque_salubrite": ["marque_salubrite", "marque_de_salubrite", "estampille_sanitaire"],
    "modeles": ["modeles_ou_references", "noms_des_modeles_ou_references"],
    "nature_juridique": ["nature_juridique_rappel", "nature_juridique_du_rappel"],
    "motif": ["motif_rappel", "motif_du_rappel"],
    "risques": ["risques_encourus", "risques_encourus_par_le_consommateur"],
    "zone_geographique": ["zone_geographique_de_vente"],
    "distributeurs": ["distributeurs"],
    "date_publication": ["date_publication", "date_de_publication"],
}


def _first_present(record: dict[str, Any], keys: list[str]) -> Optional[Any]:
    for k in keys:
        if k in record and record[k] not in (None, ""):
            return record[k]
    return None


def _parse_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date_parser.parse(value, dayfirst=True).date()
        except (ValueError, date_parser.ParserError):
            return None
    return None


def _coerce_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value if v not in (None, ""))
    return str(value).strip() or None


def normalize_record(record: dict[str, Any], source: str = "rappelconso") -> Incident:
    """Transforme un record brut en Incident.

    L'API Opendatasoft renvoie chaque record comme un dict plat. En cas de
    retour imbriqué (`{"record": {"fields": {...}}}`), on déballe.
    """
    # Déballer si wrapping Opendatasoft v1 (au cas où on cible l'ancienne API)
    if "fields" in record and isinstance(record["fields"], dict):
        record = {**record, **record["fields"]}

    def take(target_field: str) -> Optional[str]:
        return _coerce_str(_first_present(record, FIELD_MAP[target_field]))

    source_id_raw = _first_present(record, FIELD_MAP["source_id"])
    source_id = str(source_id_raw) if source_id_raw is not None else "unknown"

    return Incident(
        source=source,
        source_id=source_id,
        source_url=take("source_url"),
        categorie=take("categorie"),
        sous_categorie=take("sous_categorie"),
        marque=take("marque"),
        marque_salubrite=take("marque_salubrite"),
        modeles=take("modeles"),
        nature_juridique=take("nature_juridique"),
        motif=take("motif"),
        risques=take("risques"),
        zone_geographique=take("zone_geographique"),
        distributeurs=take("distributeurs"),
        date_publication=_parse_date(_first_present(record, FIELD_MAP["date_publication"])),
        raw=dict(record),
    )
