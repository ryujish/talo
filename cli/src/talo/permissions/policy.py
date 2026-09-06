"""권한 정책: 작업 방식과 권한 프로필의 교집합 평가.

기술 설계 10절. 계획 모드에서 일반 코드 변경·임의 셸 실행은 허용하지 않는다.
사용자가 요청한 기획 문서 저장은 document_write 범위로 별도 처리한다.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any

from talo.schemas import PermissionProfile, ToolEffect, WorkMode

# 도구명 -> 기본 영향 범위
EFFECT_BY_TOOL: dict[str, ToolEffect] = {
    "file_search": ToolEffect.READ,
    "file_read": ToolEffect.READ,
    "file_list": ToolEffect.READ,
    "file_patch": ToolEffect.WRITE,
    "file_write": ToolEffect.WRITE,
    "document_write": ToolEffect.WRITE,
    "git_status": ToolEffect.READ,
    "git_diff": ToolEffect.READ,
    "git_log": ToolEffect.READ,
    "command_run": ToolEffect.EXECUTE,
    "command_status": ToolEffect.READ,
    "memory_search": ToolEffect.READ,
    "memory_propose": ToolEffect.WRITE,
    "memory_update": ToolEffect.WRITE,
    "memory_confirm": ToolEffect.WRITE,
    "memory_retire": ToolEffect.WRITE,
    "skill_list": ToolEffect.READ,
    "skill_read": ToolEffect.READ,
}


@dataclass
class Decision:
    allowed: bool
    reason: str
    requires_approval: bool = False
    scope: dict[str, Any] = field(default_factory=dict)


@dataclass
class Grant:
    """저장된 허용 범위. 단순 문자열이 아니라 프로젝트·실행 파일·인자 패턴·작업 경로에 연결한다."""

    scope_json: dict[str, Any]
    policy_version: int = 1
    grant_id: str | None = None

    def matches(self, tool_name: str, scope: dict[str, Any], project_root: str) -> bool:
        s = self.scope_json
        if s.get("tool") not in (None, tool_name):
            return False
        if s.get("project_root") and s.get("project_root") != project_root:
            return False
        executable = scope.get("executable") or scope.get("command")
        if s.get("executable_pattern") and executable:
            if not fnmatch.fnmatch(executable, s["executable_pattern"]):
                return False
        if s.get("args_pattern"):
            args = " ".join(scope.get("args") or scope.get("argv") or [])
            if not fnmatch.fnmatch(args, s["args_pattern"]):
                return False
        if s.get("cwd_pattern") and scope.get("cwd"):
            if not fnmatch.fnmatch(scope.get("cwd"), s["cwd_pattern"]):
                return False
        return True


class PermissionPolicy:
    def __init__(self, mode: WorkMode = WorkMode.DEV, profile: PermissionProfile = PermissionProfile.PROJECT_EDIT,
                 grants: list[Grant] | None = None, project_root: str = "."):
        self.mode = mode
        self.profile = profile
        self.grants = grants or []
        self.project_root = project_root
        self.policy_version = 1
        self.denials: list[dict[str, Any]] = []

    def evaluate(self, tool_name: str, scope: dict[str, Any] | None = None) -> Decision:
        scope = scope or {}
        effect = EFFECT_BY_TOOL.get(tool_name)
        if effect is None:
            return Decision(False, f"등록되지 않은 도구: {tool_name}")

        # 계획 모드: 변경 수반 실행 금지. 기획 문서 저장만 document_write로 허용.
        if self.mode == WorkMode.PLAN:
            if effect == ToolEffect.READ:
                return Decision(True, "계획 모드의 읽기 허용", scope=scope)
            if tool_name == "document_write" and self.profile != PermissionProfile.READ_ONLY:
                return Decision(True, "요청된 기획 문서 저장 범위", scope=scope)
            return Decision(False, "계획 모드에서는 변경·실행을 수행하지 않음", scope=scope)

        # 읽기 전용 프로필: 읽기는 허용, 변경/실행은 추가 확인
        if self.profile == PermissionProfile.READ_ONLY:
            if effect == ToolEffect.READ:
                return Decision(True, "읽기 전용 프로필의 읽기 허용", scope=scope)
            return Decision(False, "읽기 전용 프로필에서는 변경·실행 불가", requires_approval=True, scope=scope)

        # 저장된 허용 범위 먼저 확인 (이미 부여된 허용은 해당 범위에서 유지)
        for grant in self.grants:
            if grant.matches(tool_name, scope, self.project_root):
                return Decision(True, "저장된 허용 범위", scope=scope)

        # 확정된 기억은 이후 모든 모델의 컨텍스트에 주입되므로 사람 검토 없이 바꾸지 않는다.
        if tool_name in {"memory_confirm", "memory_update", "memory_retire"}:
            if self.profile == PermissionProfile.DELEGATED:
                return Decision(True, "위임 실행 프로필", scope=scope)
            return Decision(False, "프로젝트 기억 변경은 사람 승인이 필요함",
                            requires_approval=True, scope=scope)

        # 프로젝트 편집: 프로젝트 내 파일 편집 허용, 명령 실행은 승인
        if self.profile == PermissionProfile.PROJECT_EDIT:
            if effect in (ToolEffect.READ, ToolEffect.WRITE):
                return Decision(True, "프로젝트 편집 프로필", scope=scope)
            return Decision(False, "명령 실행은 승인이 필요함", requires_approval=True, scope=scope)

        # 위임 실행: 사용자가 지정한 경로·명령 범위에서 연속 실행
        if self.profile == PermissionProfile.DELEGATED:
            return Decision(True, "위임 실행 프로필", scope=scope)

        return Decision(False, "허용되지 않은 권한 조합", requires_approval=True, scope=scope)

    def record_denial(self, tool_name: str, scope: dict[str, Any], reason: str) -> None:
        self.denials.append({"tool": tool_name, "scope": scope, "reason": reason, "policy_version": self.policy_version})


def mode_and_profile(mode: str | None, permission: str | None) -> tuple[WorkMode, PermissionProfile]:
    m = WorkMode(mode) if mode in {m.value for m in WorkMode} else WorkMode.DEV
    p = PermissionProfile(permission) if permission in {p.value for p in PermissionProfile} else PermissionProfile.PROJECT_EDIT
    return m, p
