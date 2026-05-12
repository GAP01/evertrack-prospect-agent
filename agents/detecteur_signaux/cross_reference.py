"""
Cross-référence entre signaux faibles (signaux.sqlite) et
rappels officiels (incidents.sqlite).

Objectif : pour chaque signal détecté, identifier si un incident
officiel correspond — utile pour :
  1. Valider la précision du détecteur (a posteriori)
  2. Calculer le lead time (combien de jours d'avance vs rappel officiel)
  3. Relier les deux vues dans le dashboard

Score de match (0-1) calculé sur 4 dimensions pondérées :
  - brand_match       (0.40) : fuzzy similarity marque ↔ marque
  - symptom_match     (0.30) : pathogène commun (listeria, salmonelle…)
  - product_match     (0.20) : fuzzy similarity produit ↔ sous_categorie/motif
  - date_proximity    (0.10) : décroissance gaussienne, max à J0

Seuils :
  - score ≥ 0.70  → match fort  (lien affiché en priorité)
  - score ≥ 0.50  → match possible
  - score <  0.50 → ignoré
"""

from __future__ import annotations

import logging
import math
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Buckets de source qu'on ne crossref pas avec les incidents.
# Cas signalconso_volume : pas de marque/produit/symptôme exploitable
# pour matcher un incident RappelConso. Cf. cadrage v2 §7.
VOLUME_BUCKETS_SKIP_CROSSREF = frozenset({"signalconso_volume"})


# --- Seuils et pondérations ----------------------------------------------

MATCH_THRESHOLD_STRONG = 0.70
MATCH_THRESHOLD_POSSIBLE = 0.50
DEFAULT_WINDOW_DAYS = 30

WEIGHT_BRAND = 0.40
WEIGHT_SYMPTOM = 0.30
WEIGHT_PRODUCT = 0.20
WEIGHT_DATE = 0.10


# --- Familles de pathogènes (pour termes génériques) ---------------------

_BACTERIAL_PATHOGENS = [
    "listeria", "listeriose", "monocytogenes",
    "salmonel", "salmonella",
    "escherichia coli", "e.coli", "e. coli", "stec", "enterohemorra",
    "botulisme", "clostridium botulinum", "clostridium",
    "staphylo", "staphylococc",
    "campylobacter",
    "shigella",
    "yersinia",
    "bacillus cereus",
]

_VIRAL_PATHOGENS = [
    "norovirus",
    "hepatite a", "hepatite virale",
    "rotavirus",
]

# Métaux lourds / contaminants chimiques (non pathogènes mais critiques)
_HEAVY_METALS = [
    "cadmium", "plomb", "mercure", "arsenic", "chrome hexavalent",
    "nickel",
]

_CHEMICAL_CONTAMINANTS = _HEAVY_METALS + [
    "pesticide", "phytosanitaire", "residu",
    "dioxine", "pcb", "hydrocarbure",
    "acrylamide", "furane",
    "nitrite", "nitrate",
    "oligo-element", "oligo element",
    "metaux lourds", "metaux traces", "elements traces metalliques",
]

_ALL_PATHOGENS = _BACTERIAL_PATHOGENS + _VIRAL_PATHOGENS


# --- Mapping symptôme → mots-clés incident.risques ----------------------

