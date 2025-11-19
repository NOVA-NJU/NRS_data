"""Shared Pydantic schemas for FastAPI input/output."""

from typing import List, Optional
from datetime import datetime

from pydantic import BaseModel, HttpUrl


class CrawlRequest(BaseModel):
    """Client payload that specifies which source id to crawl."""

    source: str


class Attachments(BaseModel):
    """Normalized representation of each attachment extracted from a detail page."""

    url: HttpUrl  # 下载链接
    filename: Optional[str] = None
    mime_type: Optional[str] = None
    text: Optional[str] = None  # 可能会有的 OCR 输出


class CrawlItem(BaseModel):
    """Single crawled article with aggregated text and metadata."""

    id: str
    title: str
    content: str
    url: HttpUrl
    publish_time: datetime
    source: str
    attachments: Optional[List[Attachments]] = None
    extra_meta: Optional[dict] = None  # 未来扩展


class ErrorResponse(BaseModel):
    """Standardized error payload returned by the API layer."""

    error: str
    code: str = "404"


class CrawlResponse(BaseModel):
    """Success envelope returned by /api/crawl."""

    code: str = "200"
    data: List[CrawlItem]