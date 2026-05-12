"""
Diag rapide pour le bucket signalconso_volume.

Usage : python diag_volumes.py

Affiche :
  1. Nombre de signaux volume en base
  2. Quelques exemples (signal_id, status, score, source_name)
  3. Statut de la table signaux_sources (pour voir si le contenu JSON est bien stocké)
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB = Path("data/signaux.sqlite")
if not DB.exists():
    print(f"[err] base introuvable : {DB.resolve()}")
    raise SystemExit(1)

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

print("=" * 60)
print("DIAG bucket signalconso_volume")
print("=" * 60)

# 1. Compte total
n_total = conn.execute(
    "SELECT COUNT(*) FROM signaux WHERE source_type = 'signalconso_volume'"
).fetchone()[0]
print(f"\n[1] Signaux 'signalconso_volume' en base : {n_total}")

# 2. Tous les source_types existants en base, pour repère
print("\n[2] Distribution des source_type en base :")
for r in conn.execute(
    "SELECT source_type, COUNT(*) AS n FROM signaux GROUP BY source_type"
).fetchall():
    print(f"    {r['source_type']:30s} : {r['n']}")

# 3. Exemples si y'en a
if n_total > 0:
    print("\n[3] 3 derniers signaux volume (ordre detected_at DESC) :")
    for r in conn.execute(
        """
        SELECT signal_id, status, score, source_name, detected_at, score_breakdown
        FROM signaux
        WHERE source_type = 'signalconso_volume'
        ORDER BY detected_at DESC
        LIMIT 3
        """
    ).fetchall():
        print(f"    - {r['signal_id']}")
        print(f"      status={r['status']}, score={r['score']}, source_name={r['source_name']}")
        print(f"      detected_at={r['detected_at']}")
        try:
            bd = json.loads(r['score_breakdown'] or "{}")
            print(f"      breakdown: z_mod={bd.get('z_mod')}, count_actuel={bd.get('count_actuel')}")
        except (ValueError, TypeError):
            pass

    print("\n[4] Sources liées (signaux_sources) :")
    for r in conn.execute(
        """
        SELECT ss.signal_id, ss.source_url, LENGTH(ss.contenu) as n_contenu
        FROM signaux_sources ss
        JOIN signaux s ON s.signal_id = ss.signal_id
        WHERE s.source_type = 'signalconso_volume'
        LIMIT 5
        """
    ).fetchall():
        print(f"    - {r['signal_id']} | url={r['source_url']} | contenu={r['n_contenu']}b")
else:
    print("\n[3] Aucun signal volume — pipeline n'a rien produit.")
    print("    Causes probables :")
    print("    a) WHERE catégorie ne matche aucune ligne ODS (encoding accents/apostrophes)")
    print("    b) Pas de pic réel cette semaine au-dessus du seuil z_mod >= 3.5")
    print("    c) Les couples (cat, dept) ont une médiane baseline < 5")

conn.close()
