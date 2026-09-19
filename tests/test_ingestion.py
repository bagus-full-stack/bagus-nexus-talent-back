from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.user import User, UserRole
from app.schemas.candidat import CandidatCV, ExperiencePro
from app.services.ingestion_service import compute_quality_status, compute_years_experience


def _exp(debut: str, fin: str | None) -> ExperiencePro:
    return ExperiencePro(
        poste="Développeur",
        date_debut=date.fromisoformat(debut),
        date_fin=date.fromisoformat(fin) if fin else None,
    )


def test_merge_intervals_overlapping_ranges_deduplicate_days():
    experiences = [
        _exp("2018-01-01", "2020-01-01"),
        _exp("2019-06-01", "2021-01-01"),  # overlaps the first
    ]

    years = compute_years_experience(experiences)

    assert years == pytest.approx(3.0, abs=0.05)


def test_merge_intervals_non_overlapping_ranges_sum():
    experiences = [
        _exp("2015-01-01", "2016-01-01"),
        _exp("2018-01-01", "2019-01-01"),
    ]

    years = compute_years_experience(experiences)

    assert years == pytest.approx(2.0, abs=0.05)


def test_low_confidence_field_gives_a_valider_status():
    candidat = CandidatCV(
        nom="Dupont",
        prenom="Jean",
        source_confiance={"nom": 0.9, "prenom": 0.9, "email": 0.4, "experiences": 0.8},
    )

    statut, champs_a_verifier = compute_quality_status(candidat)

    assert statut == "a_valider"
    assert "email" in champs_a_verifier


def test_all_confident_fields_give_ok_status():
    candidat = CandidatCV(
        nom="Dupont",
        prenom="Jean",
        source_confiance={"nom": 0.9, "prenom": 0.9, "email": 0.9, "experiences": 0.8},
    )

    statut, champs_a_verifier = compute_quality_status(candidat)

    assert statut == "ok"
    assert champs_a_verifier == []


async def _create_rh_user(db: AsyncSession) -> User:
    user = User(
        email="rh@example.com",
        nom="RH Interne",
        mot_de_passe_hash=hash_password("Passw0rd!"),
        role=UserRole.RH_INTERNE,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest.mark.asyncio
async def test_upload_rejects_bad_extension(client: AsyncClient, db_session: AsyncSession):
    await _create_rh_user(db_session)
    login = await client.post(
        "/api/v1/auth/login", json={"email": "rh@example.com", "password": "Passw0rd!"}
    )
    token = login.json()["access_token"]

    response = await client.post(
        "/api/v1/ingestion/upload",
        files={"files": ("cv.exe", b"not a real cv", "application/octet-stream")},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422
