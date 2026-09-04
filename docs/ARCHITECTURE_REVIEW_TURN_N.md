# Talo 아키텍처 리뷰 — 이번 턴에 구현할 최소 범위

작성일: 2026-09-04
상태: 리뷰/비판 제안 (파일 수정 없음)

---

## 1. 현재 상태 요약

### 두 독립 스택이 공존한다

| 영역 | Next.js 웹 | 파이썬 CLI |
|------|------------|-----------|
| 저장소 | `data/db.json` (파일 기반 JSON) | `~/.talo/registry.sqlite` + `~/.talo/projects/<아이디>/state.sqlite` (WAL SQLite) |
| 인증 | `think_along_session` 쿠키 | `~/.talo/config.toml` + macOS 키체인 |
| AI 어댑터 | `lib/server/ai.ts` — 7개 프로바이더 HTTP 직접 호출 | `providers/openai_compat.py` + `providers/cli_subprocess.py` |
| 연결 관리 | 환경변수 기반 서버 사이드 (`process.env`) | `connection_wizard.py` — 대화형 프리셋/자동감지/키체인 |
| 스키마 | `database/schema.sql` (users/thinkings/messages/attachments/insights) | `storage/db.py` 마이그레이션 (workspaces/sessions/runs/messages/events/operations/checkpoints/handoffs/memories/artifacts/verifications/grants/usage) |

**핵심 차이**: CLI와 웹은 연결 상태를 공유하지 않는다. CLI의 `~/.talo/config.toml` 연결과 웹의 `process.env` 기반 프로바이더가 완전히 분리되어 있다.

### 기획서 문서 상태

- `TALO_HERMES_CONNECTION_UI_PRD.md`: 1~3단계 로드맵 (자동 감지, 헤르메스 터미널 UI, 웹 대시보드, 다중 브릿지)
- `Talo_CLI_Connection_UI_Plan_v0.1`: 화면별(S01~S15) 상세 기획
- **현재 CLI에 이미 구현된 것**: S01, S03, S04, S06, S08, S09, S10, S12, S13의 핵심 기능

---

## 2. 이번 턴 최소 수직 슬라이스 제안

### 과설계 경계

기획서가 제시한 전체 범위(자동 감지 엔진 + 헤르메스 터미널 UI + 웹 대시보드 + 다중 브릿지)를 한 턴에 구현하면 과설계다. 대신:

### 슬라이스: "CLI에서 연결한 AI를 웹에서 보고 전환 가능하게"

**목표**: `talo setup`으로 연결한 AI를 웹 대시보드(`/settings/connections`)에서 보고 전환할 수 있다.

```
[이미 구현]                          [이번 턴 구현]                     [미래]
talo setup (CLI)     ───→     웹 /api/connections     ───→    웹 대시보드 UI
talo connect (CLI)   ───→     공유 config.toml 읽기   ───→    실시간 모델 전환
talo model (CLI)     ───→     POST /api/connections/active ──→  세션 내 전환
```

**구체적으로 구현할 것**:
1. `lib/server/connections.ts` — `~/.talo/config.toml`을 읽어 웹 API가 사용하는 연결 목록 생성
2. `app/api/connections/route.ts` — GET(목록), POST(활성 모델 변경), DELETE(연결 해제)
3. `app/settings/connections/page.tsx` — 연결 카드 그리드 (간소 버전)
4. 기존 `lib/server/ai.ts`의 `getProviderCatalog()`이 config.toml의 연결을 반영하도록 수정

**제외**: 자동 감지, MCP 브릿지, CLI 서브프로세스 브릿지, 헤르메스 터미널 UI 모드

---

## 3. 보안 경계

### 현황 문제

| 위치 | 보안 상태 | 위험 |
|------|-----------|------|
| `config.toml` | `credential_ref`만 저장 (실제 키 미저장) | ✅ 안전 |
| `db.ts` (웹) | `process.env`에서 키 읽음 | ✅ 서버 사이드만 접근 |
| `data/db.json` | Thinkings의 `answer`에 AI 응답 평문 저장 | ⚠️ AI 프롬프트 응답이 디스크에 평문 |
| `connection_wizard.py` | 키체인 저장 시 `getpass` 사용 | ✅ 히스토리 미유지 |
| MCP OAuth 키 | `connection_wizard.py:95`에 하드코딩 | 🔴 `335d3b38...` 토큰 소스코드에 노출 |

### 이번 턴 보안 경계 제안

