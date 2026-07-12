"""Standalone durable record service for C19 chat records."""

from .app import create_app, create_app_from_env
from .config import RecordServiceSettings

__all__ = ["RecordServiceSettings", "create_app", "create_app_from_env"]
