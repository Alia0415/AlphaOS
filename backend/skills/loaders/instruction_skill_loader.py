"""Load allowlisted instruction skills without executing their contents."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from backend.skills.contracts import SkillSpec


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUNTIME_DIRECTORY = ".runtime_skills"
DEFAULT_MAX_TEXT_LENGTH = 100_000


class SkillUnavailableError(RuntimeError):
    """Raised when an approved skill is not installed or cannot be verified."""


class LoadedInstructionSkill(BaseModel):
    """Bounded text and provenance loaded from one approved skill."""

    skill_id: str
    instructions: str
    references: dict[str, str] = Field(default_factory=dict)
    provenance: dict[str, Any]
    truncated: bool = False


class RuntimeSkillLocator:
    """Resolve only lock-file-backed paths below ``QUANTSKILLS_HOME``."""

    def __init__(
        self,
        *,
        project_root: Path | None = None,
        runtime_home: Path | None = None,
        lock_path: Path | None = None,
    ) -> None:
        self.project_root = (project_root or PROJECT_ROOT).resolve()
        configured_home = runtime_home or Path(
            os.getenv("QUANTSKILLS_HOME", DEFAULT_RUNTIME_DIRECTORY)
        )
        if not configured_home.is_absolute():
            configured_home = self.project_root / configured_home
        self.runtime_home = configured_home.resolve()
        self.lock_path = (
            lock_path.resolve()
            if lock_path is not None
            else self.project_root / "skills.lock.json"
        )

    def resolve_entrypoint(
        self,
        spec: SkillSpec,
    ) -> tuple[Path, dict[str, Any]]:
        lock_entry = self._lock_entry(spec)
        skill_root = self._safe_runtime_path(spec.runtime_path)
        if not skill_root.is_dir():
            raise SkillUnavailableError(
                f"Runtime skill '{spec.id}' is not installed under "
                f"QUANTSKILLS_HOME."
            )

        entrypoint = (skill_root / spec.expected_entrypoint).resolve()
        if not entrypoint.is_relative_to(skill_root) or not entrypoint.is_file():
            raise SkillUnavailableError(
                f"Approved entrypoint is missing for runtime skill '{spec.id}'."
            )
        file_hashes = lock_entry.get("file_sha256", {})
        if not isinstance(file_hashes, dict):
            raise SkillUnavailableError(
                f"Lock file hashes are invalid for runtime skill '{spec.id}'."
            )
        expected_hash = str(
            file_hashes.get(
                spec.expected_entrypoint,
                lock_entry.get("entrypoint_sha256", ""),
            )
        ).strip()
        if expected_hash and _sha256(entrypoint) != expected_hash:
            raise SkillUnavailableError(
                f"Approved entrypoint hash mismatch for runtime skill '{spec.id}'."
            )
        provenance = {
            "source_repository": lock_entry["repository"],
            "source_commit": lock_entry["commit_sha"],
            "source_ref": spec.source_ref,
            "license": lock_entry["license"],
            "skill_path": lock_entry["skill_path"],
            "expected_entrypoint": lock_entry["expected_entrypoint"],
            "owner": lock_entry["owner"],
            "mode": lock_entry["mode"],
            "dependency_mapping": lock_entry.get("dependency_mapping", {}),
        }
        return entrypoint, provenance

    def resolve_reference(
        self,
        spec: SkillSpec,
        reference: str,
    ) -> Path:
        if reference not in spec.allowed_references:
            raise ValueError(
                f"Reference is not allowlisted for skill '{spec.id}': {reference}"
            )
        entrypoint, _ = self.resolve_entrypoint(spec)
        skill_root = entrypoint.parent.resolve()
        path = (skill_root / reference).resolve()
        references_root = (skill_root / "references").resolve()
        if (
            not path.is_relative_to(references_root)
            or not path.is_file()
            or path.is_symlink()
        ):
            raise ValueError(f"Unsafe or missing skill reference: {reference}")
        lock_entry = self._lock_entry(spec)
        file_hashes = lock_entry.get("file_sha256", {})
        expected_hash = (
            str(file_hashes.get(reference, "")).strip()
            if isinstance(file_hashes, dict)
            else ""
        )
        if reference in spec.required_references and not expected_hash:
            raise SkillUnavailableError(
                f"Required reference hash is missing for runtime skill '{spec.id}'."
            )
        if expected_hash and _sha256(path) != expected_hash:
            raise SkillUnavailableError(
                f"Approved reference hash mismatch for runtime skill '{spec.id}'."
            )
        return path

    def skill_root(self, spec: SkillSpec) -> Path:
        entrypoint, _ = self.resolve_entrypoint(spec)
        return entrypoint.parent

    def _lock_entry(self, spec: SkillSpec) -> dict[str, Any]:
        if not self.lock_path.is_file():
            raise SkillUnavailableError(
                "skills.lock.json is missing; install the approved runtime skills."
            )
        try:
            payload = json.loads(self.lock_path.read_text(encoding="utf-8"))
            entry = payload["skills"][spec.id]
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            raise SkillUnavailableError(
                f"Lock metadata is missing or invalid for skill '{spec.id}'."
            ) from None
        required = {
            "repository",
            "commit_sha",
            "skill_path",
            "license",
            "installed_at",
            "expected_entrypoint",
            "owner",
            "mode",
        }
        if not isinstance(entry, dict) or required - set(entry):
            raise SkillUnavailableError(
                f"Lock metadata is incomplete for skill '{spec.id}'."
            )
        if (
            entry["repository"] != spec.source_repository
            or entry["license"] != spec.license
            or entry["expected_entrypoint"] != spec.expected_entrypoint
            or entry["owner"] not in spec.owner_agents
            or entry["mode"] != spec.mode.value
        ):
            raise SkillUnavailableError(
                f"Lock metadata does not match the allowlist for skill '{spec.id}'."
            )
        commit_sha = str(entry["commit_sha"])
        if len(commit_sha) != 40 or any(
            character not in "0123456789abcdef" for character in commit_sha.lower()
        ):
            raise SkillUnavailableError(
                f"Lock commit is invalid for runtime skill '{spec.id}'."
            )
        if spec.source_ref != "locked" and commit_sha != spec.source_ref:
            raise SkillUnavailableError(
                f"Lock commit does not match the pinned ref for skill '{spec.id}'."
            )
        return entry

    def _safe_runtime_path(self, relative_path: str) -> Path:
        candidate = (self.runtime_home / relative_path).resolve()
        if not candidate.is_relative_to(self.runtime_home):
            raise ValueError("Runtime skill path escapes QUANTSKILLS_HOME")
        return candidate


class InstructionSkillLoader:
    """Read approved Markdown as untrusted methodology text only."""

    def __init__(
        self,
        *,
        locator: RuntimeSkillLocator | None = None,
        max_text_length: int = DEFAULT_MAX_TEXT_LENGTH,
    ) -> None:
        if max_text_length < 1:
            raise ValueError("max_text_length must be positive")
        self.locator = locator or RuntimeSkillLocator()
        self.max_text_length = max_text_length

    def load(
        self,
        spec: SkillSpec,
        *,
        references: tuple[str, ...] = (),
    ) -> LoadedInstructionSkill:
        entrypoint, provenance = self.locator.resolve_entrypoint(spec)
        remaining = self.max_text_length
        instructions, remaining, truncated = _bounded_read(entrypoint, remaining)
        loaded_references: dict[str, str] = {}

        requested_references = tuple(
            dict.fromkeys((*spec.required_references, *references))
        )
        for reference in requested_references:
            path = self.locator.resolve_reference(spec, reference)
            text, remaining, item_truncated = _bounded_read(path, remaining)
            loaded_references[reference] = text
            truncated = truncated or item_truncated
            if remaining == 0:
                break

        return LoadedInstructionSkill(
            skill_id=spec.id,
            instructions=instructions,
            references=loaded_references,
            provenance=provenance,
            truncated=truncated,
        )


def _bounded_read(path: Path, remaining: int) -> tuple[str, int, bool]:
    text = path.read_text(encoding="utf-8")
    if len(text) <= remaining:
        return text, remaining - len(text), False
    return text[:remaining], 0, True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
