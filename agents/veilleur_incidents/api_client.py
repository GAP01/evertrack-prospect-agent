"""
Client minimal pour l'API RappelConso (Opendatasoft Explore v2.1).

Dataset : `rappelconso-v2-gtin-espaces` (V2 - V1 decommissionnee fin 2025).

Endpoints :
    GET /api/explore/v2.1/catalog/datasets/{dataset}                - metadata
    GET /api/explore/v2.1/catalog/datasets/{dataset}/records        - records
"""

from __future__ import annotations

import logging
from typing import Any, Iterator, Optional
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets"
DATASET_ID = "rappelconso-v2-gtin-espaces"
DEFAULT_TIMEOUT = 20
MAX_PAGE_SIZE = 100


class RappelConsoError(RuntimeError):
    """Erreur remontee par l'API avec son message detaille."""


class RappelConsoClient:
    def __init__(
        self,
        dataset_id: str = DATASET_ID,
        base_url: str = BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
        session: Optional[requests.Session] = None,
    ):
        self.dataset_id = dataset_id
        self.base_url = base_url
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "EverTrack-Veilleur/0.1")

    def _dataset_url(self) -> str:
        return f"{self.base_url}/{self.dataset_id}"

    def _records_url(self) -> str:
        return f"{self._dataset_url()}/records"

    def _get(self, url: str, params: Optional[dict] = None) -> dict[str, Any]:
        resp = self.session.get(url, params=params, timeout=self.timeout)
        logger.debug("GET %s -> %s", resp.url, resp.status_code)
        if resp.status_code >= 400:
            # Opendatasoft renvoie du JSON avec `message` et `error_code`.
            try:
                body = resp.json()
            except ValueError:
                body = {"raw": resp.text[:500]}
            raise RappelConsoError(
                f"HTTP {resp.status_code} on {resp.url}\n"
                f"API response: {body}"
            )
        return resp.json()

    def get_dataset_metadata(self) -> dict[str, Any]:
        """Retourne les metadonnees du dataset, incluant la liste des champs."""
        return self._get(self._dataset_url())

    def list_fields(self) -> list[dict[str, Any]]:
        """Liste condensee des champs (name + label + type)."""
        meta = self.get_dataset_metadata()
        # Le schema est dans dataset.fields
        fields = (
            meta.get("dataset", {}).get("fields")
            or meta.get("fields")
            or []
        )
        out = []
        for f in fields:
            out.append({
                "name": f.get("name"),
                "label": f.get("label"),
                "type": f.get("type"),
            })
        return out

    def fetch_page(
        self,
        limit: int = MAX_PAGE_SIZE,
        offset: int = 0,
        where: Optional[str] = None,
        order_by: Optional[str] = None,
        refine: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "limit": min(limit, MAX_PAGE_SIZE),
            "offset": offset,
        }
        if order_by:
            params["order_by"] = order_by
        if where:
            params["where"] = where

        if refine:
            params_list = list(params.items()) + [("refine", r) for r in refine]
            url = f"{self._records_url()}?{urlencode(params_list, doseq=True)}"
            return self._get(url)
        return self._get(self._records_url(), params=params)

    def iter_records(
        self,
        where: Optional[str] = None,
        refine: Optional[list[str]] = None,
        order_by: Optional[str] = None,
        max_records: Optional[int] = None,
        page_size: int = MAX_PAGE_SIZE,
    ) -> Iterator[dict[str, Any]]:
        fetched = 0
        offset = 0
        while True:
            limit = page_size
            if max_records is not None:
                remaining = max_records - fetched
                if remaining <= 0:
                    return
                limit = min(limit, remaining)

            payload = self.fetch_page(
                limit=limit, offset=offset,
                where=where, refine=refine, order_by=order_by,
            )
            results = payload.get("results", [])
            if not results:
                return
            for record in results:
                yield record
                fetched += 1
                if max_records is not None and fetched >= max_records:
                    return
            if len(results) < limit:
                return
            offset += limit
