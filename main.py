"""FastAPI entrypoint that wires the crawler router and exposes health checks."""

from fastapi import FastAPI

from router import router


# Single FastAPI instance reused across ASGI servers/tests.
app = FastAPI(title="NJU Crawler Service", version="1.0.0")
app.include_router(router)


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
	uvicorn.run(app, host="0.0.0.0", port=8000)
