import asyncio
import hashlib
import io
import json
from datetime import datetime
from typing import List, Optional

from curl_cffi import requests as curl_requests
from PyPDF2 import PdfReader
from bs4 import BeautifulSoup
from docx import Document
from PIL import Image
import pytesseract
from urllib.parse import parse_qs, urljoin, urlparse
import re

from config import (
    DETAIL_SELECTORS,
    MAX_RETRIES,
    REQUEST_TIMEOUT,
    TARGET_SOURCES,
    TESSDATA_DIR,
    TESSERACT_CMD,
)
from models import Attachments, CrawlItem
from vector_client import vector_client
from storage import database

database.initialize()

import os
os.environ["TESSDATA_PREFIX"] = TESSDATA_DIR
pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

PAGINATION_PATTERN = re.compile(r"(list)(\d+)(\.htm)$", re.IGNORECASE)


ASYNC_HTTP = curl_requests.AsyncSession(impersonate="chrome120")


async def fetch_html(
    url: str,
    headers: dict,
    timeout: int = REQUEST_TIMEOUT,
    retries: int = MAX_RETRIES,
) -> str:
    """Fetch HTML with retry/backoff using curl_cffi's impersonation."""
    for attempt in range(retries):
        try:
            response = await ASYNC_HTTP.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.text
        except Exception as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"Failed to fetch {url} after {retries} attempts.") from exc
            wait_seconds = 1 + attempt
            print(f"[WARN] attempt {attempt + 1} for {url} failed: {exc}; retry in {wait_seconds}s.")
            await asyncio.sleep(wait_seconds)
    raise RuntimeError(f"Failed to fetch {url}")


async def download_binary(
    url: str,
    headers: dict,
    timeout: int = REQUEST_TIMEOUT,
    retries: int = MAX_RETRIES,
) -> Optional[bytes]:
    """Download binary assets (images, pdfs, docx) through the shared async session."""
    for attempt in range(retries):
        try:
            response = await ASYNC_HTTP.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.content
        except Exception as exc:
            if attempt == retries - 1:
                print(f"[WARN] failed to download binary {url}: {exc}")
                return None
            wait_seconds = 1 + attempt
            print(f"[WARN] download attempt {attempt + 1} for {url} failed: {exc}; retry in {wait_seconds}s.")
            await asyncio.sleep(wait_seconds)
    return None


def normalize_url(base_url: str, url_el) -> Optional[str]:
    """Turn relative, protocol-relative or absolute attributes into absolute URLs."""
    href = None
    if isinstance(url_el, str):
        href = url_el.strip()
    elif url_el is not None:
        href = (url_el.get("href") or url_el.get("src") or "").strip()

    if not href:
        return None

    parsed = urlparse(href)
    if parsed.scheme:
        return href
    if href.startswith("//"):
        base_scheme = urlparse(base_url).scheme or "https"
        return f"{base_scheme}:{href}"
    return urljoin(base_url, href)


def parse_list(html: str, selectors: dict, base_url: str) -> List[dict]:
    """Extract list-page entries using the provided CSS selectors."""
    soup = BeautifulSoup(html, "lxml")
    items = soup.select(selectors["item_container"])
    results = []
    for item in items:
        date_el = item.select_one(selectors["date"])
        title_el = item.select_one(selectors["title"])
        url_el = item.select_one(selectors["url"])
        type_el = item.select_one(selectors["type"])

        full_url = normalize_url(base_url, url_el)

        results.append(
            {
                "title": title_el.get_text(strip=True) if title_el else None,
                "date": date_el.get_text(strip=True) if date_el else None,
                "url": full_url,
                "type": type_el.get_text(strip=True) if type_el else None,
            }
        )
    return results


def build_paginated_urls(list_url: str, max_pages: int) -> List[str]:
    """Generate paginated list URLs like list1.htm, list2.htm, ... up to max_pages."""
    if max_pages <= 1:
        return [list_url]

    urls = [list_url]
    match = PAGINATION_PATTERN.search(list_url)
    for page in range(2, max_pages + 1):
        if match:
            prefix = list_url[: match.start()]
            suffix = match.group(3)
            urls.append(f"{prefix}list{page}{suffix}")
        else:
            separator = "&" if "?" in list_url else "?"
            urls.append(f"{list_url}{separator}page={page}")
    return urls


def parse_publish_time(date_str: Optional[str]) -> datetime:
    """Best-effort parse of date strings, defaulting to current UTC when absent."""
    if not date_str:
        return datetime.utcnow()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return datetime.utcnow()


def extract_text_content(soup: BeautifulSoup, selector_cfg: Optional[dict]) -> str:
    """Grab the textual portion of the detail page according to selector config."""
    if not selector_cfg:
        return ""
    container = soup.select_one(selector_cfg.get("item_container", ""))
    if not container:
        return ""
    content_selector = selector_cfg.get("content")
    if content_selector:
        nodes = container.select(content_selector)
        text_chunks = [node.get_text(" ", strip=True) for node in nodes if node]
    else:
        text_chunks = [container.get_text(" ", strip=True)]
    return "\n".join(filter(None, text_chunks))


