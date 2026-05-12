"""
Diag rapide marque_salubrite après le fetch RappelConso patché.

Usage : python diag_agrements.py
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

DB = Path("data/incidents.sqlite")
if not DB.exists():
    print(f"[err] base introuvable : {DB.resolve()}")
    raise SystemExit(1)

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

print("=" * 60)
print("DIAG marque_salubrite")
print("=" * 60)

# Total
total = conn.execute("SELECT COUNT(1) FROM incidents").fetchone()[0]
n_explicit = conn.execute(
    "SELECT COUNT(1) FROM incidents WHERE marque_salubrite IS NOT NULL AND marque_salubrite != ''"
).fetchone()[0]
print(f"\n[1] Couverture : {n_explicit}/{total} incidents avec agrement ({100*n_explicit/max(total,1):.1f} %)")

# Échantillons
print("\n[2] 5 incidents avec agrement :")
for r in conn.execute(
    "SELECT source_id, marque, marque_salubrite, distributeurs FROM incidents "
    "WHERE marque_salubrite IS NOT NULL AND marque_salubrite != '' LIMIT 5"
).fetchall():
    print(f"    {r['source_id']:20s} marque={r['marque']!r:35s} agrement={r['marque_salubrite']!r}")

# Pour les incidents qui ont marque_salubrite=NULL, regarde si le pattern existe
# quand même dans raw_json (cas où l'API ne le sort pas en colonne mais dans le raw)
print("\n[3] Recherche pattern d'agrement caché dans raw_json (incidents avec marque_salubrite=NULL) :")
pat = re.compile(r"FR\s*\d{2}\.\d{3}\.\d{3}\.CE", re.I)
n_hidden = 0
samples = []
for r in conn.execute(
    "SELECT source_id, raw_json FROM incidents WHERE marque_salubrite IS NULL OR marque_salubrite = ''"
).fetchall():
    raw = r["raw_json"] or ""
    m = pat.search(raw)
    if m:
        n_hidden += 1
        if len(samples) < 5:
            samples.append((r["source_id"], m.group()))
print(f"    {n_hidden} incidents sans champ explicite mais avec pattern detectable")
for s in samples:
    print(f"    {s[0]} → {s[1]}")

# Stats sur la base agréments DGAL
print("\n[4] Base DGAL locale :")
dgal_db = Path("data/agrements_dgal.sqlite")
if dgal_db.exists():
    c2 = sqlite3.connect(dgal_db)
    n_dgal = c2.execute("SELECT COUNT(1) FROM agrements_dgal").fetchone()[0]
    print(f"    {n_dgal} etablissements en cache")
    c2.close()
else:
    print("    Base DGAL absente — lance d'abord :")
    print("    python -m enrichisseur_prospects.agrements_dgal refresh")

conn.close()
