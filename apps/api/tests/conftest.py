"""
tests/conftest.py
-----------------
Registers all ORM models before any test triggers SQLAlchemy mapper
configuration (e.g. ResearchRun's relationship() to Workspace resolves
only when src.auth.models has been imported).
"""

import src.shared.models  # noqa: F401
