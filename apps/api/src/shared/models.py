"""
shared/models.py
----------------
Central registry for all ORM models.
Ensures all classes are discovered by SQLAlchemy before mapper configuration.
Import this module anywhere model registration is required (e.g. alembic/env.py, app/main.py).
"""
import src.auth.models
import src.ingestion.models
import src.research.models  # noqa: F401
