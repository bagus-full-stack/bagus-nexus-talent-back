import asyncio

from sqlalchemy import select

from app.core.security import hash_password
from app.db.postgres import SessionLocal
from app.models.user import User, UserRole, UserStatus

ADMIN_EMAIL = "admin@nexustalent.local"
ADMIN_PASSWORD = "bagus_admin"


async def main():
    async with SessionLocal() as db:
        existing = await db.scalar(select(User).where(User.email == ADMIN_EMAIL))
        if existing:
            print(f"Un utilisateur existe déjà avec cet email : {existing.email}")
            return

        user = User(
            nom="Admin",
            email=ADMIN_EMAIL,
            mot_de_passe_hash=hash_password(ADMIN_PASSWORD),
            role=UserRole.ADMIN,
            statut=UserStatus.ACTIF,
        )
        db.add(user)
        await db.commit()
        print(f"Admin créé : {user.email} / mot de passe : {ADMIN_PASSWORD}")


asyncio.run(main())
