"""
auth/models.py
--------------
Purpose:    ORM models for User and Workspace — the top-level ownership boundary.
            Everything else (documents, runs) belongs to a workspace.
Dependencies: shared/database.py (Base), schema.md
Scope:      Model definitions only. Auth logic is a PRD Non-Goal for MVP;
            this module is intentionally thin so it's easy to fill in later.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.database import Base

if TYPE_CHECKING:
    from src.ingestion.models import Document
    from src.research.models import ConversationThread, ResearchRun


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # auth_id: external provider identifier (Clerk, Auth0, etc.) — stubbed for MVP
    auth_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    workspaces: Mapped[list[Workspace]] = relationship(back_populates="owner")


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped[User] = relationship(back_populates="workspaces")
    documents: Mapped[list[Document]] = relationship(back_populates="workspace")
    research_runs: Mapped[list[ResearchRun]] = relationship(back_populates="workspace")
    conversation_threads: Mapped[list[ConversationThread]] = relationship(back_populates="workspace")