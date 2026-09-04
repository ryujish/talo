"""Talo 데이터 경로.

제품 설계 경로:
  ~/.talo/config.toml
  ~/.talo/registry.sqlite
  ~/.talo/projects/<project-id>/state.sqlite
  ~/.talo/projects/<project-id>/artifacts/
  ~/.talo/skills/
  저장소 .talo/project.toml
  저장소 .talo/skills/

테스트를 위해 TALO_HOME 환경변수로 루트를 재지정할 수 있다.
"""
from __future__ import annotations

import os
from pathlib import Path


def talo_home() -> Path:
    override = os.environ.get("TALO_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".talo"


def config_path() -> Path:
    return talo_home() / "config.toml"


def registry_db_path() -> Path:
    return talo_home() / "registry.sqlite"


def project_dir(project_id: str) -> Path:
    return talo_home() / "projects" / project_id


def project_db_path(project_id: str) -> Path:
    return project_dir(project_id) / "state.sqlite"


def artifacts_dir(project_id: str) -> Path:
    return project_dir(project_id) / "artifacts"


def daily_dir(project_id: str) -> Path:
    return project_dir(project_id) / "daily"


def user_skills_dir() -> Path:
    return talo_home() / "skills"


def ensure_talo_dirs(project_id: str | None = None) -> None:
    talo_home().mkdir(parents=True, exist_ok=True)
    user_skills_dir().mkdir(parents=True, exist_ok=True)
    if project_id:
        project_dir(project_id).mkdir(parents=True, exist_ok=True)
        artifacts_dir(project_id).mkdir(parents=True, exist_ok=True)
        daily_dir(project_id).mkdir(parents=True, exist_ok=True)


def project_talo_dir(repo_root: Path) -> Path:
    return repo_root / ".talo"


def project_config_path(repo_root: Path) -> Path:
    return project_talo_dir(repo_root) / "project.toml"


def project_skills_dir(repo_root: Path) -> Path:
    return project_talo_dir(repo_root) / "skills"
