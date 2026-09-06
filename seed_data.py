import asyncio
import uuid
from app.db.session import AsyncSession, engine
from app.auth.models import OrgUnit, User, UserRole

async def seed_basic_data():
    async with AsyncSession(engine) as session:
        try:
            # Create default Org Unit
            org_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
            org = OrgUnit(id=org_id, name="LEA Central Unit")
            session.add(org)

            # Create default User
            user_id = uuid.UUID("165e9dfc-739a-419c-bc43-3be8d25afe92")
            user = User(
                id=user_id,
                email="investigator@lea.gov.in",
                password_hash="bcrypt_hash_placeholder",
                role=UserRole.investigator,
                org_unit_id=org_id,
            )
            session.add(user)

            await session.commit()
            print("✅ Successfully seeded default OrgUnit and User.")
        except Exception as e:
            await session.rollback()
            print(f"❌ Seeding failed: {e}")

if __name__ == "__main__":
    asyncio.run(seed_basic_data())
