"""ASGI entry point: ``uvicorn waltrix_api.asgi:app``."""

from .main import create_app

app = create_app()
