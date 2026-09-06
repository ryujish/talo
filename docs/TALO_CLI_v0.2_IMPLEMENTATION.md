# Talo CLI v0.2 구현 및 실행 안내

기준 설계: `TALO_PRODUCT_TECH_DESIGN_v0.2.md`. 작업 대상은 Talo CLI다. 웹 참조 경로 `think-along_start`의 코드는 이번에 변경하지 않았다.

## 이번 CLI 구현

| 영역 | 동작 |
| --- | --- |
| 파일 변경 | `file_patch`, `file_write`, `document_write`가 원본을 먼저 덮어쓰지 않고 SQLite 변경 제안을 생성 |
| 대화형 검토 | 실제 컬러 diff → 적용/수정 요청/취소. 원본·후보 해시를 승인 대상에 결합 |
| 비대화형 실행 | 제안만 저장하고 승인 필요 종료 코드를 반환. 변경 ID로 나중에 검토·적용 |
| 체크포인트 | 변경 전 바이트·모드·존재 여부, 후보 바이트를 저장. Git index와 사용자 commit 이력을 변경하지 않음 |
| `/undo` | 마지막 적용 묶음 복원. 이후 사용자 수정이 있으면 충돌로 멈춤 |
| 장애 복구 | 부분 적용을 SQLite 상태로 식별. 명시적 recover로 알려진 before/after만 복원 |
| 패치 복구 | 정확 일치, 줄바꿈 정규화, 제한된 고유 anchor Fuzzy 후보. 실패 코드와 최신 파일 재조회 지시를 모델에 전달, 재시도 수·시간·반복 패치 제한 |
| 대화 연속성 | 같은 세션의 최근 원문·직전 인계·확정 결정·규칙을 실제 다음 모델 요청에 전달 |
| 다음 실행 | 최근 세션을 기본 재개. 목표·열린 작업·대기 변경 표시. `/new`로 별도 세션 생성 |
| 완료 판단 | 모델 완료 응답만으로 목표를 달성했다고 확정하지 않음. `tasks done --evidence`로 사용자 확인 기록 |
| 외부 CLI | macOS 파일 쓰기 sandbox와 임시 작업 복제. 결과를 하나의 변경 묶음으로 검토 후 원본에 적용 |
| Headless | `talo serve`의 버전 있는 stdio JSONL 계약. 요청 ID 중복 실행 방지와 미확정 결과 재실행 차단 |
| 배포 기반 | 런타임을 포함하는 독립 실행 파일 빌드 스크립트, 체크섬·빌드 환경·의존성 lock 산출 |

## 바로 실행

Talo 폴더에서 개발 환경 실행:

```bash
cli/.venv/bin/talo demo
cli/.venv/bin/talo
```

로컬에서 검증한 런타임 포함 배포본 실행 (폴더 전체를 함께 유지):

```bash
./cli/dist/portable/talo/talo --version
./cli/dist/portable/talo/talo demo
./cli/dist/portable/talo/talo
```

`demo`는 임시 프로젝트에서 diff → 적용 → undo를 실행하고 원문 복구를 확인한다. 실제 사용자 프로젝트나 AI 연결을 수정하지 않는다. 실제 작업은 사용할 프로젝트 폴더에서 Talo 실행 파일을 호출한다.

## 변경 검토 명령

```bash
talo changes list
talo changes review <change-id>
talo changes diff <change-id> --json
talo changes apply <change-id> --hash <검토한-patch-hash>
talo changes cancel <change-id>
talo undo
talo changes recover <change-id>
talo tasks list
talo tasks done <task-id> --evidence "검증 명령과 확인 결과"
```

대화형 명령: `/diff`, `/review`, `/undo`, `/tasks`, `/new`, 기존 `/model`·`/memory`·`/sessions`.

변경을 검토한 뒤 파일 또는 브랜치가 바뀌면 이전 승인은 사용하지 못한다. recover는 임의 시점으로 돌아가는 명령이 아니라 중단된 적용·undo를 복구하는 명령이다. shell 명령의 외부 부작용, API 호출, 패키지 설치는 undo 대상이 아니다.

## Headless 계약 예

`talo serve`의 stdin으로 JSON 한 줄씩 전송한다. stdout은 event/result/error JSONL이며 각 응답에 요청 id가 포함된다.

```json
{"version":1,"id":"health-1","method":"health"}
```

지원 메서드: `session.start`, `sessions.list`, `run`, `changes.list`, `changes.diff`, `changes.apply`, `changes.undo`, `changes.cancel`, `changes.recover`, `tasks.list`.

