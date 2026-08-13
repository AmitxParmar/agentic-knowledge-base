import asyncio
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker

from src.auth.models import User, Workspace
from src.shared.database import engine


async def main():
    async_session = async_sessionmaker(engine)
    async with async_session() as session:
        # Create user
        user = User(id=uuid.UUID("00000000-0000-0000-0000-000000000000"), email="test@example.com", name="Test User")
        session.add(user)
        # Create workspace
        workspace = Workspace(id=uuid.UUID("00000000-0000-0000-0000-000000000000"), name="Test Workspace", owner_id=user.id)
        session.add(workspace)
        try:
            await session.commit()
            print("Created workspace and user")
        except Exception as e:
            print("Already exists?", e)

if __name__ == "__main__":
    asyncio.run(main())
