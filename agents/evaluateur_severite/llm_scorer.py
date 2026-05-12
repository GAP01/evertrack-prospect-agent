"""
Scoring du risque sanitaire via Claude Haiku (Anthropic API).

Strategie a deux niveaux :
- Si la cle ANTHROPIC_API_KEY est presente et le SDK installe -> appel LLM.
- Sinon, on bascule sur une table de mots-cles (fallback deterministe), pour
  garder l'agent fonctionnel sans dependance reseau et a cout zero.

Le LLM doit retourner un JSON strict :
    {"score": int 0-100, "rationale": str <= 200 chars, "label": str court}
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

from .models import DimensionScore

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """Tu es un expert en securite sanitaire et en epidemiologie alimentaire.

Ta tache : noter sur 0-100 la GRAVITE INTRINSEQUE du risque sanitaire d'un incident produit (rappel, retrait, alerte). Tu ne juges PAS l'ampleur de la diffusion ni le nombre de personnes touchees - uniquement la dangerosite du danger lui-meme pour une personne exposee.

Bareme de reference :
- 90-100 : risque vital frequent ou eleve (botulisme, listeria chez personnes a risque, contamination radioactive, allergene non declare grave)
- 70-89  : risque grave necessitant souvent une hospitalisation (salmonelle, E. coli pathogene, intoxication aigue)
- 50-69  : risque moyen pouvant necessiter consultation medicale (histamine elevee, levures inadequates, corps etrangers tranchants)
- 30-49  : risque faible ou inconfort (residus phytosanitaires legerement au-dessus des seuils, defauts d'etiquetage allergene mineur)
- 0-29   : risque negligeable ou purement reglementaire (defauts cosmetiques, etiquetage non sanitaire)

Reponds STRICTEMENT en JSON valide, sans texte autour, exactement ce schema :
{"score": <int 0-100>, "rationale": "<phrase de 1-2 lignes en francais>", "label": "<2-3 mots>"}

Pas de markdown, pas de bloc de code, juste le JSON."""


USER_TEMPLATE = """Incident a noter :
- Categorie : {categorie}
- Sous-categorie : {sous_categorie}
- Motif du rappel : {motif}
- Risques encourus : {risques}

Retourne le JSON."""


# --- Fallback deterministe -------------------------------------------------

# Table calibree sur les pathogenes/dangers les plus frequents en agro.
# Le score est applique au max sur les mots-cles trouves.
SANITARY_KEYWORDS = [
    # 90-100 : risque vital
    (95, "Botulisme - risque vital", ["botulisme", "clostridium botulinum"]),
    (92, "Listeria - risque grave (femmes enceintes, immunodeprimes)",
        ["listeria", "listeriose", "monocytogenes"]),
    (90, "Allergene non declare - risque anaphylactique",
        ["allergene non declare", "allergen non declare", "arachide non mention",
         "fruits a coque non mention"]),
    (88, "Contamination chimique grave / metaux lourds",
        ["radioactiv", "plomb", "mercure", "cadmium", "dioxine"]),
    # 70-89 : risque grave
    (85, "E. coli pathogene - risque SHU enfant",
        ["escherichia coli", "e. coli", "stec ", "enterohemorra", "shu"]),
    (80, "Salmonellose - risque eleve",
        ["salmonel", "salmonella"]),
    (75, "Norovirus / hepatite A - risque infectieux",
        ["norovirus", "hepatite a", "hepatite virale"]),
    (72, "Toxine staphylococcique",
        ["staphylocoque", "entérotoxine staph"]),
    # 50-69 : risque moyen
    (60, "Histamine elevee - intoxication aigue",
        ["histamine"]),
    (60, "Corps etranger tranchant",
        ["verre", "metal", "fragment de metal", "corps etranger tranchant",
         "fragments de plastique"]),
    (55, "Levures / moisissures inadequates",
        ["levures", "moisissure"]),
    # 30-49 : risque faible
    (40, "Residus phytosanitaires au-dessus des seuils",
        ["phytosanitaire", "pesticide", "residus de produits"]),
    (35, "Etiquetage allergene incomplet",
        ["etiquetage", "mention allergen", "mention obligatoire"]),
    # 0-29 : risque negligeable
    (20, "Defaut cosmetique ou pratique",
        ["defaut cosmetique", "defaut emballage"]),
]


def _fallback_score(incident: dict[str, Any]) -> tuple[int, str, str]:
    """Score sans LLM via la table de mots-cles. Retourne (score, rationale, label)."""
    blob = " ".join(filter(None, [
        (incident.get("motif") or "").lower(),
        (incident.get("risques") or "").lower(),
    ]))
    if not blob.strip():
        return 30, "Aucun motif exploitable, defaut prudent", "indetermine"

    best = (0, "", "")
    for score, label, keywords in SANITARY_KEYWORDS:
        if any(k in blob for k in keywords):
            if score > best[0]:
                best = (score, label, label.split(" - ")[0].lower())

    if best[0] == 0:
        return 30, f"Motif non reconnu par la table : '{blob[:80]}...'", "non classe"
    return best[0], best[1], best[2]


# --- Appel Claude API ------------------------------------------------------

def _call_claude_api(incident: dict[str, Any], model: str) -> Optional[dict]:
    """Tente d'appeler l'API Claude. Retourne le dict parse ou None si echec."""
    try:
        import anthropic  # type: ignore
    except ImportError:
        logger.warning("Le SDK anthropic n'est pas installe. Fallback table mots-cles.")
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY absente. Fallback table mots-cles.")
        return None

    client = anthropic.Anthropic(api_key=api_key)
    user_msg = USER_TEMPLATE.format(
        categorie=incident.get("categorie") or "(non renseigne)",
        sous_categorie=incident.get("sous_categorie") or "(non renseigne)",
        motif=incident.get("motif") or "(non renseigne)",
        risques=incident.get("risques") or "(non renseigne)",
    )

    try:
        msg = client.messages.create(
            model=model,
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as exc:
        logger.warning("Appel Claude echoue : %s. Fallback table mots-cles.", exc)
        return None

    text = "".join(getattr(b, "text", "") for b in msg.content).strip()

    # Extraction du JSON (defensif : on cherche les premieres et dernieres accolades)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        logger.warning("Reponse LLM sans JSON detectable : %r", text[:200])
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        logger.warning("JSON LLM invalide (%s) : %r", exc, text[:200])
        return None

    score = data.get("score")
    if not isinstance(score, (int, float)) or not (0 <= score <= 100):
        logger.warning("Score LLM hors borne ou invalide : %r", score)
        return None

    return {
        "score": int(score),
        "rationale": str(data.get("rationale", ""))[:300],
        "label": str(data.get("label", ""))[:60],
    }


# --- Interface publique ----------------------------------------------------

def score_risque_sanitaire(
    incident: dict[str, Any],
    use_llm: bool = True,
    model: str = "claude-haiku-4-5-20251001",
) -> tuple[DimensionScore, bool]:
    """
    Score la dimension 'risque sanitaire' d'un incident.

    Retourne (DimensionScore, llm_used: bool).
    Poids fixe a 50% du score global (le facteur dominant).
    """
    if use_llm:
        result = _call_claude_api(incident, model)
        if result is not None:
            rationale = result["rationale"] or result["label"] or "(LLM)"
            return DimensionScore(
                "risque_sanitaire",
                float(result["score"]),
                0.50,
                f"[LLM] {rationale}",
            ), True

    # Fallback
    score, rationale, _label = _fallback_score(incident)
    return DimensionScore(
        "risque_sanitaire",
        float(score),
        0.50,
        f"[regles] {rationale}",
    ), False
