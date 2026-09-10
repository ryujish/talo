"""정확 일치, 줄바꿈 정규화, 고유 anchor 기반 제한 Fuzzy 후보 생성."""
from __future__ import annotations

import difflib
from talo.changes.manager import ChangeError


def replacement(content: str, old: str, new: str) -> tuple[str, str]:
    if not old:
        raise ChangeError("INVALID_CHANGE", "빈 치환 기준은 허용하지 않습니다")
    count = content.count(old)
    if count == 1:
        return content.replace(old, new, 1), "exact"
    if count > 1:
        raise ChangeError("AMBIGUOUS_MATCH", "같은 문맥이 여러 곳입니다. 더 긴 고유 문맥을 제공하세요")
    # 줄끝 형식만 정규화. 들여쓰기·문자열 공백은 그대로 비교한다.
    source = content.splitlines(keepends=True)
    needles = old.splitlines(keepends=True)
    plain = lambda xs: [x.rstrip("\r\n") for x in xs]
    target = plain(needles)
    if len(target) > 400 or len(source) > 20000:
        raise ChangeError("MATCH_BUDGET", "후보 탐색 상한을 초과했습니다. 짧은 고유 문맥을 지정하세요")
    if not target:
        raise ChangeError("NO_MATCH", "치환 문맥이 없습니다")
    candidates = []
    for i in range(max(0, len(source) - len(target) + 1)):
        current = plain(source[i:i + len(target)])
        if current == target:
            candidates.append((i, "newline"))
        elif len(target) >= 3 and current[0] == target[0] and current[-1] == target[-1]:
            ratio = difflib.SequenceMatcher(None, "\n".join(target), "\n".join(current), autojunk=False).ratio()
            if ratio >= 0.85:
                candidates.append((i, "fuzzy"))
    if len(candidates) != 1:
        code = "AMBIGUOUS_MATCH" if candidates else "NO_MATCH"
        raise ChangeError(code, "고유한 문맥이 없습니다. 최신 파일을 읽고 패치를 재생성하세요")
    i, method = candidates[0]
    matched = "".join(source[i:i + len(target)])
    ending = "\r\n" if "\r\n" in matched else "\n"
    replacement_text = new.replace("\r\n", "\n").replace("\n", ending)
    if matched.endswith(("\n", "\r")) and not old.endswith(("\n", "\r")) and not new.endswith(("\n", "\r")):
        replacement_text += ending
    return "".join(source[:i]) + replacement_text + "".join(source[i + len(target):]), method
