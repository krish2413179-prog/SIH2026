"""
Seed script — creates the first admin user and initial OrgUnit.

Run inside the Docker container after migrations:
    docker compose exec api python seed_admin.py

Or from the host if Python 3.11 + deps are available:
    python seed_admin.py
"""

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@lea.gov.in")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@123456")  # change on first login
ORG_UNIT_NAME = os.environ.get("ORG_UNIT_NAME", "Cyber Crime Division")


async def seed():
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select
    from app.auth.models import User, UserRole, OrgUnit
    from app.auth.service import pwd_context
    from app.db.base import Base

    database_url = os.environ["DATABASE_URL"]
    connect_args = {}
    if "asyncpg" in database_url:
        connect_args = {
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
        }
    engine = create_async_engine(database_url, echo=False, connect_args=connect_args)

    async with engine.begin() as conn:
        # Ensure tables exist (migrations should have run, but just in case)
        pass

    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        # Check if admin already exists
        result = await db.execute(select(User).where(User.email == ADMIN_EMAIL))
        existing = result.scalars().first()
        if existing:
            print(f"Admin user {ADMIN_EMAIL!r} already exists — skipping.")
            return

        # Create OrgUnit
        org_result = await db.execute(select(OrgUnit).where(OrgUnit.name == ORG_UNIT_NAME))
        org_unit = org_result.scalars().first()
        if not org_unit:
            org_unit = OrgUnit(name=ORG_UNIT_NAME)
            db.add(org_unit)
            await db.flush()
            print(f"Created OrgUnit: {ORG_UNIT_NAME}")

        # Create admin user
        admin = User(
            email=ADMIN_EMAIL,
            password_hash=pwd_context.hash(ADMIN_PASSWORD),
            role=UserRole.admin,
            org_unit_id=org_unit.id,
        )
        db.add(admin)
        await db.commit()
        print(f"[+] Admin user created: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
        print("  -> Change this password after first login!")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
