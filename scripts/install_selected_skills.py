"""Install only the fixed, pinned runtime repositories approved for AlphaOS."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GITHUB_ROOT = "https://github.com"
APPROVED_REPOSITORIES: dict[str, dict[str, Any]] = {
    "factor_idea_generation": {
        "repository": "quantskills/skill-factor-idea-generation",
        "commit_sha": "4fda44d27bc80efe60284da6b03bc56a2bf4e82f",
        "directory": "skill-factor-idea-generation",
        "skill_path": ".",
        "license": "GPL-3.0-only",
        "owner": "quant",
        "mode": "instruction",
        "expected_entrypoint": "SKILL.md",
        "critical_files": [
            "SKILL.md",
            "LICENSE",
            "references/factor_shape_guidance.md",
            "references/idea_quality_bar.md",
            "references/output_schema.md",
        ],
    },
    "r020_volume_expansion": {
        "repository": "quantskills/skill-quant-factor-volume-stat-alpha",
        "commit_sha": "b169f31106f748b8746c4c1028c162e95f7277f4",
        "directory": "skill-quant-factor-volume-stat-alpha",
        "skill_path": "factors/R020-5d-z-scored-volume-expansion",
        "license": "GPL-3.0-only",
        "owner": "quant",
        "mode": "executable",
        "expected_entrypoint": "scripts/factor.py",
        "critical_files": [
            "factors/R020-5d-z-scored-volume-expansion/scripts/factor.py",
            "LICENSE",
        ],
    },
    "a_share_stock_dossier": {
        "repository": "quantskills/skill-a-share-stock-dossier",
        "commit_sha": "213a9cb6b36ccc3ae4c72606ff72211de7b67199",
        "directory": "skill-a-share-stock-dossier",
        "skill_path": ".",
        "license": "GPL-3.0-only",
        "owner": "research",
        "mode": "instruction",
        "expected_entrypoint": "SKILL.md",
        "critical_files": [
            "SKILL.md",
            "references/dossier-guide.md",
            "LICENSE",
        ],
        "dependency_mapping": {
            "skill-pandadata-api": "backend.services.pandadata_client.PandaDataClient"
        },
    },
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install AlphaOS's fixed, pinned QuantSkills allowlist."
    )
    parser.add_argument(
        "--runtime-home",
        type=Path,
        default=Path(os.getenv("QUANTSKILLS_HOME", ".runtime_skills")),
        help="Runtime directory, relative to the AlphaOS root by default.",
    )
    parser.add_argument(
        "--lock-file",
        type=Path,
        default=Path("skills.lock.json"),
        help="Lock file, relative to the AlphaOS root by default.",
    )
    args = parser.parse_args()
    runtime_home = _resolve_runtime_home(args.runtime_home)
    lock_file = _resolve_lock_path(args.lock_file)
    runtime_home.mkdir(parents=True, exist_ok=True)

    installed_at = datetime.now(timezone.utc).isoformat()
    lock_skills: dict[str, dict[str, Any]] = {}
    for skill_id, approved in APPROVED_REPOSITORIES.items():
        repository = approved["repository"]
        destination = runtime_home / approved["directory"]
        _install_repository(repository, approved["commit_sha"], destination)
        commit_sha = _git(destination, "rev-parse", "HEAD").strip()
        if commit_sha != approved["commit_sha"]:
            raise RuntimeError(f"Pinned commit checkout failed: {skill_id}")
        skill_root = (destination / approved["skill_path"]).resolve()
        entrypoint = (skill_root / approved["expected_entrypoint"]).resolve()
        if (
            not skill_root.is_relative_to(destination.resolve())
            or not entrypoint.is_relative_to(skill_root)
            or not entrypoint.is_file()
        ):
            raise RuntimeError(
                f"Approved entrypoint is missing after install: {skill_id}"
            )
        file_hashes: dict[str, str] = {}
        for relative_path in approved["critical_files"]:
            critical_file = (destination / relative_path).resolve()
            if (
                not critical_file.is_relative_to(destination.resolve())
                or not critical_file.is_file()
                or critical_file.is_symlink()
            ):
                raise RuntimeError(
                    f"Approved critical file is missing after install: "
                    f"{skill_id}/{relative_path}"
                )
            stored_path = (
                critical_file.relative_to(skill_root).as_posix()
                if critical_file.is_relative_to(skill_root)
                else f"repository:{relative_path}"
            )
            file_hashes[stored_path] = _sha256(critical_file)
        lock_skills[skill_id] = {
            "repository": repository,
            "commit_sha": commit_sha,
            "skill_path": approved["skill_path"],
            "license": approved["license"],
            "installed_at": installed_at,
            "owner": approved["owner"],
            "mode": approved["mode"],
            "expected_entrypoint": approved["expected_entrypoint"],
            "entrypoint_sha256": _sha256(entrypoint),
            "file_sha256": file_hashes,
            "dependency_mapping": approved.get("dependency_mapping", {}),
        }

    payload = {
        "version": 1,
        "generated_at": installed_at,
        "runtime_home": (
            runtime_home.relative_to(PROJECT_ROOT).as_posix()
            if runtime_home.is_relative_to(PROJECT_ROOT)
            else str(runtime_home)
        ),
        "policy": "Only the fixed, pinned AlphaOS runtime allowlist may be installed.",
        "skills": lock_skills,
    }
    lock_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "installed_skills": sorted(lock_skills),
                "runtime_home": str(runtime_home),
                "lock_file": str(lock_file),
            },
            ensure_ascii=True,
        )
    )


def _install_repository(
    repository: str,
    commit_sha: str,
    destination: Path,
) -> None:
    approved = {item["repository"] for item in APPROVED_REPOSITORIES.values()}
    if repository not in approved:
        raise ValueError("Repository is not on the fixed allowlist")
    url = f"{GITHUB_ROOT}/{repository}.git"
    if destination.exists():
        if not (destination / ".git").is_dir():
            raise RuntimeError(
                f"Existing runtime directory is not a Git checkout: {destination.name}"
            )
        origin = _git(destination, "remote", "get-url", "origin").strip()
        normalized_origin = origin.removesuffix(".git").lower()
        if normalized_origin != url.removesuffix(".git").lower():
            raise RuntimeError(
                f"Existing runtime checkout has an unexpected origin: "
                f"{destination.name}"
            )
    else:
        _run(
            "git",
            "clone",
            "--no-checkout",
            url,
            str(destination),
            cwd=runtime_home_parent(destination),
        )
    _git(destination, "fetch", "--depth=1", "origin", commit_sha)
    _git(destination, "checkout", "--detach", commit_sha)


def runtime_home_parent(destination: Path) -> Path:
    return destination.parent.resolve()


def _git(repository: Path, *arguments: str) -> str:
    return _run("git", "-C", str(repository), *arguments, cwd=PROJECT_ROOT)


def _run(*arguments: str, cwd: Path) -> str:
    try:
        completed = subprocess.run(
            arguments,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError):
        raise RuntimeError("Approved QuantSkills installation command failed.") from None
    return completed.stdout


def _resolve_runtime_home(path: Path) -> Path:
    resolved = path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()
    if resolved == Path(resolved.anchor):
        raise ValueError("QUANTSKILLS_HOME cannot be a filesystem root")
    return resolved


def _resolve_lock_path(path: Path) -> Path:
    resolved = path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()
    if not resolved.is_relative_to(PROJECT_ROOT):
        raise ValueError("The lock file must remain below the AlphaOS project root")
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
