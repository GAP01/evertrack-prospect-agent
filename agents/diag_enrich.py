"""
Diag impact agrement DGAL sur l'enrichissement prospects.

Compare :
  - Combien d'enrichissements 'found' au total
  - Combien sont passés par agrement_dgal vs sirene textuel
  - Confidence moyenne par api_used
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB = Path("data/enrichissements.sqlite")
if not DB.exists():
    print(f"[err] base introuvable : {DB.resolve()}")
    raise SystemExit(1)

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

print("=" * 60)
print("DIAG impact agrement DGAL sur enrichissement")
print("=" * 60)

# Distribution des api_used
print("\n[1] Distribution par api_used :")
for r in conn.execute(
    "SELECT api_used, COUNT(1) AS n, AVG(confidence) AS avg_conf "
    "FROM enrichissements GROUP BY api_used ORDER BY n DESC"
).fetchall():
    print(f"    {r['api_used']:30s} : {r['n']:4d} (conf moy {r['avg_conf']:.2f})")

# Distribution par status
print("\n[2] Distribution par match_status :")
for r in conn.execute(
    "SELECT match_status, COUNT(1) AS n FROM enrichissements GROUP BY match_status ORDER BY n DESC"
).fetchall():
    print(f"    {r['match_status']:20s} : {r['n']}")

# Échantillons agrement
print("\n[3] 5 prospects matchés via agrement DGAL :")
for r in conn.execute(
    "SELECT source_id, raison_sociale, contact_nom, contact_titre, confidence "
    "FROM enrichissements WHERE api_used LIKE 'agrement%' LIMIT 5"
).fetchall():
    contact = f"{r['contact_nom'] or '-'} ({r['contact_titre'] or '-'})"
    print(f"    {r['source_id']:20s} {r['raison_sociale'] or '?':40s} contact={contact} conf={r['confidence']:.2f}")

conn.close()
