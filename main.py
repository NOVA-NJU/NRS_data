"""FastAPI entrypoint that wires the crawler router and exposes health checks."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Optional

from fastapi import FastAPI

from config import AUTO_CRAWL_ENABLED, CRAWL_INTERVAL, CRAWLER_PORT, TARGET_SOURCES
from router import router
from services import crawl_source

logger = logging.getLogger(__name__)

# Single FastAPI instance reused across ASGI servers/tests.
app = FastAPI(title="NJU Crawler Service", version="1.0.0")
app.include_router(router)

_periodic_task: Optional[asyncio.Task] = None


async def _crawl_all_sources_once() -> None:
	"""Iterate through configured sources and run the crawler."""
	for source in TARGET_SOURCES:
		source_id = source["id"]
		try:
			await crawl_source(source_id)
			logger.info("Periodic crawl finished for source %s", source_id)
		except Exception as exc:  # noqa: BLE001
			logger.warning("Periodic crawl failed for source %s: %s", source_id, exc)


async def _periodic_crawl_loop() -> None:
	"""Background loop that triggers crawl jobs based on CRAWL_INTERVAL."""
	while True:
		await _crawl_all_sources_once()
		await asyncio.sleep(max(1, CRAWL_INTERVAL))


@app.on_event("startup")
async def _start_periodic_task() -> None:
	global _periodic_task
	if AUTO_CRAWL_ENABLED and _periodic_task is None:
		_periodic_task = asyncio.create_task(_periodic_crawl_loop())
		logger.info("Started periodic crawler task with interval %s seconds", CRAWL_INTERVAL)


@app.on_event("shutdown")
async def _stop_periodic_task() -> None:
	global _periodic_task
	if _periodic_task:
		_periodic_task.cancel()
		with contextlib.suppress(asyncio.CancelledError):
			await _periodic_task
		logger.info("Stopped periodic crawler task")
		_periodic_task = None


@app.get("/health")
async def health_check() -> dict:
	"""Lightweight health probe for liveness/readiness checks."""
	return {"status": "ok"}


def get_app() -> FastAPI:
	"""Provide the configured FastAPI app to external runners/tests."""
	return app


if __name__ == "__main__":
	import uvicorn

	# Running "python main.py" boots a local dev server.
	uvicorn.run(app, host="0.0.0.0", port=CRAWLER_PORT)
