"""출력용 텍스트·스코프 정제.

일지(daily)와 Inbox 저장·출력에 자격 증명 값이나 원문 전체 메시지가
남지 않도록 한다.
"""
from __future__ import annotations

import json
import re
from typing import Any

_SECRET_KEY = re.compile(
    r"(api[_-]?key|secret|token|password|authorization|credential|oauth)", re.IGNORECASE)
_ENV_ASSIGN = re.compile(r"(?im)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\S.*)$")
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{6,}")
_SK_KEY = re.compile(r"(?i)(sk-[A-Za-z0-9]{4})[A-Za-z0-9._\-]+")


def is_secret_key(key: str) -> bool:
    return bool(_SECRET_KEY.search(key))


def redact_text(text: str, max_len: int = 400) -> str:
    """자격 증명 패턴을 정제하고 길이를 제한한다."""
    if not text:
        return text
    out = _ENV_ASSIGN.sub(
        lambda m: f"{m.group(1)}=<redacted>" if is_secret_key(m.group(1)) else m.group(0),
        text,
    )
    out = _BEARER.sub(r"\1<redacted>", out)
    out = _SK_KEY.sub(r"\1<redacted>", out)
    if len(out) > max_len:
        out = out[:max_len] + "…"
    return out


def redact_scope(scope: Any, max_str: int = 80) -> Any:
    """도구 호출 scope를 정제한다. 비밀 키 값은 <redacted>, 긴 원문은 잘라낸다."""
    if isinstance(scope, dict):
        return {
            str(k): ("<redacted>" if is_secret_key(str(k)) else redact_scope(v, max_str))
            for k, v in scope.items()
        }
    if isinstance(scope, list):
        return [redact_scope(x, max_str) for x in scope]
    if isinstance(scope, str):
        if len(scope) > max_str:
            return scope[:max_str] + "…"
        return redact_text(scope, max_str)
    return scope


def sanitize_scope_json(scope_json: str, max_str: int = 80) -> str:
    """scope_json을 정제된 한 줄 JSON 문자열로 바꾼다."""
    try:
        parsed = json.loads(scope_json or "{}")
    except json.JSONDecodeError:
        return "<파싱 불가>"
    return json.dumps(redact_scope(parsed, max_str), ensure_ascii=False)
