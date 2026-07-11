from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select

from src.auth.models import User, Workspace
from src.shared.database import SessionLocal

DEV_WORKSPACE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEV_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


async def seed() -> None:
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.id == DEV_USER_ID))
        if user is None:
            session.add(User(id=DEV_USER_ID, email="dev@local", name="Dev User"))

        workspace = await session.scalar(select(Workspace).where(Workspace.id == DEV_WORKSPACE_ID))
        if workspace is None:
            session.add(
                Workspace(
                    id=DEV_WORKSPACE_ID,
                    owner_id=DEV_USER_ID,
                    name="Dev Workspace",
                )
            )

        await session.commit()
        print("seeded")


if __name__ == "__main__":
    asyncio.run(seed())
