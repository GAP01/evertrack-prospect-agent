"""
Orchestration du matching marque → entreprise SIRENE + enrichissement contact Pappers.

Logique :
1. Normaliser la marque (normalizer.py)
2. Fallback sur distributeurs si marque inutilisable
3. Appel SIRENE pour identification (api_sirene.py)
4. Score de similarité nom normalisé / raison sociale
5. Si found/ambiguous + PAPPERS_API_KEY définie → appel Pappers pour contact dirigeant
"""

from __future__ import annotations

import difflib
import json
import logging
import os
from typing import Any, Optional

from .api_sirene import SireneClient, SireneAPIError, extract_company_fields
from . import agrements_dgal
from .api_pappers import PappersClient, PappersNotConfiguredError, PappersAPIError
from .models import (
    EnrichissementResult,
    CONFIDENCE_FOUND,
    CONFIDENCE_AMBIGUOUS,
)
from .normalizer import normalize_marque, normalize_distributeur, _strip_accents

logger = logging.getLogger(__name__)

ENRICHER_VERSION = "v0.1"


def _get_pappers_client() -> Optional[PappersClient]:
    """Retourne un client Pappers si la clé est configurée, sinon None."""
    try:
        return PappersClient()
    except PappersNotConfiguredError:
        return None


def _similarity(a: str, b: str) -> float:
    """Score de similarité entre deux chaînes normalisées (0.0–1.0)."""
    a_norm = _strip_accents(a.lower().strip())
    b_norm = _strip_accents(b.lower().strip())
    return difflib.SequenceMatcher(None, a_norm, b_norm).ratio()


def _best_candidate(
    query: str,
    results: list[dict[str, Any]],
) -> tuple[Optional[dict[str, Any]], float]:
    """
    Retourne (meilleur_résultat, confidence) parmi les candidats SIRENE.

    La confidence est le score de similarité entre la query normalisée
    et la raison sociale du candidat.
    """
    best_result: Optional[dict[str, Any]] = None
    best_score = 0.0

    for r in results:
        raison = r.get("nom_complet") or r.get("nom_raison_sociale") or ""
        score = _similarity(query, raison)
        # Bonus si le nom de la query est un sous-ensemble de la raison sociale
        if _strip_accents(query.lower()) in _strip_accents(raison.lower()):
            score = min(1.0, score + 0.15)
        if score > best_score:
            best_score = score
            best_result = r

    return best_result, round(best_score, 3)


def _enrich_contact_pappers(
    siren: str,
    pappers: PappersClient,
) -> dict[str, Optional[str]]:
    """
    Tente de récupérer le meilleur contact via Pappers pour un SIREN donné.

    Retourne un dict avec contact_nom, contact_titre, contact_type, contact_source.
    En cas d'erreur, retourne des champs None sans lever d'exception.
    """
    try:
        data = pappers.get_by_siren(siren)
        if data is None:
            return {"contact_nom": None, "contact_titre": None,
                    "contact_type": None, "contact_source": None}
        contact = pappers.extract_contact(data)
        contact["contact_source"] = "pappers" if contact.get("contact_nom") else None
        return contact
    except PappersAPIError as exc:
        logger.warning("Pappers indisponible pour siren=%s : %s", siren, exc)
        return {"contact_nom": None, "contact_titre": None,
                "contact_type": None, "contact_source": None}



# Confidence pour un match via agrément sanitaire DGAL.
# Très élevée : l'agrément est nominatif et pointe directement vers
# l'établissement de production (usine) avec son SIRET officiel.
CONFIDENCE_AGREMENT = 0.95