# La clé = symptome du signal (produit par le LLM).
# La valeur = liste de patterns à chercher dans incident.risques + motif (lower, sans accents).
# Ordre important : les clés spécifiques AVANT les génériques (matchées en premier).
SYMPTOM_TO_KEYWORDS: dict[str, list[str]] = {
    # Pathogènes spécifiques (priorité haute)
    "listeria": ["listeria", "listeriose", "monocytogenes"],
    "salmonelle": ["salmonel", "salmonella"],
    "e.coli": ["escherichia coli", "e.coli", "e. coli", "stec", "enterohemorra", "shu"],
    "botulisme": ["botulisme", "clostridium botulinum"],
    "norovirus": ["norovirus"],
    "hepatite a": ["hepatite a", "hepatite virale"],
    "staphylocoque": ["staphylo", "staphylococc"],
    "campylobacter": ["campylobacter"],

    # Toxines & contaminations chimiques
    "toxine": ["toxine"],
    "histamine": ["histamine"],
    "moisissure": ["moisissure", "levures"],

    # Métaux lourds — familles spécifiques ET génériques
    # Les clés génériques (ex: "contamination au cadmium") mappent vers le
    # métal seul car les motifs RappelConso citent souvent "cadmium" en isolation.
    "cadmium": ["cadmium"],
    "plomb": ["plomb"],
    "mercure": ["mercure"],
    "arsenic": ["arsenic"],
    "contamination au cadmium": ["cadmium"],
    "contamination au plomb": ["plomb"],
    "contamination au mercure": ["mercure"],
    "contamination chimique": _CHEMICAL_CONTAMINANTS,
    "metaux lourds": _HEAVY_METALS,
    "contamination metaux": _HEAVY_METALS,
    "contaminant chimique": _CHEMICAL_CONTAMINANTS,
    "residus chimiques": _CHEMICAL_CONTAMINANTS,
    "pesticides": ["pesticide", "phytosanitaire", "residu"],
    "pesticide": ["pesticide", "phytosanitaire", "residu"],
    "phytosanitaires": ["pesticide", "phytosanitaire", "residu"],

    # Allergènes
    "allergène non déclaré": [
        "allergene", "allergen", "mention obligatoire", "etiquetage allergen",
    ],

    # Corps étrangers spécifiques (avant le générique)
    "corps étranger (verre)": ["verre"],
    "corps étranger (plastique)": ["plastique"],
    "corps étranger (métal)": ["metal"],
    "corps étranger": ["corps etranger", "inertes", "fragment"],

    # TERMES GÉNÉRIQUES → mappent vers familles de pathogènes
    # Matchés uniquement si aucun terme spécifique n'a hit avant.
    "contamination bacterienne": _BACTERIAL_PATHOGENS,
    "contamination microbiologique": _ALL_PATHOGENS,
    "bacterie": _BACTERIAL_PATHOGENS,
    "bacteries": _BACTERIAL_PATHOGENS,
    "pathogene": _ALL_PATHOGENS,
    "infection bacterienne": _BACTERIAL_PATHOGENS,
    "toxi-infection": _BACTERIAL_PATHOGENS + ["toxine", "staphylo"],
    "toxi infection": _BACTERIAL_PATHOGENS + ["toxine", "staphylo"],
    "intoxication alimentaire": _BACTERIAL_PATHOGENS + ["toxine", "histamine", "intoxication"],
    "risque sanitaire": _ALL_PATHOGENS + ["toxine", "histamine"],
    "contamination": _ALL_PATHOGENS + ["toxine", "corps etranger", "allergene"],
}


# --- Mapping produit → catégorie RappelConso -----------------------------

# Si le signal.produit contient un terme de la clé, on boost product_match
# à 0.85 quand l'incident.sous_categorie contient un des mots de la valeur.
PRODUCT_CATEGORY_HINTS: dict[str, list[str]] = {
    # Laitier
    "fromage": ["lait", "laitier", "fromage"],
    "yaourt": ["lait", "laitier"],
    "lait": ["lait", "laitier"],
    "creme": ["lait", "laitier"],
    "beurre": ["lait", "laitier"],
    # Viandes / charcuterie
    "viande": ["viande", "charcuterie"],
    "jambon": ["viande", "charcuterie"],
    "saucisson": ["viande", "charcuterie"],
    "saucisse": ["viande", "charcuterie"],
    "coppa": ["viande", "charcuterie"],
    "terrine": ["viande", "charcuterie"],
    "pate": ["viande", "charcuterie"],
    "lardons": ["viande", "charcuterie"],
    "boeuf": ["viande"],
    "porc": ["viande"],
    "poulet": ["viande", "volaille"],
    "volaille": ["viande", "volaille"],
    "dinde": ["viande", "volaille"],
    # Poisson / fruits de mer
    "poisson": ["peche", "poisson", "aquaculture"],
    "saumon": ["peche", "poisson"],
    "thon": ["peche", "poisson"],
    "huitre": ["peche", "aquaculture"],
    "crevette": ["peche", "aquaculture"],
    "moule": ["peche", "aquaculture"],
    # Plats préparés
    "salade": ["plats prepares", "snacks", "fruits et legumes"],
    "taboule": ["plats prepares", "snacks"],
    "pizza": ["plats prepares", "snacks"],
    "sandwich": ["plats prepares", "snacks"],
    "tzatziki": ["plats prepares", "snacks"],
    "houmous": ["plats prepares", "snacks"],
    # Bébé
    "bebe": ["infantile", "bebe"],
    "infantile": ["infantile", "bebe"],
    # Boulangerie / pâtisserie
    "biscuit": ["biscuits", "gateaux"],
    "gateau": ["biscuits", "gateaux"],
    "pain": ["boulangerie", "pain"],
    "brioche": ["boulangerie"],
    # Fruits & légumes
    "legume": ["fruits et legumes"],
    "fruit": ["fruits et legumes"],
    "pomme": ["fruits et legumes"],
    "poire": ["fruits et legumes"],
    "avocat": ["fruits et legumes"],
    "avocats": ["fruits et legumes"],
    "tomate": ["fruits et legumes"],
    "carotte": ["fruits et legumes"],
    "banane": ["fruits et legumes"],
    "raisin": ["fruits et legumes"],
    "orange": ["fruits et legumes"],
    "citron": ["fruits et legumes"],
    "fraise": ["fruits et legumes"],
    "framboise": ["fruits et legumes"],
    "champignon": ["fruits et legumes"],
    # Céréales / féculents
    "pate alimentaire": ["cereales"],
    "pates": ["cereales"],
    "riz": ["cereales"],
    "farine": ["cereales"],
    # Boissons
    "jus": ["boissons"],
    "eau": ["boissons"],
    "biere": ["boissons"],
    "vin": ["boissons"],
    # Condiments
    "sauce": ["condiments", "epicerie"],
    "vinaigre": ["condiments"],
    "huile": ["huiles", "condiments"],
}