async def perform_ocr_from_url(image_url: str, headers: dict) -> str:
    """Download an image and run pytesseract OCR if the executable is configured."""
    if not TESSERACT_CMD:
        return ""

    image_bytes = await download_binary(image_url, headers)
    if not image_bytes:
        return ""

    def _ocr() -> str:
        try:
            pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
            config_parts = []
            if TESSDATA_DIR:
                config_parts.append(f'--tessdata-dir "{TESSDATA_DIR}"')
            config = " ".join(config_parts) or None
            with Image.open(io.BytesIO(image_bytes)) as img:
                text = pytesseract.image_to_string(img, lang="chi_sim+eng", config=config)
            return text.strip()
        except (pytesseract.TesseractError, OSError) as exc:
            print(f"[WARN] OCR failed for {image_url}: {exc}")
            return ""

    return await asyncio.to_thread(_ocr)


async def extract_image_texts(
    soup: BeautifulSoup, selector_cfg: Optional[dict], base_url: str, headers: dict
) -> List[str]:
    """Collect OCR text for every image that matches the configured selector."""
    if not selector_cfg:
        return []
    container = soup.select_one(selector_cfg.get("item_container", ""))
    if not container:
        return []
    image_selector = selector_cfg.get("images")
    if not image_selector:
        return []
    texts: List[str] = []
    for img in container.select(image_selector):
        src = normalize_url(base_url, img.get("src"))
        if not src:
            continue
        ocr_text = await perform_ocr_from_url(src, headers)
        if ocr_text:
            texts.append(ocr_text)
    return texts


def parse_pdf_bytes(file_bytes: bytes) -> str:
    """Return concatenated text for all PDF pages (skipping empty extractions)."""
    reader = PdfReader(io.BytesIO(file_bytes))
    texts = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(filter(None, texts))


def parse_docx_bytes(file_bytes: bytes) -> str:
    """Join all paragraph texts from a DOCX binary payload."""
    document = Document(io.BytesIO(file_bytes))
    return "\n".join(p.text for p in document.paragraphs if p.text)


async def extract_file_texts(
    soup: BeautifulSoup,
    selector_cfg: Optional[dict],
    base_url: str,
    headers: dict,
    allowed_ext: tuple,
) -> List[Attachments]:
    """Download and parse attachment texts for the allowed extensions."""
    if not selector_cfg:
        return []
    container = soup.select_one(selector_cfg.get("item_container", ""))
    if not container:
        return []
    file_selector = selector_cfg.get("files")
    if not file_selector:
        return []

    attachments: List[Attachments] = []
    for link in container.select(file_selector):
        file_url = normalize_url(base_url, link)
        if not file_url:
            continue
        if not file_url.lower().endswith(allowed_ext):
            continue
        filename = link.get_text(strip=True) or "attachment"
        binary = await download_binary(file_url, headers)
        if not binary:
            continue

        if file_url.lower().endswith(".pdf"):
            text = await asyncio.to_thread(parse_pdf_bytes, binary)
            mime = "application/pdf"
        elif file_url.lower().endswith(".docx"):
            text = await asyncio.to_thread(parse_docx_bytes, binary)
            mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            continue

        attachments.append(Attachments(url=file_url, filename=filename, mime_type=mime, text=text))
    return attachments


async def extract_embedded_pdf_attachment(
    soup: BeautifulSoup, selector_cfg: Optional[dict], base_url: str, headers: dict
) -> List[Attachments]:
    """Handle sites that embed PDFs via viewer iframes instead of direct links."""
    if not selector_cfg:
        return []
    viewer_selector = selector_cfg.get("viewer")
    if not viewer_selector:
        return []
    iframe = soup.select_one(viewer_selector)
    if not iframe:
        return []
    src = iframe.get("src")
    if not src:
        return []
    full_src = normalize_url(base_url, src)
    if not full_src:
        return []
    parsed = urlparse(full_src)
    file_param = parse_qs(parsed.query).get("file")
    if not file_param:
        return []
    pdf_url = normalize_url(base_url, file_param[0])
    if not pdf_url:
        return []
    binary = await download_binary(pdf_url, headers)
    if not binary:
        return []
    text = await asyncio.to_thread(parse_pdf_bytes, binary)
    return [
        Attachments(
            url=pdf_url,
            filename=pdf_url.split("/")[-1],
            mime_type="application/pdf",
            text=text,
        )
    ]


def aggregate_content(text: str, image_texts: List[str], attachment_texts: List[str]) -> str:
    """Merge base content, OCR outputs, and attachment snippets into one blob."""
    chunks = [chunk for chunk in [text] if chunk]
    if image_texts:
        chunks.append("\n".join(image_texts))
    if attachment_texts:
        chunks.append("\n".join(attachment_texts))
    return "\n\n".join(chunks)