def _try_match_via_agrement(
    incident: dict[str, Any],
    client: SireneClient,
) -> Optional[EnrichissementResult]:
    """
    Tentative de match via la marque de salubrité (agrément DGAL CE 853/2004).

    Retourne :
      - EnrichissementResult prêt si l'agrément est valide et trouvé en base DGAL
        + résolu côté SIRENE (confidence 0.95).
      - None si pas applicable (pas d'agrément, ou non trouvé) → fallback
        sur la stratégie classique par marque commerciale.
    """
    source = incident["source"]
    source_id = incident["source_id"]
    raw = (incident.get("marque_salubrite") or "").strip()
    if not raw:
        return None

    numero = agrements_dgal.parse_agrement(raw)
    if not numero:
        logger.debug("Incident %s : marque_salubrite non parsable %r", source_id, raw)
        return None

    dgal = agrements_dgal.lookup(numero)
    if not dgal:
        logger.info(
            "Incident %s : agrément %s introuvable dans la base DGAL "
            "(refresh nécessaire ?). Fallback marque.",
            source_id, numero,
        )
        return None

    siret = (dgal.get("siret") or "").strip()
    if not siret:
        # Cas rare : ligne DGAL sans SIRET (devrait être corrigé en amont)
        logger.warning(
            "Incident %s : agrément %s sans SIRET en base DGAL", source_id, numero,
        )
        # On peut quand même retourner un match partiel basé sur les infos DGAL
        return EnrichissementResult(
            source=source,
            source_id=source_id,
            enricher_version=ENRICHER_VERSION,
            marque_input=incident.get("marque"),
            query_used=f"agrement:{numero}",
            match_status="found",
            confidence=CONFIDENCE_AGREMENT,
            api_used="agrement_dgal",
            siren=None,
            siret_siege=None,
            raison_sociale=dgal.get("raison_sociale"),
            adresse=" ".join(p for p in [
                dgal.get("adresse"),
                dgal.get("code_postal"),
                dgal.get("commune"),
            ] if p),
            raw_json=json.dumps({"dgal": dgal}, ensure_ascii=False, default=str),
        )

    # Cas normal : on a un SIRET → lookup SIRENE par SIREN (= 9 premiers chiffres)
    siren = siret[:9] if len(siret) >= 9 else siret
    sirene_data: Optional[dict[str, Any]] = None
    try:
        sirene_data = client.get_by_siren(siren)
    except SireneAPIError as exc:
        logger.warning(
            "Incident %s : agrément %s → SIREN %s, mais SIRENE KO : %s. "
            "Fallback sur infos DGAL seules.",
            source_id, numero, siren, exc,
        )

    if sirene_data:
        fields = extract_company_fields(sirene_data)
        # On garde le SIRET de l'établissement DGAL (= usine), pas forcément celui du siège
        fields["siret_etablissement_dgal"] = siret
        return EnrichissementResult(
            source=source,
            source_id=source_id,
            enricher_version=ENRICHER_VERSION,
            marque_input=incident.get("marque"),
            query_used=f"agrement:{numero}",
            match_status="found",
            confidence=CONFIDENCE_AGREMENT,
            api_used="agrement_dgal+sirene",
            siren=fields.get("siren"),
            siret_siege=fields.get("siret_siege"),
            raison_sociale=fields.get("raison_sociale") or dgal.get("raison_sociale"),
            forme_juridique=fields.get("forme_juridique"),
            code_naf=fields.get("code_naf"),
            libelle_naf=fields.get("libelle_naf"),
            adresse=fields.get("adresse"),
            effectif_tranche=fields.get("effectif_tranche"),
            categorie_entreprise=fields.get("categorie_entreprise"),
            contact_nom=fields.get("contact_nom"),
            contact_titre=fields.get("contact_titre"),
            contact_source=fields.get("contact_source"),
            contact_type=fields.get("contact_type"),
            raw_json=json.dumps(
                {"dgal": dgal, "sirene": sirene_data},
                ensure_ascii=False, default=str,
            ),
        )

    # SIRENE KO ou pas de retour → on retourne le match minimal DGAL-only
    return EnrichissementResult(
        source=source,
        source_id=source_id,
        enricher_version=ENRICHER_VERSION,
        marque_input=incident.get("marque"),
        query_used=f"agrement:{numero}",
        match_status="found",
        confidence=CONFIDENCE_AGREMENT,
        api_used="agrement_dgal",
        siret_siege=siret,
        raison_sociale=dgal.get("raison_sociale"),
        adresse=" ".join(p for p in [
            dgal.get("adresse"),
            dgal.get("code_postal"),
            dgal.get("commune"),
        ] if p),
        raw_json=json.dumps({"dgal": dgal}, ensure_ascii=False, default=str),
    )



