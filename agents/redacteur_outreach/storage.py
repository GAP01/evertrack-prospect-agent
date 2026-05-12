"""
Persistance SQLite des messages outreach generes (Agent 5).

Une seule table `messages` — un row par message, identifie par `message_id`.
La connexion est persistante (passee au constructeur) pour supporter
`":memory:"` dans les tests et eviter d'ouvrir/fermer une connexion par
operation en production.
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from .models import OutreachMessage, STATUS_CHOICES


_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    message_id          TEXT PRIMARY KEY,
    source              TEXT NOT NULL,
    source_id           TEXT NOT NULL,
    canal               TEXT NOT NULL DEFAULT 'email',
    objet               TEXT,
    body_md             TEXT,
    body_fallback       TEXT,
    llm_used            INTEGER NOT NULL DEFAULT 0,
    redacteur_version   TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'brouillon',
    context_json        TEXT,
    pitch_version       TEXT,
    generated_at        TEXT,
    validated_at        TEXT,
    sent_at             TEXT,
    notes               TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_source ON messages (source, source_id);
CREATE INDEX IF NOT EXISTS idx_messages_status ON messages (status);
"""

_MIGRATIONS: list[str] = []


class OutreachStorage:
    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema(self._conn)
        self._migrate(self._conn)

    # --- Schema & migrations ---------------------------------------------

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(_SCHEMA)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        for stmt in _MIGRATIONS:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass

    # --- Helper ----------------------------------------------------------

    def _row_to_message(self, row: sqlite3.Row) -> OutreachMessage:
        return OutreachMessage(
            message_id=row["message_id"],
            source=row["source"],
            source_id=row["source_id"],
            canal=row["canal"],
            objet=row["objet"],
            body_md=row["body_md"],
            body_fallback=row["body_fallback"],
            llm_used=bool(row["llm_used"]),
            redacteur_version=row["redacteur_version"],
            status=row["status"],
            context_json=row["context_json"],
            pitch_version=row["pitch_version"],
            generated_at=row["generated_at"],
            validated_at=row["validated_at"],
            sent_at=row["sent_at"],
            notes=row["notes"],
        )

    # --- Ecriture --------------------------------------------------------

    def save(self, msg: OutreachMessage) -> None:
        """INSERT OR REPLACE — idempotent sur message_id."""
        self._conn.execute(
            """
            INSERT OR REPLACE INTO messages
            (message_id, source, source_id, canal, objet, body_md,
             body_fallback, llm_used, redacteur_version, status,
             context_json, pitch_version, generated_at, validated_at,
             sent_at, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                msg.message_id,
                msg.source,
                msg.source_id,
                msg.canal,
                msg.objet,
                msg.body_md,
                msg.body_fallback,
                int(msg.llm_used),
                msg.redacteur_version,
                msg.status,
                msg.context_json,
                msg.pitch_version,
                msg.generated_at,
                msg.validated_at,
                msg.sent_at,
                msg.notes,
            ),
        )
        self._conn.commit()

    def set_status(
        self,
        message_id: str,
        status: str,
        *,
        validated_at: Optional[str] = None,
        sent_at: Optional[str] = None,
    ) -> None:
        """Met a jour le statut et les timestamps associes."""
        if status not in STATUS_CHOICES:
            raise ValueError(
                f"Statut invalide: {status!r}. Valeurs acceptees: {STATUS_CHOICES}"
            )
        fields = ["status = ?"]
        params: list[object] = [status]
        if validated_at is not None:
            fields.append("validated_at = ?")
            params.append(validated_at)
        if sent_at is not None:
            fields.append("sent_at = ?")
            params.append(sent_at)
        params.append(message_id)
        self._conn.execute(
            f"UPDATE messages SET {', '.join(fields)} WHERE message_id = ?",
            params,
        )
        self._conn.commit()

    def delete(self, message_id: str) -> bool:
        """Supprime le message. Retourne True si une ligne a ete supprimee."""
        cur = self._conn.execute(
            "DELETE FROM messages WHERE message_id = ?", (message_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    # --- Lecture ---------------------------------------------------------

    def get(self, message_id: str) -> Optional[OutreachMessage]:
        row = self._conn.execute(
            "SELECT * FROM messages WHERE message_id = ?", (message_id,)
        ).fetchone()
        return self._row_to_message(row) if row else None

    def get_by_source(
        self, source: str, source_id: str
    ) -> Optional[OutreachMessage]:
        """Retourne le premier message correspondant a (source, source_id).

        Utile pour verifier l'idempotence avant generation : si un message
        existe deja pour cet incident, l'orchestrateur peut l'ignorer ou le
        regenerer selon --reenrich.
        """
        row = self._conn.execute(
            """
            SELECT * FROM messages
            WHERE source = ? AND source_id = ?
            ORDER BY generated_at DESC NULLS LAST
            LIMIT 1
            """,
            (source, source_id),
        ).fetchone()
        return self._row_to_message(row) if row else None

    def list_by_status(self, status: str) -> list[OutreachMessage]:
        rows = self._conn.execute(
            "SELECT * FROM messages WHERE status = ? ORDER BY generated_at DESC NULLS LAST",
            (status,),
        ).fetchall()
        return [self._row_to_message(r) for r in rows]

    def list_all(self, limit: Optional[int] = None) -> list[OutreachMessage]:
        sql = "SELECT * FROM messages ORDER BY generated_at DESC NULLS LAST"
        params: tuple[object, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_message(r) for r in rows]

    def count_by_status(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) n FROM messages GROUP BY status"
        ).fetchall()
        return {r["status"]: r["n"] for r in rows}

    # --- Cycle de vie ----------------------------------------------------

    def close(self) -> None:
        self._conn.close()