# Marques à ignorer pour le brand_match (trop génériques)
GENERIC_BRANDS = {
    "", "sans marque", "sans marques", "non renseigne", "non renseigné",
    "inconnu", "inconnue", "-", "n/a", "na", "divers",
}


# --- Utilitaires ---------------------------------------------------------

def _strip_accents(s: str) -> str:
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _norm(s: Optional[str]) -> str:
    if not s:
        return ""
    s = _strip_accents(s.lower())
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s[:10]).date()
    except (ValueError, TypeError):
        return None


# --- Composantes du score -----------------------------------------------

def brand_similarity(signal_brand: Optional[str], incident_brand: Optional[str]) -> float:
    """Fuzzy match entre marques. 0 si l'une est vide ou générique."""
    s = _norm(signal_brand)
    i = _norm(incident_brand)
    if not s or not i:
        return 0.0
    if s in GENERIC_BRANDS or i in GENERIC_BRANDS:
        return 0.0
    # SequenceMatcher.ratio = 2M / T, 0..1
    ratio = SequenceMatcher(None, s, i).ratio()
    # Bonus substring : une marque courte contenue dans l'autre
    if len(s) >= 3 and s in i:
        ratio = max(ratio, 0.85)
    elif len(i) >= 3 and i in s:
        ratio = max(ratio, 0.85)
    return ratio


def brand_or_distributor_similarity(
    signal_brand: Optional[str],
    incident_brand: Optional[str],
    incident_distributeurs: Optional[str],
) -> float:
    """
    Retourne le MAX entre :
      - similarité(signal.marque, incident.marque)
      - similarité(signal.marque, incident.distributeurs)

    Utile car le signal presse parle souvent du DISTRIBUTEUR (Carrefour,
    Leclerc, Super U) alors que RappelConso enregistre la MARQUE FABRICANT
    (Océan Délices, Scapmaree, …) avec Carrefour dans distributeurs.

    Le champ distributeurs peut contenir plusieurs enseignes séparées par
    ¤, |, ou virgule — le substring match les traite comme un seul blob.
    """
    direct = brand_similarity(signal_brand, incident_brand)
    if not incident_distributeurs:
        return direct
    # On cherche signal.marque comme substring du blob distributeurs.
    # Ex: "Carrefour" in "carrefour" → bonus 0.85
    via_distrib = brand_similarity(signal_brand, incident_distributeurs)
    return max(direct, via_distrib)