health 이외 요청에는 프로젝트 절대 경로 `cwd`를 전달한다. `run`의 params는 `session_id`, `request`, 선택적 `mode`·`permission`이다. 쓰기 요청의 동일 ID·동일 본문 재요청은 저장된 결과를 반환한다. 같은 ID·다른 본문은 거절한다. 중단되어 결과가 미확정인 요청은 자동 재실행하지 않는다.

이 stdio 인터페이스는 웹 연결을 위한 첫 코어 경계다. 설계의 사용자별 자동 기동 데몬·HTTP 인증·SSE·브라우저 연결을 모두 완성한 상태는 아니다. 현재 CLI는 공통 Application Service를 직접 사용하고, 같은 workspace의 run과 파일 변경을 각각 OS 잠금으로 직렬화한다.

## 빌드

빌드 환경에만 Python과 PyInstaller가 필요하다. 검증된 빌드 환경의 lock은 `cli/dist/portable/build-requirements.lock`(onedir) 또는 `cli/dist/build-requirements.lock`(onefile)에 생성된다. 실제 배포본에는 별도 Python·Node 실행 파일 설치가 필요하지 않다.

```bash
cli/.build-venv/bin/python cli/packaging/build.py --onedir
# 단일 파일은 --onedir 없이 빌드
```

Homebrew 등록·서명 공증·공개 release는 아직 수행하지 않았다. `brew install talo`를 이미 가능한 설치법으로 안내하지 않는다. 현재 머신의 x86_64 Python으로 첫 로컬 산출물을 만들었으며 arm64 전용 빌드와 깨끗한 별도 Mac 설치 검증은 별도 출시 게이트다.

## 적용 범위와 남은 작업

- UTF-8 일반 파일의 생성·수정·삭제를 지원한다. 심볼릭 링크·하드링크·바이너리·서브모듈 변경은 차단한다. 파일당 2 MiB, 변경 묶음 16 MiB 상한이다.
- 외부 CLI 격리는 파일 쓰기 경계다. 네트워크·읽기까지 격리하는 컨테이너가 아니다. API 연결과 달리 외부 CLI 자체 설치·로그인 요구가 남는다. 인증 갱신·도구별 캐시 쓰기 때문에 특정 CLI가 실패할 수 있으므로 실제 계정 호환성은 별도 검증한다.
- 외부 CLI의 읽기·계획 모드 결과는 원본에 적용하지 않는다. 외부 CLI가 오류로 끝난 임시 결과는 자동 적용하지 않는다.
- 제한 Fuzzy 후보는 반드시 diff 검토 대상이다. 자가 수정은 모델에 최신 파일 재조회 지시를 반환하는 방식이며 별도의 정적 분석기·테스트 sandbox와 결합된 완전한 healing 엔진은 후속 범위다.
- 구조화된 열린 작업은 저장하지만, 전체 과거 대화의 의미 기반 작업 추출·자동 완료 판정·모델별 토큰 예산 최적화는 후속 범위다.
- checkpoint 자동 보존 기간·용량 정리, 복구 conflict의 hunk 편집 UI, 자동 브랜치 재연결은 후속 범위다. 현재 복구 blob은 자동 삭제하지 않는다.
- 웹 대시보드, JSON→SQLite 데이터 이전, HTTP/SSE와 단일 데몬 writer 전환, Homebrew 공개 배포·공증, 실제 사용자 검증은 구현 완료로 표시하지 않는다.

## 검증 명령

```bash
cli/.venv/bin/python -m pytest cli/tests
```

추가 테스트는 기존 staged/unstaged 변경 보존, 생성·삭제·모드·CRLF 복구, 외부 수정 충돌, 다중 파일 부분 적용 중단, 손상된 blob, 프로젝트 격리, 실제 macOS sandbox 쓰기 차단, 모델 입력의 원문·결정·도구 결과 연결, headless 요청 재시작 멱등성을 확인한다.

## 최종 검증 결과

- CLI 단위·통합 테스트: **104 passed**. 실제 macOS 파일 쓰기 격리 테스트 포함.
- x86_64 단일 파일: Python·Node·Git을 찾을 수 없는 PATH에서 버전, demo, 변경 제안·승인·undo를 검증했다.
- 런타임 포함 폴더 배포본: 같은 PATH 조건에서 버전, demo의 원문 복구, stdio health를 검증했다.
- 이 Mac에서 단일 파일 버전 조회는 첫 실행 22.83초, 이후 약 15~16초였다. 폴더 배포본은 첫 실행 22.07초, 두 번째 0.21초, demo 1.97초였다. 반복 실행에는 폴더 배포본을 권장하되 첫 실행 지연은 미해결이다. 원인은 별도 프로파일링이 필요하다.
- 실제 공급자 계정 호출, 다른 Mac의 설치 경험, arm64 네이티브 실행, 서명·공증은 이번 결과로 보장하지 않는다.
