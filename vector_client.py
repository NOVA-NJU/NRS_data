"""Client for interacting with the external vector store service."""
from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from config import VECTOR_SERVICE


class VectorClient:
    """Simple HTTP client used to store deduplication hashes in NRS Vector."""

    def __init__(self) -> None:
        self.enabled: bool = bool(VECTOR_SERVICE.get("enabled", False))
        self.base_url: str = VECTOR_SERVICE.get("base_url", "").rstrip("/")
        self.timeout: int = int(VECTOR_SERVICE.get("timeout", 10))
        self.api_key: Optional[str] = VECTOR_SERVICE.get("api_key")

    def _build_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def store_document(self, document_id: str, text: str, metadata: Dict[str, Any]) -> bool:
        """Persist a document in the vector store.

        Returns True when the call succeeds, False otherwise.
        """
        if not self.enabled:
            return False
        if not self.base_url:
            print("[WARN] Vector service base_url is empty, skip storing document.")
            return False

        payload = {
            "document_id": document_id,
            "text": text,
            "metadata": metadata,
        }
        url = f"{self.base_url}/vectors/documents"
        try:
            response = requests.post(url, json=payload, headers=self._build_headers(), timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            status = data.get("status", "").lower()
            return status in {"stored", "queued", "updated"}
        except requests.RequestException as exc:
            print(f"[WARN] Failed to store document in vector service: {exc}")
            return False

    def document_exists(self, document_id: str) -> bool:
        """Check whether a document is already stored."""
        if not self.enabled or not self.base_url:
            return False
        url = f"{self.base_url}/vectors/documents/{document_id}"
        try:
            response = requests.get(url, headers=self._build_headers(), timeout=self.timeout)
            if response.status_code == 200:
                return True
            if response.status_code == 404:
                return False
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"[WARN] Failed to query document {document_id}: {exc}")
        return False

    def clear_documents(self) -> bool:
        """Request the vector service to delete all stored documents."""
        if not self.enabled or not self.base_url:
            return False
        url = f"{self.base_url}/vectors/documents"
        try:
            response = requests.delete(url, headers=self._build_headers(), timeout=self.timeout)
            response.raise_for_status()
            return True
        except requests.RequestException as exc:
            print(f"[WARN] Failed to clear vector documents: {exc}")
            return False


vector_client = VectorClient()
