"""
Orchestrateur principal de l'agent redacteur_outreach (Agent 5).

Assemble les 4 modules de la chaine :
  1. context_builder  -> collecte le contexte multi-base (incidents / scores /
                         enrichissements / signaux)
  2. pitch_loader     -> charge la config editeur (pitch.json)
  3. template_renderer-> produit le brouillon deterministe (fallback)
  4. llm_rewriter     -> reecrit optionnellement via Claude Haiku

Calcule le message_id (sha1 stable sur source|source_id), persiste le resultat
dans outreach.sqlite via OutreachStorage et retourne l'OutreachMessage.

Comportement idempotent par defaut : si un message existe deja pour
(source, source_id), il est retourne tel quel sans rappel LLM.
Passer force=True pour forcer la regeneration.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

from .context_builder import IncidentNotFoundError, build_context
from .llm_rewriter import rewrite as llm_rewrite
from .models import REDACTEUR_VERSION, OutreachMessage
from .pitch_loader import load_pitch
from .storage import OutreachStorage
from .template_renderer import render as render_template


class Redacteur:
    def __init__(
        self,
        storage: OutreachStorage,
        data_dir: str = "data",
        pitch_path: Optional[str] = None,
    ) -> None:
        self._storage = storage
        self._data_dir = data_dir
        self._pitch = load_pitch(pitch_path)

    def generate(
        self,
        source: str,
        source_id: str,
        *,
        canal: str = "email",
        no_llm: bool = False,
        force: bool = False,
    ) -> OutreachMessage:
        """
        Genere ou retourne un message d'outreach pour un incident.

        Comportement idempotent par defaut : si un message existe deja pour
        (source, source_id), il est retourne sans regeneration.

        Si force=True, regenere (INSERT OR REPLACE ecrase l'existant via save()).
        Si no_llm=True, saute l'etape LLM (utile sans cle ou en test).

        Raises:
            IncidentNotFoundError: si l'incident n'existe pas en base.
        """
        # 1. Idempotence : retourner l'existant sauf si force
        if not force:
            existing = self._storage.get_by_source(source, source_id)
            if existing is not None:
                return existing

        # 2. Assemblage du contexte — peut lever IncidentNotFoundError
        context = build_context(source, source_id, data_dir=self._data_dir)

        # 3. Rendu template deterministe (fallback garanti sans LLM)
        rendered_fallback = render_template(context, self._pitch)
        body_fallback = rendered_fallback["body"]
        objet_fallback = rendered_fallback["objet"]

        # 4. Reecriture LLM optionnelle
        if no_llm:
            rewrite_result: dict = {
                "body_md": body_fallback,
                "objet": objet_fallback,
                "llm_used": False,
                "reason": "no_llm_requested",
            }
        else:
            rewrite_result = llm_rewrite(body_fallback, context, self._pitch)

        # 5. Calcul du statut selon le resultat LLM
        status = self._determine_status(rewrite_result)

        # 6. Identifiant stable base sur (source, source_id)
        message_id = self._build_message_id(source, source_id)

        # 7. Construction et persistance du message
        # context_json en ASCII pur (ensure_ascii=True) pour la portabilite Windows
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        msg = OutreachMessage(
            message_id=message_id,
            source=source,
            source_id=source_id,
            canal=canal,
            objet=rewrite_result.get("objet") or objet_fallback,
            body_md=rewrite_result["body_md"],
            body_fallback=body_fallback,
            llm_used=bool(rewrite_result["llm_used"]),
            redacteur_version=REDACTEUR_VERSION,
            status=status,
            context_json=json.dumps(context, ensure_ascii=True, sort_keys=True),
            pitch_version=str(self._pitch.get("version", "0.0")),
            generated_at=now_iso,
            notes=rewrite_result.get("reason"),
        )

        # INSERT OR REPLACE dans OutreachStorage : ecrase l'existant si force=True.
        # Pas besoin de delete() explicite car save() utilise INSERT OR REPLACE.
        self._storage.save(msg)
        return msg

    def regenerate(self, message_id: str) -> OutreachMessage:
        """
        Force la regeneration d'un message existant a partir de son message_id.

        Raises:
            ValueError: si le message_id est inconnu en base.
        """
        existing = self._storage.get(message_id)
        if existing is None:
            raise ValueError(f"message_id {message_id!r} not found")
        return self.generate(
            existing.source,
            existing.source_id,
            canal=existing.canal,
            force=True,
        )

    @staticmethod
    def _build_message_id(source: str, source_id: str) -> str:
        """
        Identifiant stable sha1[:16] sur (source, source_id).

        Stable par construction : deux appels avec les memes arguments retournent
        toujours le meme identifiant, ce qui garantit l'idempotence INSERT OR REPLACE.
        Si une separation par version de redacteur etait souhaitable, il suffirait
        d'ajouter REDACTEUR_VERSION dans le hash.
        """
        raw = f"{source}|{source_id}".encode("utf-8")
        return hashlib.sha1(raw).hexdigest()[:16]

    @staticmethod
    def _determine_status(rewrite_result: dict) -> str:
        """
        Determine le statut du message selon l'issue de la reecriture LLM.

        Regles :
          - LLM utilise avec succes         -> "a_valider" (validation humaine obligatoire)
          - LLM skipe (no_api_key,
            anthropic_not_installed,
            no_llm_requested)               -> "brouillon" (brouillon deterministique OK)
          - Anomalie LLM (api_error,
            hallucination_detected,
            non_ascii_detected)             -> "a_valider" (humain doit verifier)
        """
        if rewrite_result.get("llm_used"):
            return "a_valider"
        reason = rewrite_result.get("reason")
        if reason in ("no_api_key", "anthropic_not_installed", "no_llm_requested"):
            return "brouillon"
        # Toute autre raison (api_error, hallucination_detected, non_ascii_detected…)
        # indique une anomalie : un humain doit inspecter avant usage.
        return "a_valider"
