"""Instrument preservation profiles endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.exceptions import ResourceNotFoundError
from app.models.profiles import get_profile, list_profiles
from app.models.schemas import InstrumentProfile, ProfilesResponse

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get("", response_model=ProfilesResponse)
async def get_all_profiles() -> ProfilesResponse:
    """Return all configurable instrument preservation profiles."""
    return ProfilesResponse(profiles=list_profiles())


@router.get("/{profile_id}", response_model=InstrumentProfile)
async def get_single_profile(profile_id: str) -> InstrumentProfile:
    """Return a single instrument preservation profile by ID."""
    profile = get_profile(profile_id)
    if profile is None:
        raise ResourceNotFoundError(
            message=f"Instrument profile '{profile_id}' was not found.",
            details={"profile_id": profile_id},
        )
    return profile