def symptom_match(
    signal_symptome: Optional[str],
    incident_motif: Optional[str],
    incident_risques: Optional[str],
) -> float:
    """
    1.0 si on trouve un pattern du symptôme signal dans motif+risques.
    0.0 sinon. Binaire pour garder une logique simple.
    """
    if not signal_symptome:
        return 0.0
    key = signal_symptome.strip().lower()
    # Normalise la clé pour matcher SYMPTOM_TO_KEYWORDS
    key_norm = _norm(key)
    patterns = None
    for sym_key, pats in SYMPTOM_TO_KEYWORDS.items():
        if _norm(sym_key) in key_norm or key_norm in _norm(sym_key):
            patterns = pats
            break
    if patterns is None:
        # Fallback : utilise le symptome lui-même comme pattern
        patterns = [_norm(key)]

    blob = _norm(f"{incident_motif or ''} {incident_risques or ''}")
    if not blob:
        return 0.0

    for p in patterns:
        if p and _norm(p) in blob:
            return 1.0
    return 0.0


def product_similarity(
    signal_produit: Optional[str],
    incident_sous_cat: Optional[str],
    incident_motif: Optional[str],
) -> float:
    """
    Similarité produit signal vs sous_categorie + motif de l'incident.

    Stratégie :
    1. Match direct (substring) sur sous_cat ou motif → 0.85
    2. Hint sémantique via PRODUCT_CATEGORY_HINTS (ex: "fromage" → "lait et
       produits laitiers") → 0.85
    3. Fuzzy SequenceMatcher en dernier recours
    """
    p = _norm(signal_produit)
    if not p:
        return 0.0

    best = 0.0
    for target in (incident_sous_cat, incident_motif):
        t = _norm(target)
        if not t:
            continue
        # 1. Substring direct (ex: "raclette" ⊂ "fromages à raclette")
        if p in t or t in p:
            best = max(best, 0.85)
            continue
        # 3. SequenceMatcher
        r = SequenceMatcher(None, p, t).ratio()
        best = max(best, r)

    # 2. Hint sémantique : chercher un terme du produit dans les hints,
    #    puis vérifier que la catégorie de l'incident contient un des mots attendus.
    cat_norm = _norm(incident_sous_cat)
    if cat_norm:
        for product_hint, cat_keywords in PRODUCT_CATEGORY_HINTS.items():
            if product_hint in p:
                for kw in cat_keywords:
                    if kw in cat_norm:
                        best = max(best, 0.85)
                        break
                if best >= 0.85:
                    break

    return best


def date_proximity(
    signal_date: Optional[datetime],
    incident_date: Optional[date],
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> float:
    """
    Décroissance gaussienne : 1.0 à J0, ~0.37 à window_days, ~0 à 2*window_days.

    Retourne 0 si une des dates manque ou si hors fenêtre (±2*window).
    """
    if signal_date is None or incident_date is None:
        return 0.0
    s_date = signal_date.date() if isinstance(signal_date, datetime) else signal_date
    delta_days = abs((s_date - incident_date).days)
    if delta_days > 2 * window_days:
        return 0.0
    # exp(-(x/σ)²) avec σ = window_days
    sigma = max(1, window_days)
    return math.exp(-((delta_days / sigma) ** 2))


def lead_time_days(
    signal_date: Optional[datetime],
    incident_date: Optional[date],
) -> Optional[int]:
    """
    Délai en jours entre signal et incident officiel.
    Positif  → signal avant incident (early warning)
    Négatif  → signal après incident (couverture presse du rappel)
    """
    if signal_date is None or incident_date is None:
        return None
    s_date = signal_date.date() if isinstance(signal_date, datetime) else signal_date
    return (incident_date - s_date).days


# --- Calcul global du score ---------------------------------------------

@dataclass
class MatchScore:
    score: float
    brand: float
    symptom: float
    product: float
    date: float
    lead_time: Optional[int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 3),
            "brand_match": round(self.brand, 3),
            "symptom_match": round(self.symptom, 3),
            "product_match": round(self.product, 3),
            "date_proximity": round(self.date, 3),
            "lead_time_days": self.lead_time,
        }


