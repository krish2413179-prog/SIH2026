import asyncio
import uuid
from app.db.session import AsyncSession, engine
from app.auth.models import OrgUnit, User, UserRole

async def fix_database():
    async with AsyncSession(engine) as session:
        try:
            # 1. Ensure OrgUnit exists
            org_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
            # Use merge to avoid UniqueViolation if it partially exists
            org = OrgUnit(id=org_id, name="LEA Central Unit")
            await session.merge(org)

            # 2. Ensure User exists
            user_id = uuid.UUID("165e9dfc-739a-419c-bc43-3be8d25afe92")
            user = User(
                id=user_id,
                email="investigator@lea.gov.in",
                password_hash="bcrypt_hash_placeholder",
                role=UserRole.investigator,
                org_unit_id=org_id,
            )
            await session.merge(user)

            await session.commit()
            print("✅ Database constraints fixed: OrgUnit and User are present.")
        except Exception as e:
            await session.rollback()
            print(f"❌ Fix failed: {e}")

if __name__ == "__main__":
    asyncio.run(fix_database())