1. **config.toml 공유 시 비밀값 누출 방지**:
   - 웹 API는 `credential_ref`만 노출, 실제 키 해석은 서버 사이드에서만
   - `GET /api/connections` 응답에 `keychain:xxx` → `***` 마스킹

2. **MCP OAuth 하드코딩 제거**:
   - `default_key` 필드를 config.toml 외부로 분리하거나 사용자 입력으로 전환

3. **`data/db.json` Thinkings 보안**:
   - AI 응답에 민감 정보가 포함될 수 있음 → 파일 권한 `0600` 보장

---

## 4. 실패 복구

### 현황

- **웹**: `readDb()` 실패 시 `seedDatabase()`로 자동 복구 (로그 없음, 데이터 손실)
- **CLI**: SQLite WAL + `busy_timeout=5000`으로 동시성 처리. 마이그레이션 체크섬 불일치 시 `RuntimeError`

### 이번 턴 복구 설계

```
config.toml 읽기 실패 → 기본 연결 목록으로 폴백 (환경변수 기반)
웹 API 연결 목록 조회 실패 → 500 대신 빈 목록 + 경고 헤더
활성 모델 변경 실패 → 낙관적 잠금 (config.toml의 mtime 체크)
```

---

## 5. 정기 작업 중복 실행 방지

**이번 턴에 정기 실행되는 작업은 없다.**

그러나 향후 고려사항으로:
- 인사이트 리포트 주기적 생성(`insights` 테이블)은 정기 실행 대신 **웹훅 트리거** 또는 **CLI `talo insight` 수동 실행**으로 시작
- 중복 실행 방지: `~/.talo/locks/<task>.lock` 파일 + `fcntl.flock()` (파이썬), 또는 SQLite의 `operations` 테이블 상태 체크
- 현재 CLI의 `operations` 테이블에 `UNIQUE(run_id, call_id)`가 있으므로, 동일 요청의 중복 도구 실행은 DB 레벨에서 방지됨

---

## 6. 로컬 파일/DB 책임

| 파일 | 소유자 | 형식 | 역할 |
|------|--------|------|------|
| `~/.talo/config.toml` | CLI | 톰엘 | 연결 설정, 기본 모델, 프로젝트 기본값 |
| `~/.talo/registry.sqlite` | CLI | SQLite WAL | 워크스페이스, 세션, 실행 기록, 이벤트, 검증 |
| `~/.talo/projects/<아이디>/state.sqlite` | CLI | SQLite WAL | 프로젝트별 상태, 메모리, 체크포인트 |
| `data/db.json` | 웹 | JSON | Thinkings, 메시지, 사용자, 인사이트 (데모) |
| `.talo/project.toml` | CLI | 톰엘 | 프로젝트별 규칙, 제외 경로 |
| `.talo/skills/` | CLI | YAML | 사용자 정의 스킬 |
| `~/.talo/skills/` | CLI | YAML | 전역 스킬 |

**이번 턴 변경**: `config.toml`을 웹이 읽는다. 동시에 쓰기 경쟁이 발생할 수 있으므로:
- 웹은 **읽기 전용**으로 제한 (활성 모델 변경은 CLI이 비동기로 다시 로드)
- 또는: `config.toml` 쓰기 시 원자적 쓰기 (이미 `tmp + os.replace` 패턴 사용 중)

---

## 7. CLI 사용자 경험

### 이미 구현된 기능 (이번 턴 유지)

| 명령 | 화면 | 상태 |
|------|------|------|
| `talo` | 첫 실행 안내 / 대화형 | ✅ |
| `talo setup` | S01→S03→S06→S08→S09→S10 흐름 | ✅ |
| `talo connect` | S13 관리 메뉴 (인자 없이 대화형) | ✅ |
| `talo connect add` | 수동 연결 추가 (플래그 기반) | ✅ |
| `talo model` | S09 모델 선택기 | ✅ |
| `talo doctor` | 진단 리포트 | ✅ |
| `talo run "요청"` | 단발 실행 | ✅ |
| `talo resume [아이디]` | 세션 재개 | ✅ |

### 이번 턴 개선

- `talo connect list` → JSON 출력 (`--json` 플래그) 추가
- `talo doctor` → 연결 상태 검증 결과에 `config.toml` 버전 표시
- 화면 80열 준수 확인 (이미 `render.py`가 리치 기반)

---

## 8. 테스트 전략

### 현재 테스트

