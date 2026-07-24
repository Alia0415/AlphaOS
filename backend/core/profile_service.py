"""Application service for the SQLite-backed local user profile."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.core.store import Store
from backend.core.user_profile import (
    LOCAL_USER_ID,
    PERSONAL_DECISION_REQUIRED_FIELDS,
    UserInvestmentProfile,
    UserProfilePatch,
    UserProfilePut,
)


class UserProfileService:
    """Canonical profile operations for the hackathon's local single user.

    SQLite is the source of truth. The fixed ID is not an account identifier,
    does not support cross-device sync, and can be replaced by a login user ID.
    """

    def __init__(
        self,
        store: Store,
        profile_id: str = LOCAL_USER_ID,
    ) -> None:
        self.store = store
        self.profile_id = profile_id

    def get(self) -> UserInvestmentProfile | None:
        payload = self.store.get_user_profile(self.profile_id)
        return (
            UserInvestmentProfile.model_validate(payload)
            if payload is not None
            else None
        )

    def put(self, incoming: UserProfilePut) -> UserInvestmentProfile:
        existing = self.get()
        facts = incoming.model_dump(
            mode="python",
            exclude_computed_fields=True,
            exclude={"profile_version", "created_at", "updated_at"},
        )
        return self._save(facts, existing)

    def patch(self, incoming: UserProfilePatch) -> UserInvestmentProfile:
        existing = self.get()
        base = (
            existing.model_dump(mode="python", exclude_computed_fields=True)
            if existing is not None
            else UserInvestmentProfile().model_dump(
                mode="python", exclude_computed_fields=True
            )
        )
        changes = {
            name: getattr(incoming, name)
            for name in incoming.model_fields_set
        }
        base.update(changes)
        return self._save(base, existing)

    def delete(self) -> bool:
        return self.store.delete_user_profile(self.profile_id)

    def status(self) -> dict[str, Any]:
        profile = self.get()
        if profile is None:
            return {
                "profile_exists": False,
                "onboarding_completed": False,
                "action_required": "profile_onboarding_required",
                "missing_fields": list(PERSONAL_DECISION_REQUIRED_FIELDS),
                "profile_version": None,
                "profile_completeness": 0.0,
            }
        missing = profile.missing_fields(PERSONAL_DECISION_REQUIRED_FIELDS)
        return {
            "profile_exists": True,
            "onboarding_completed": profile.onboarding_completed,
            "action_required": (
                None
                if profile.onboarding_completed and not missing
                else "profile_update_required"
                if profile.onboarding_completed
                else "profile_onboarding_required"
            ),
            "missing_fields": missing,
            "profile_version": profile.profile_version,
            "profile_completeness": profile.profile_completeness,
        }

    def _save(
        self,
        values: dict[str, Any],
        existing: UserInvestmentProfile | None,
    ) -> UserInvestmentProfile:
        now = datetime.now(timezone.utc)
        values.update(
            {
                "profile_version": (
                    existing.profile_version + 1 if existing is not None else 1
                ),
                "created_at": existing.created_at if existing is not None else now,
                "updated_at": now,
            }
        )
        profile = UserInvestmentProfile.model_validate(values)
        payload = profile.model_dump(
            mode="json",
            exclude_computed_fields=True,
        )
        self.store.save_user_profile(
            profile_id=self.profile_id,
            profile_version=profile.profile_version,
            onboarding_completed=profile.onboarding_completed,
            profile=payload,
            created_at=profile.created_at.isoformat(),
            updated_at=profile.updated_at.isoformat(),
        )
        return profile