def build_attachment_text_snippet(attachment: Attachments) -> str:
    """Render human-friendly markers before attachment texts."""
    title = attachment.filename or attachment.url
    return f"【附件：{title}】\n{attachment.text or ''}"


def compute_sha256(*segments: Optional[str]) -> str:
    """Generate a deterministic identifier from the provided text segments."""
    payload = "\n".join(segment or "" for segment in segments)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def parse_detail_page(html: str, base_url: str, headers: dict) -> tuple[str, List[Attachments]]:
    """Parse a detail page and return aggregated text plus attachment metadata."""
    soup = BeautifulSoup(html, "lxml")
    text_content = extract_text_content(soup, DETAIL_SELECTORS.get("text_selector"))
    image_texts = await extract_image_texts(soup, DETAIL_SELECTORS.get("img_selector"), base_url, headers)
    pdf_attachments = await extract_file_texts(
        soup, DETAIL_SELECTORS.get("pdf_selector"), base_url, headers, allowed_ext=(".pdf",)
    )
    doc_attachments = await extract_file_texts(
        soup, DETAIL_SELECTORS.get("doc_selector"), base_url, headers, allowed_ext=(".docx",)
    )
    embedded_pdf = await extract_embedded_pdf_attachment(
        soup, DETAIL_SELECTORS.get("embedded_pdf_selector"), base_url, headers
    )

    attachments = pdf_attachments + doc_attachments + embedded_pdf
    attachment_texts = [build_attachment_text_snippet(att) for att in attachments if att.text]
    content = aggregate_content(text_content, image_texts, attachment_texts)
    return content, attachments


MAX_CONCURRENT_DETAIL_REQUESTS = 5


async def crawl_source(source_id: str) -> List[CrawlItem]:
    """Crawl a configured list page and return normalized CrawlItem records."""
    source_cfg = next((src for src in TARGET_SOURCES if src["id"] == source_id), None)
    if not source_cfg:
        raise ValueError(f"Unknown source id: {source_id}")

    max_pages = int(source_cfg.get("max_pages", 1))
    list_urls = build_paginated_urls(source_cfg["list_url"], max_pages)

    entries: List[dict] = []
    for page_number, list_url in enumerate(list_urls, start=1):
        try:
            list_html = await fetch_html(list_url, source_cfg["headers"])
        except RuntimeError as exc:
            print(f"[WARN] skip list page {list_url}: {exc}")
            continue
        page_entries = parse_list(list_html, source_cfg["selectors"], source_cfg["base_url"])
        if not page_entries:
            print(f"[INFO] list page {page_number} returned no entries")
        entries.extend(page_entries)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_DETAIL_REQUESTS)

    async def process_entry(entry: dict) -> Optional[CrawlItem]:
        detail_url = entry.get("url")
        if not detail_url:
            return None
        try:
            async with semaphore:
                detail_html = await fetch_html(detail_url, source_cfg["headers"])
        except RuntimeError as exc:
            print(f"[WARN] skip detail {detail_url}: {exc}")
            return None

        content, attachments = await parse_detail_page(detail_html, source_cfg["base_url"], source_cfg["headers"])
        content = content or ""

        item_id = compute_sha256(content.strip() or detail_url or "", detail_url)
        publish_time = parse_publish_time(entry.get("date"))

        exists = await asyncio.to_thread(database.record_exists, item_id)
        if exists:
            return None

        metadata = {
            "url": detail_url,
            "source_id": source_cfg["id"],
            "source_name": source_cfg["name"],
            "title": entry.get("title"),
            "publish_time": publish_time.isoformat(),
        }
        await asyncio.to_thread(vector_client.store_document, item_id, content, metadata)

        attachments_payload = None
        if attachments:
            attachment_dicts = []
            for attachment in attachments:
                data = attachment.dict()
                data["url"] = str(data.get("url") or "")
                attachment_dicts.append(data)
            attachments_payload = json.dumps(attachment_dicts, ensure_ascii=False)
        await asyncio.to_thread(
            database.insert_record,
            item_id,
            entry.get("title") or "",
            detail_url,
            publish_time.isoformat(),
            source_cfg["id"],
            source_cfg["name"],
            True,
            attachments_payload,
        )

        return CrawlItem(
            id=item_id,
            title=entry.get("title") or "",
            content=content,
            url=detail_url,
            publish_time=publish_time,
            source=source_cfg["name"],
            attachments=attachments or None,
            extra_meta={"category": entry.get("type")},
        )

    tasks = [process_entry(entry) for entry in entries]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    crawl_items: List[CrawlItem] = []
    for result in results:
        if isinstance(result, Exception):
            print(f"[WARN] detail task failed: {result}")
            continue
        if result:
            crawl_items.append(result)
    return crawl_items


def fetch_detail(parsed_lists, headers):
    raise NotImplementedError("fetch_detail is superseded by crawl_source.")
