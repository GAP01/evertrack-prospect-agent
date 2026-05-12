"""
Dashboard EverTrack — interface Streamlit.

Lancement (depuis `agents/`) :
    streamlit run dashboard/app.py

Variables d'environnement utiles :
    ANTHROPIC_API_KEY  (optionnel - active le scoring LLM)
    EVERTRACK_DATA_DIR (defaut: ./data, contient incidents.sqlite et scores.sqlite)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

# Permet de lancer `streamlit run dashboard/app.py` depuis agents/
# en garantissant que les modules `veilleur_incidents` et `evaluateur_severite`
# soient importables.
HERE = Path(__file__).resolve().parent
AGENTS_ROOT = HERE.parent
if str(AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENTS_ROOT))

from dashboard import actions, data_access  # noqa: E402


# --- Config ----------------------------------------------------------------

st.set_page_config(
    page_title="EverTrack — Veille incidents",
    page_icon=":mag:",
    layout="wide",
)

DATA_DIR = Path(os.environ.get("EVERTRACK_DATA_DIR", "data"))
INCIDENTS_DB = DATA_DIR / "incidents.sqlite"
SCORES_DB = DATA_DIR / "scores.sqlite"

# Mode demo : masque les actions de pipeline pour proteger la cle API
# (utile quand on partage l'UI via tunnel a un tiers).
DEMO_MODE = os.environ.get("EVERTRACK_DEMO_MODE", "").strip() in ("1", "true", "yes")

TIER_COLORS = {
    "critique": "#c0392b",
    "eleve":    "#e67e22",
    "modere":   "#f1c40f",
    "faible":   "#7f8c8d",
}
TIER_LABELS = {
    "critique": "Critique",
    "eleve":    "Eleve",
    "modere":   "Modere",
    "faible":   "Faible",
}


# --- Helpers UI ------------------------------------------------------------

def tier_badge(tier: str) -> str:
    color = TIER_COLORS.get(tier, "#7f8c8d")
    label = TIER_LABELS.get(tier, tier)
    return (
        f'<span style="background:{color};color:white;'
        f'padding:2px 8px;border-radius:10px;font-size:0.8em;'
        f'font-weight:600;">{label}</span>'
    )


def _truncate(text: str, n: int) -> str:
    if not text:
        return ""
    return text if len(text) <= n else text[: n - 1] + "…"


# --- Sidebar : actions de pipeline ----------------------------------------

with st.sidebar:
    st.title("EverTrack")
    st.caption("Veille incidents → prospection")

    s = data_access.stats(INCIDENTS_DB, SCORES_DB)
    st.metric("Incidents en base", s["incidents_total"])
    st.metric("Incidents scorés", s["scores_total"])
    if s["last_score_at"]:
        st.caption(f"Dernière éval : {s['last_score_at'][:19].replace('T', ' ')}")

    st.divider()

with st.sidebar:
    if DEMO_MODE:
        st.info(
            ":lock: **Mode démo** — actions désactivées. "
            "Lance le dashboard en local sans `EVERTRACK_DEMO_MODE` pour les ré-activer."
        )
    else:
        st.subheader("Actions")

        with st.form("fetch_form", clear_on_submit=False):
            st.markdown("**Récupérer les nouveaux incidents**")
            since_days = st.number_input("Fenêtre (jours)", min_value=1, max_value=90, value=7)
            max_records = st.number_input("Limite (0 = aucune)", min_value=0, max_value=500, value=0)
            cat_filter = st.text_input("Catégorie (vide = tous secteurs)", value="alimentation")
            submitted_fetch = st.form_submit_button("Récupérer", use_container_width=True)
            if submitted_fetch:
                with st.spinner("Appel RappelConso…"):
                    report = actions.trigger_fetch(
                        incidents_db=INCIDENTS_DB,
                        since_days=int(since_days),
                        categorie=(cat_filter or None),
                        max_records=int(max_records) or None,
                    )
                st.success(
                    f"Récupérés : {report['fetched']} | "
                    f"Nouveaux : {report['new']} | "
                    f"MAJ : {report['updated']}"
                )
                st.rerun()

        st.markdown("")
        with st.form("score_form", clear_on_submit=False):
            st.markdown("**Scorer les incidents**")
            use_llm = st.checkbox("Utiliser l'API Claude (sinon table mots-clés)", value=True)
            rescore = st.checkbox("Forcer le rescoring", value=False,
                                  help="Sinon on saute les incidents déjà scorés")
            max_score = st.number_input("Limite (0 = aucune)", min_value=0, max_value=500, value=0,
                                        key="score_max")
            submitted_score = st.form_submit_button("Scorer", use_container_width=True)
            if submitted_score:
                if use_llm and not os.environ.get("ANTHROPIC_API_KEY"):
                    st.warning("ANTHROPIC_API_KEY non définie — bascule auto sur la table mots-clés.")
                with st.spinner("Scoring en cours…"):
                    report = actions.trigger_score(
                        incidents_db=INCIDENTS_DB,
                        scores_db=SCORES_DB,
                        use_llm=use_llm,
                        rescore=rescore,
                        max_incidents=int(max_score) or None,
                    )
                st.success(
                    f"Scorés : {report['scored_now']} (sur {report['incidents_total']}, "
                    f"{report['skipped_already_scored']} déjà connus). "
                    f"LLM utilisé : {report['llm_used_count']}/{report['scored_now']}."
                )
                st.rerun()


# --- Main : top et filtres ------------------------------------------------

st.title("Top incidents par sévérité")

if not SCORES_DB.exists():
    st.info(
        "Aucun score en base. Utilise les actions dans la sidebar : "
        "**Récupérer** puis **Scorer**."
    )
    st.stop()

col_a, col_b, col_c, col_d = st.columns(4)
with col_a:
    tier_filter = st.selectbox(
        "Tier",
        options=["(tous)", "critique", "eleve", "modere", "faible"],
        index=0,
    )
with col_b:
    sous_cats = ["(toutes)"] + data_access.list_sous_categories(INCIDENTS_DB)
    sous_cat_filter = st.selectbox("Sous-catégorie", options=sous_cats, index=0)
with col_c:
    limit = st.number_input("Limite", min_value=5, max_value=200, value=25, step=5)
with col_d:
    st.write("")
    st.write("")
    if st.button("Rafraîchir", use_container_width=True):
        st.rerun()

rows = data_access.top_incidents(
    INCIDENTS_DB,
    SCORES_DB,
    limit=int(limit),
    tier=None if tier_filter == "(tous)" else tier_filter,
    sous_categorie=None if sous_cat_filter == "(toutes)" else sous_cat_filter,
)

if not rows:
    st.info("Aucun incident ne correspond aux filtres.")
    st.stop()


# Tableau cliquable : on selectionne une row pour afficher le detail.
import pandas as pd  # import tardif pour eviter le cout au boot si pas de data

table_data = []
for r in rows:
    inc = r["incident"]
    table_data.append({
        "Score": round(r["score"], 1),
        "Tier": r["tier"],
        "Date pub.": inc.get("date_publication") or "",
        "Marque": _truncate(inc.get("marque") or "—", 30),
        "Sous-catégorie": _truncate(inc.get("sous_categorie") or "—", 25),
        "Motif": _truncate(inc.get("motif") or "—", 80),
        "_source": r["source"],
        "_source_id": r["source_id"],
    })
df = pd.DataFrame(table_data)

st.markdown(f"**{len(rows)} incidents affichés** (classés par score décroissant)")

event = st.dataframe(
    df.drop(columns=["_source", "_source_id"]),
    use_container_width=True,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    column_config={
        "Score": st.column_config.NumberColumn(format="%.1f", width="small"),
        "Tier": st.column_config.TextColumn(width="small"),
        "Date pub.": st.column_config.TextColumn(width="small"),
    },
)

selected_rows = event.selection.rows if event and event.selection else []
if not selected_rows:
    st.caption("Clique sur une ligne pour voir le détail et le breakdown du score.")
    st.stop()

idx = selected_rows[0]
sel_source = table_data[idx]["_source"]
sel_id = table_data[idx]["_source_id"]


# --- Vue detail : breakdown du score et infos incident -------------------

st.divider()
st.subheader("Détail incident")

detail = data_access.get_incident_full(INCIDENTS_DB, SCORES_DB, sel_source, sel_id)
if not detail:
    st.error("Détail introuvable.")
    st.stop()

inc = detail["incident"]
score = detail["score"]

c1, c2 = st.columns([2, 1])

with c1:
    st.markdown(
        f"### {inc.get('marque') or '(marque non renseignée)'} "
        f"— *{inc.get('sous_categorie') or 'sous-catégorie inconnue'}*"
    )
    st.markdown(f"**Date de publication :** {inc.get('date_publication') or '?'}")
    st.markdown(f"**Catégorie :** {inc.get('categorie') or '?'}")
    st.markdown(f"**Nature juridique :** {inc.get('nature_juridique') or '?'}")
    st.markdown("**Motif :**")
    st.info(inc.get("motif") or "(non renseigné)")
    if inc.get("risques"):
        st.markdown("**Risques encourus :**")
        st.warning(inc.get("risques"))
    if inc.get("zone_geographique"):
        st.markdown(f"**Zone géographique :** {inc['zone_geographique']}")
    if inc.get("distributeurs"):
        st.markdown(f"**Distributeurs :** {inc['distributeurs']}")
    if inc.get("source_url"):
        st.link_button("📄 Voir la fiche RappelConso officielle", inc["source_url"])

with c2:
    if not score:
        st.warning("Cet incident n'est pas encore scoré.")
    else:
        st.markdown("#### Score global")
        st.markdown(
            f"<div style='font-size:3em;font-weight:700;'>{score['score']:.1f}/100</div>",
            unsafe_allow_html=True,
        )
        st.markdown(tier_badge(score["tier"]), unsafe_allow_html=True)
        st.caption(
            f"Scorer {score['scorer_version']} · "
            f"{'LLM Claude' if score['llm_used'] else 'Table mots-clés'} · "
            f"{score['scored_at'][:19].replace('T', ' ')}"
        )

        st.markdown("#### Décomposition")
        for d in score["dimensions"]:
            contribution = d["raw"] * d["weight"]
            with st.container(border=True):
                st.markdown(
                    f"**{d['name']}** "
                    f"<span style='color:#7f8c8d;'>(poids {int(d['weight']*100)}%)</span>",
                    unsafe_allow_html=True,
                )
                cprog, cval = st.columns([3, 1])
                with cprog:
                    st.progress(min(1.0, d["raw"] / 100.0))
                with cval:
                    st.markdown(
                        f"<div style='text-align:right;'>"
                        f"{d['raw']:.0f} → <strong>+{contribution:.1f}</strong>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                st.caption(d.get("rationale") or "")
