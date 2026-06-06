"""Round-trip test: insert a User, fetch it back, verify all columns work."""

import asyncio
import uuid

import pytest
from sqlalchemy import select

from flowforge.config import get_settings
from flowforge.db import create_engine, create_sessionmaker
from flowforge.models import User


@pytest.mark.asyncio
async def test_user_round_trip():
    """Insert a User and read it back. Proves the model + migration are correct."""

    engine = create_engine(get_settings())
    Session = create_sessionmaker(engine)

    # Use a unique email so reruns don't collide with the unique-index.
    unique_email = f"alice+{uuid.uuid4().hex[:8]}@example.com"

    try:
        # --- write ---
        async with Session() as session:
            new_user = User(
                email=unique_email,
                full_name="Alice",
            )

            session.add(new_user)
            await session.commit()

            inserted_id = new_user.id  # works because expire_on_commit=False

        # --- read (separate session, proves it was persisted, not just cached) ---
        async with Session() as session:
            stmt = select(User).where(User.email == unique_email)

            result = await session.execute(stmt)
            fetched = result.scalar_one()

        assert fetched.id == inserted_id
        assert fetched.email == unique_email
        assert fetched.full_name == "Alice"
        assert fetched.created_at is not None  # server_default fired

    finally:
        await engine.dispose()