- 웹: `tests/p0-decisions.test.mjs` ~ `tests/p3-capabilities.test.mjs` (7개 파일, `node --test`)
- CLI: `cli/tests/` (pytest, `pyproject.toml`에 `testpaths = ["tests"]`)
- 통합 검증: `npm run verify` = 린트 + 타입검사 + 테스트 + 빌드

### 이번 턴 테스트 계층

```
1단계: 단위 테스트
  - lib/server/connections.ts: config.toml 파싱, 연결 목록 생성
  - app/api/connections/route.ts: GET/POST/DELETE 핸들러 (가짜 config.toml 사용)

2단계: 통합 테스트
  - CLI → 웹 연결 공유: config.toml 쓴 뒤 웹 API에서 읽기 확인
  - 동시 접근: CLI가 config.toml 쓰는 동안 웹 API 읽기 (동시성 테스트)

3단계: 종단간 (npm run verify)
  - 타입스크립트 컴파일 통과
  - 기존 테스트 깨지지 않음
  - `talo doctor`이 새 연결 구조 인식

테스트 파일 위치:
  - 웹: tests/p1-connections.test.mjs (기존 이름 규칙 유지)
  - CLI: cli/tests/test_connections.py (기존 규칙 유지)
```

---

## 9. 기술 설계 문서 목차 (제안)

```
TALO_CONNECTION_SHARING_DESIGN.md

1. 개요
   1.1 문제: CLI와 웹의 연결 상태 분리
   1.2 목표: CLI에서 설정한 연결을 웹에서 읽기/전환
   1.3 제외 범위: 자동 감지, MCP 브릿지, CLI 서브프로세스

2. 아키텍처
   2.1 config.toml 스키마 (기존 + 확장)
   2.2 웹 API 엔드포인트 설계
   2.3 읽기 전용 공유 vs 양방향 동기화 (접근 방식 비교)
   2.4 보안 경계 (credential_ref 마스킹)

3. 데이터 모델
   3.1 config.toml 연결 구조
   3.2 웹 API 응답 스키마
   3.3 오류 코드

4. 구현
   4.1 파일 레이아웃
   4.2 핵심 함수 시그니처
   4.3 상태 전이

5. 실패 복구
   5.1 config.toml 읽기 실패
   5.2 동시 쓰기 경쟁
   5.3 연결 검증 실패

6. 테스트
   6.1 단위 테스트
   6.2 통합 테스트
   6.3 기존 테스트 영향 분석

7. 보안 검토
   7.1 비밀값 누출 경로
   7.2 파일 권한
   7.3 API 노출 범위

8. 마일스톤
   8.1 구현 순서
   8.2 검증 기준
```

---

## 10. 비판적 결론

### 과설계 위험

1. **다중 브릿지 아키텍처를 이번 턴에 구현하지 않는다.** CLI 서브프로세스 브릿지는 코덱스 OAuth 인증이라는 특수 케이스다. 범용화하면 복잡도가 폭증한다.

2. **헤르메스 터미널 UI(화살표/단축키 리치 UI)는 고급 사용자 경험이다.** 현재 `input()` 기반 대화형이 충분하다. `prompt_toolkit` 의존성을 추가할 명분이 없다.

3. **웹 대시보드의 "실시간 지연시간 표시"**는 `.env.local` 환경변수 기반 연결에서 의미가 없다. 환경변수 키는 한번 설정하면 바뀌지 않는다.

### 남겨야 할 것

1. **`config.toml`을 웹에서 읽는 것만으로 충분하다.** 양방향 동기화는 웹에서 설정 UI를 만들 때 구현한다.

2. **`connection_wizard.py`의 자동감지(`scan_local_environment`)는 이미 충분히 동작한다.** 코드를 줄이지 말고 웹에서 재사용할 수 있는 추상화로 만든다.

3. **SQLite 스키마가 이미 CLI와 웹에서 이중으로 존재한다.** 통합을 이번 턴에 하면 안된다. `config.toml`이라는 비밀값 없는 설정 파일만 공유한다.

### 확인 질문

- 웹 대시보드 UI의 범위: 연결 목록만 보여줄지, 카드 그리드 + 지연시간 표시까지 할지
- config.toml의 원자적 쓰기가 이미 `os.replace` 패턴으로 구현되어 있으므로, 웹 읽기 시 mtime 체크로 신선도 판단 가능
- `data/db.json`의 Thinkings 저장소를 SQLite로 전환할지 (장기 과제)
