"""Tiny mock server mimicking the vector service API for local testing."""
from __future__ import annotations

from typing import Dict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Mock Vector Service", version="0.1.0")


class DocumentPayload(BaseModel):
    document_id: str = Field(..., description="Unique identifier used as primary key")
    text: str = Field(..., description="Full document text to be embedded")
    metadata: Dict[str, str] = Field(default_factory=dict, description="Optional metadata blob")


_STORE: Dict[str, DocumentPayload] = {}


@app.post("/vectors/documents")
def store_document(payload: DocumentPayload) -> Dict[str, str]:
    """Persist a document in memory and return a status flag."""
    _STORE[payload.document_id] = payload
    return {"status": "stored", "document_id": payload.document_id}


@app.get("/vectors/documents/{document_id}")
def get_document(document_id: str) -> Dict[str, object]:
    if document_id not in _STORE:
        raise HTTPException(status_code=404, detail="document not found")
    payload = _STORE[document_id]
    return {"status": "found", "document": payload.dict()}


@app.delete("/vectors/documents")
def clear_documents() -> Dict[str, object]:
    count = len(_STORE)
    _STORE.clear()
    return {"status": "cleared", "deleted": count}

@app.get("/vectors/documents")
def list_documents():
    return {"documents": [payload.dict() for payload in _STORE.values()]}