def compute_match(
    signal: dict[str, Any],
    incident: dict[str, Any],
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> MatchScore:
    """
    Calcule le score de match pour une paire (signal, incident).

    Attend les lignes SQLite brutes (dict). Les dates sont des strings ISO.
    """
    b = brand_or_distributor_similarity(
        signal.get("marque"),
        incident.get("marque"),
        incident.get("distributeurs"),
    )
    s = symptom_match(
        signal.get("symptome"),
        incident.get("motif"),
        incident.get("risques"),
    )
    p = product_similarity(
        signal.get("produit"),
        incident.get("sous_categorie"),
        incident.get("motif"),
    )
    sig_dt = _parse_date(signal.get("detected_at"))
    inc_dt = _parse_date(incident.get("date_publication"))
    d = date_proximity(sig_dt, inc_dt, window_days=window_days)

    total = (
        WEIGHT_BRAND * b
        + WEIGHT_SYMPTOM * s
        + WEIGHT_PRODUCT * p
        + WEIGHT_DATE * d
    )

    return MatchScore(
        score=total,
        brand=b,
        symptom=s,
        product=p,
        date=d,
        lead_time=lead_time_days(sig_dt, inc_dt),
    )


# --- Recherche de candidats (lecture DB) ---------------------------------

def _load_incidents(
    incidents_db: Path,
    reference_date: Optional[date] = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> list[dict[str, Any]]:
    """
    Charge les incidents dans la fenêtre ±2*window_days autour de reference_date.
    Si reference_date=None, charge tout.
    """
    if not Path(incidents_db).exists():
        return []
    with sqlite3.connect(incidents_db) as conn:
        conn.row_factory = sqlite3.Row
        if reference_date:
            from datetime import timedelta
            delta = timedelta(days=2 * window_days)
            dmin = (reference_date - delta).isoformat()
            dmax = (reference_date + delta).isoformat()
            rows = conn.execute(
                """
                SELECT source, source_id, source_url, marque, sous_categorie,
                       motif, risques, date_publication, distributeurs
                FROM incidents
                WHERE date_publication BETWEEN ? AND ?
                ORDER BY date_publication DESC
                """,
                (dmin, dmax),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT source, source_id, source_url, marque, sous_categorie,
                       motif, risques, date_publication, distributeurs
                FROM incidents
                ORDER BY date_publication DESC
                """
            ).fetchall()
    return [dict(r) for r in rows]


def find_matches_for_signal(
    signal: dict[str, Any],
    incidents_db: Path,
    min_score: float = MATCH_THRESHOLD_POSSIBLE,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> list[dict[str, Any]]:
    """
    Retourne la liste triée des incidents matchant un signal,
    score >= min_score. Chaque item = incident + match_score dict.
    """
    sig_date = _parse_date(signal.get("detected_at"))
    candidates = _load_incidents(incidents_db, sig_date, window_days)

    out: list[dict[str, Any]] = []
    for inc in candidates:
        match = compute_match(signal, inc, window_days=window_days)
        if match.score >= min_score:
            out.append({
                **inc,
                "match": match.as_dict(),
            })
    out.sort(key=lambda x: x["match"]["score"], reverse=True)
    return out


def find_matches_for_incident(
    incident: dict[str, Any],
    signaux_db: Path,
    min_score: float = MATCH_THRESHOLD_POSSIBLE,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> list[dict[str, Any]]:
    """
    Retourne la liste triée des signaux matchant un incident, score >= min_score.
    """
    if not Path(signaux_db).exists():
        return []

    inc_date = _parse_date(incident.get("date_publication"))
    from datetime import timedelta
    if inc_date:
        delta = timedelta(days=2 * window_days)
        dmin = (inc_date - delta).isoformat()
        dmax = (inc_date + delta).isoformat()

    with sqlite3.connect(signaux_db) as conn:
        conn.row_factory = sqlite3.Row
        if inc_date:
            rows = conn.execute(
                """
                SELECT * FROM signaux
                WHERE detected_at BETWEEN ? AND ?
                ORDER BY detected_at DESC
                """,
                (dmin, dmax + "T23:59:59"),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM signaux").fetchall()
    signaux = [dict(r) for r in rows]

    out: list[dict[str, Any]] = []
    for sig in signaux:
        match = compute_match(sig, incident, window_days=window_days)
        if match.score >= min_score:
            out.append({
                **sig,
                "match": match.as_dict(),
            })
    out.sort(key=lambda x: x["match"]["score"], reverse=True)
    return out


# --- Pré-calcul de toutes les correspondances ---------------------------

def _find_incident_by_rappelconso_url(
    rc_url: str,
    incidents_by_fiche: dict[str, tuple[str, str]],
) -> Optional[tuple[str, str]]:
    """
    Cherche l'incident correspondant à une URL rappel.conso.gouv.fr.
    Le matching se fait sur le numéro de fiche (ex: '22094').
    Retourne (source, source_id) ou None.
    """
    import re as _re
    m = _re.search(r"fiche-rappel/(\d+)", rc_url)
    if not m:
        return None
    fiche_num = m.group(1)
    return incidents_by_fiche.get(fiche_num)


def _build_incidents_by_fiche_index(
    incidents_db: Path,
) -> dict[str, tuple[str, str]]:
    """Index des incidents par numéro de fiche extrait de source_url.
    { '22094': ('rappelconso', '2026-04-0257'), ... }"""
    import re as _re
    out: dict[str, tuple[str, str]] = {}
    with sqlite3.connect(incidents_db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT source, source_id, source_url FROM incidents "
            "WHERE source_url IS NOT NULL AND source_url != ''"
        ).fetchall()
    for r in rows:
        m = _re.search(r"fiche-rappel/(\d+)", r["source_url"] or "")
        if m:
            out[m.group(1)] = (r["source"], r["source_id"])
    return out


def recompute_all_matches(
    signaux_db: Path,
    incidents_db: Path,
    min_score: float = MATCH_THRESHOLD_POSSIBLE,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> dict[str, Any]:
    """
    Recalcule et stocke toutes les correspondances dans signal_incident_matches.

    Après le calcul algorithmique, auto-confirme les matches dont la source
    contient un lien direct vers la fiche RappelConso correspondante.

    Stratégie : on vide la table (en préservant les matches user_confirmed=1)
    puis on remplit. Les matches ne sont pas coûteux (<1s pour 100x100).
    """
    from .storage import SignalStorage  # import local pour éviter cycle

    if not Path(signaux_db).exists():
        return {"ok": False, "error": f"signaux_db absent : {signaux_db}"}
    if not Path(incidents_db).exists():
        return {"ok": False, "error": f"incidents_db absent : {incidents_db}"}

    storage = SignalStorage(signaux_db)  # assure la table matches

    # Charge tous les signaux
    with sqlite3.connect(signaux_db) as conn:
        conn.row_factory = sqlite3.Row
        signaux = [dict(r) for r in conn.execute("SELECT * FROM signaux").fetchall()]

    # Charge tous les incidents (pas de filtre de date ici, window_days trop restrictif
    # pour un pré-calcul global — la proximity s'en charge via score)
    incidents = _load_incidents(incidents_db, reference_date=None)

    n_matches = 0
    n_strong = 0
    total_pairs = 0
    # Préserve les matches validés humainement
    storage.clear_matches(keep_confirmed=True)

    computed_at = datetime.utcnow().isoformat()

    n_skipped_volume = 0
    for sig in signaux:
        # Skip les buckets sans marque exploitable (volumes anormaux).
        if sig.get("source_type") in VOLUME_BUCKETS_SKIP_CROSSREF:
            n_skipped_volume += 1
            continue
        for inc in incidents:
            total_pairs += 1
            m = compute_match(sig, inc, window_days=window_days)
            if m.score < min_score:
                continue
            storage.upsert_match(
                signal_id=sig["signal_id"],
                incident_source=inc["source"],
                incident_source_id=inc["source_id"],
                score=m.score,
                brand_match=m.brand,
                symptom_match=m.symptom,
                product_match=m.product,
                date_proximity=m.date,
                lead_time_days=m.lead_time,
                computed_at=computed_at,
            )
            n_matches += 1
            if m.score >= MATCH_THRESHOLD_STRONG:
                n_strong += 1

    # Auto-confirmation via liens directs RappelConso dans les articles
    url_confirmed = 0
    try:
        incidents_idx = _build_incidents_by_fiche_index(incidents_db)
        for signal_id, rc_url in storage.all_signals_with_rappelconso_urls():
            match = _find_incident_by_rappelconso_url(rc_url, incidents_idx)
            if match:
                inc_source, inc_source_id = match
                storage.confirm_match(signal_id, inc_source, inc_source_id)
                url_confirmed += 1
    except Exception as exc:
        logger.warning("Auto-confirm URL échoué : %s", exc)

    return {
        "ok": True,
        "signaux_count": len(signaux),
        "signaux_skipped_volume_bucket": n_skipped_volume,
        "incidents_count": len(incidents),
        "pairs_evaluated": total_pairs,
        "matches_stored": n_matches,
        "strong_matches": n_strong,
        "url_auto_confirmed": url_confirmed,
        "min_score": min_score,
        "window_days": window_days,
        "computed_at": computed_at,
    }