def match_incident(
    incident: dict[str, Any],
    client: SireneClient,
    pappers: Optional[PappersClient] = None,
) -> EnrichissementResult:
    """
    Tente de matcher un incident avec une entreprise SIRENE,
    puis enrichit le contact via Pappers si disponible.

    Retourne un EnrichissementResult avec le match_status approprié.
    """
    source = incident["source"]
    source_id = incident["source_id"]
    marque_raw = incident.get("marque")

    # Étape 0 : si l'incident a une marque_salubrite (agrément DGAL CE 853/2004),
    # on tente le lookup direct vers SIRET avant le matching textuel par marque.
    # C'est plus fiable car nominatif et lié à l'établissement réel de production.
    via_agrement = _try_match_via_agrement(incident, client)
    if via_agrement is not None:
        return via_agrement

    # Étape 1 : normalisation marque
    query = normalize_marque(marque_raw)

    # Étape 2 : fallback distributeur si marque inutilisable
    fallback_used = False
    if query is None:
        query = normalize_distributeur(incident.get("distributeurs"))
        if query:
            fallback_used = True
            logger.debug(
                "Incident %s : marque inutilisable, fallback distributeur → %r",
                source_id, query,
            )

    # Étape 3 : pas de query exploitable → skipped
    if query is None:
        logger.info("Incident %s : aucun terme utilisable → skipped", source_id)
        return EnrichissementResult(
            source=source,
            source_id=source_id,
            enricher_version=ENRICHER_VERSION,
            marque_input=marque_raw,
            query_used=None,
            match_status="skipped",
            confidence=0.0,
            api_used="none",
        )

    # Étape 4 : appel SIRENE
    try:
        results = client.search(query, nombre=5)
    except SireneAPIError as exc:
        logger.error("Erreur SIRENE pour incident %s : %s", source_id, exc)
        return EnrichissementResult(
            source=source,
            source_id=source_id,
            enricher_version=ENRICHER_VERSION,
            marque_input=marque_raw,
            query_used=query,
            match_status="not_found",
            confidence=0.0,
            api_used="sirene",
        )

    # Étape 5 : sélection du meilleur candidat
    if not results:
        logger.info("Incident %s : aucun résultat SIRENE pour %r", source_id, query)
        return EnrichissementResult(
            source=source,
            source_id=source_id,
            enricher_version=ENRICHER_VERSION,
            marque_input=marque_raw,
            query_used=query,
            match_status="not_found",
            confidence=0.0,
            api_used="sirene",
        )

    best, confidence = _best_candidate(query, results)

    if confidence >= CONFIDENCE_FOUND:
        match_status = "found"
    elif confidence >= CONFIDENCE_AMBIGUOUS:
        match_status = "ambiguous"
    else:
        match_status = "not_found"

    if match_status == "not_found":
        logger.info(
            "Incident %s : confidence %.2f trop faible pour %r (meilleur: %s)",
            source_id, confidence, query,
            (best or {}).get("nom_complet", "?"),
        )
        return EnrichissementResult(
            source=source,
            source_id=source_id,
            enricher_version=ENRICHER_VERSION,
            marque_input=marque_raw,
            query_used=query,
            match_status="not_found",
            confidence=confidence,
            api_used="sirene",
            raw_json=json.dumps(
                {"query": query, "top_candidate": best}, ensure_ascii=False
            ),
        )

    fields = extract_company_fields(best)
    siren = fields.get("siren")

    logger.info(
        "Incident %s → %s [%s] confidence=%.2f status=%s",
        source_id,
        fields.get("raison_sociale"),
        siren,
        confidence,
        match_status,
    )

    # Enrichissement contact : Pappers en priorité si clé dispo, sinon contact SIRENE
    # Dans les deux cas, on cherche d'abord un profil cible (qualité/supply/conformité),
    # puis on tombe back sur un dirigeant exécutif si aucun profil cible n'est trouvé.
    contact_nom = fields.get("contact_nom")
    contact_titre = fields.get("contact_titre")
    contact_source = fields.get("contact_source")
    contact_type = fields.get("contact_type")
    api_used = "sirene"

    if siren and pappers is not None:
        pappers_contact = _enrich_contact_pappers(siren, pappers)
        if pappers_contact.get("contact_nom"):
            contact_nom = pappers_contact["contact_nom"]
            contact_titre = pappers_contact["contact_titre"]
            contact_type = pappers_contact.get("contact_type")
            contact_source = pappers_contact["contact_source"]
            api_used = "sirene+pappers"
            logger.debug(
                "Incident %s : contact Pappers → %s (%s) [type=%s]",
                source_id, contact_nom, contact_titre, contact_type,
            )

    logger.info(
        "Incident %s : contact=%s type=%s",
        source_id, contact_nom or "aucun", contact_type or "-",
    )

    return EnrichissementResult(
        source=source,
        source_id=source_id,
        enricher_version=ENRICHER_VERSION,
        marque_input=marque_raw,
        query_used=query,
        match_status=match_status,
        confidence=confidence,
        siren=siren,
        siret_siege=fields.get("siret_siege"),
        raison_sociale=fields.get("raison_sociale"),
        forme_juridique=fields.get("forme_juridique"),
        code_naf=fields.get("code_naf"),
        libelle_naf=fields.get("libelle_naf"),
        adresse=fields.get("adresse"),
        effectif_tranche=fields.get("effectif_tranche"),
        categorie_entreprise=fields.get("categorie_entreprise"),
        contact_nom=contact_nom,
        contact_titre=contact_titre,
        contact_source=contact_source,
        contact_type=contact_type,
        api_used=api_used,
        raw_json=json.dumps(best, ensure_ascii=False),
    )
