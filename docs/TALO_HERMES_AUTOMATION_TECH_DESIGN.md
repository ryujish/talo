# Talo × Hermes 자동화 기술 설계

- 상태: P0·P1 구현 완료
- 작성일: 2026-09-04
- 원문: [AI 공부/사용 일지 — Part 6 Hermes](https://app.notion.com/p/AI-0-3-39637f585d8381408ad6da8375439a61)
- 분석: Codex 오케스트레이터 + AGY 제품 분석 + DeepCode 코드 갭 분석 + OpenCode 아키텍처 검수

## 1. 목표

Hermes의 24시간 비서 패턴 중 Talo의 핵심인 **모델이 바뀌어도 기억·결정·미완료 작업이 이어지는 연속성**을 강화하는 기능만 채택한다. Hermes 자체를 복제하거나 메신저 봇 플랫폼을 새로 만드는 것이 목표가 아니다.

이번 구현의 완료 조건은 다음과 같다.

1. 모델이 제안한 기억을 검색뿐 아니라 확정·수정·폐기할 수 있다.
2. 확정·수정·폐기는 사람 승인 또는 명시적 위임 없이는 실행되지 않는다.
3. 같은 요청이 재시도되어도 기억 버전이 중복 증가하지 않는다.
4. 프로젝트가 다른 기억은 조회하거나 변경할 수 없다.
5. 전체 Web·CLI 검증이 한 명령으로 통과한다.

## 2. 원문에서 추출한 Hermes 기능

| 기능 | Talo 판정 | 이유 |
|---|---|---|
| 영속 메모리 | P0 채택 | Talo의 핵심 가치이며 SQLite `MemoryStore`가 이미 존재 |
| 모델 자유 선택 | P0 유지 | `talo model`, 연결 마법사, Web provider adapter가 이미 담당 |
| 셀프호스팅 | P0 유지 | 로컬 SQLite·JSON 저장소와 로컬 OpenAI 호환 모델 지원 |
| 미완료 이월 | P1 채택 | 기존 handoff의 `next_actions`를 재개 화면에 연결하면 됨 |
| 사람 검토 Inbox | P1 채택 | 동기 승인 상태는 있으나 영속 승인 큐가 없음 |
| cron | P1 채택 | 일일 회고를 자동화하되 별도 상주 데몬은 만들지 않음 |
| 업무 준비 일지 | P1 변형 채택 | Slack/Gmail보다 Talo 세션·결정·Git 변경을 우선 사용 |
| AI 뉴스레터 | P2 변형 채택 | 외부 뉴스 대신 프로젝트 내부 의사결정 회고부터 제공 |
| Slack/Telegram 등 게이트웨이 | P2 보류 | OAuth·웹훅·정보 유출·운영 비용이 핵심 가치 대비 큼 |

우선순위는 원문의 기능 수가 아니라 Talo의 제품 경계와 기존 코드 재사용 가능성으로 정했다.

## 3. 현재 구조와 갭

### 3.1 CLI

- 실행: `cli/src/talo/runtime/loop.py`
- 저장: 프로젝트별 SQLite WAL (`cli/src/talo/storage/db.py`)
- 기억: `MemoryStore`의 `propose`, `confirm`, `revise`, `retire`
- 권한: `PermissionPolicy`의 mode/profile/tool effect 교집합
- 종료 인계: handoff 문서와 `next_actions`

P0 전에는 `memory_search`와 `memory_propose`만 모델 도구로 등록되어 있었다. 도메인 계층에 존재하는 확정·수정·폐기 함수가 도구 계층에 연결되지 않아 기억 학습 루프가 닫히지 않았다.

### 3.2 Web

- 실행: Next.js API routes
- 저장: `data/db.json`
- 결정 기억: confirmed decision을 context packet에 포함
- AI 연결: 환경변수 및 provider adapter

Web과 CLI는 저장소가 분리되어 있다. 이번 P0에서 두 저장소를 합치지 않는다. 스키마 통합은 데이터 이전·동시성·권한 모델까지 함께 설계해야 하므로 별도 마이그레이션으로 다룬다.

## 4. P0 구현: 사람 승인형 영속 메모리 루프

### 4.1 흐름

```text
모델 memory_propose
  → SQLite memories(status=proposed, version=1)
  → 모델 memory_confirm/update/retire 요청
  → PermissionPolicy
      ├─ delegated: 실행
      └─ 그 외: approval_required
  → 사람 승인
  → MemoryStore 도메인 메서드
  → 이후 confirmed rule만 모든 모델의 컨텍스트에 주입
```

### 4.2 도구 계약

| 도구 | 입력 | 결과 | 영향 |
|---|---|---|---|
| `memory_confirm` | `memory_id` | 최신 memory record | WRITE + 승인 |
| `memory_update` | `memory_id`, `content` | 최신 memory record | WRITE + 승인 |
| `memory_retire` | `memory_id` | retired memory record | WRITE + 승인 |

세 도구는 현재 프로젝트의 기억만 다룬다. 다른 프로젝트의 ID 또는 존재하지 않는 ID는 `프로젝트 범위의 기억이 아님` 오류로 종료한다.

### 4.3 멱등성

- 이미 `confirmed`인 기억을 다시 확정하면 DB를 쓰지 않는다.
- 내용이 같은 수정 요청은 DB를 쓰지 않는다.
- 이미 `retired`인 기억을 다시 폐기하면 DB를 쓰지 않는다.

이 규칙으로 provider 재시도나 네트워크 응답 유실이 기억 버전을 부풀리지 않는다.

### 4.4 변경 파일

- `cli/src/talo/tools/builtin.py`: 도구 핸들러 3개
- `cli/src/talo/tools/registry.py`: OpenAI 호환 도구 스키마 등록
- `cli/src/talo/permissions/policy.py`: 사람 승인 경계
- `cli/src/talo/memory/store.py`: 멱등 상태 전이
- `cli/tests/test_storage.py`: 수직 슬라이스 및 프로젝트 격리 회귀
- `cli/tests/test_workspace_tools.py`: 승인 정책 회귀
- `package.json`: Web·CLI 단일 검증 명령

## 5. P1 구현: OS 스케줄러 기반 일일 자동화

### 5.1 선택

Talo 내부에 24시간 폴링 데몬을 추가하지 않는다. macOS `launchd` 또는 Linux `systemd timer`가 `talo cron run-due`를 매분 호출하고, Talo는 예약 상태와 실행 멱등성만 책임진다.

```text
launchd/systemd timer
  → talo cron run-due
  → BEGIN IMMEDIATE
  → due job 조회
  → scheduled_runs(job_id, scheduled_for) UNIQUE 선점
  → read_only + 고정 예산으로 기존 AgentRuntime 실행
  → 성공/실패 기록
  → daily Markdown artifact 생성
  → Human Review Inbox에 게시
```

### 5.2 제안 스키마

```sql
CREATE TABLE scheduled_jobs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  name TEXT NOT NULL,
  prompt TEXT NOT NULL,
  schedule_json TEXT NOT NULL,
  timezone TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  next_run_at REAL NOT NULL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE scheduled_runs (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES scheduled_jobs(id),
  scheduled_for REAL NOT NULL,
  state TEXT NOT NULL,
  session_id TEXT,
  run_id TEXT,
  error TEXT,
  started_at REAL NOT NULL,
  finished_at REAL,
  UNIQUE(job_id, scheduled_for)
);
```

`UNIQUE(job_id, scheduled_for)`가 같은 시간 슬롯의 중복 실행을 막는다. 선점과 `next_run_at` 갱신은 한 SQLite 트랜잭션에서 수행한다.

### 5.3 CLI 계약

```text
talo cron add --name daily-standup --at 08:00 --weekdays mon,tue,wed,thu,fri --prompt "..."
talo cron list
talo cron disable <job-id>
talo cron run-due
talo cron history [job-id]
```

첫 버전은 원문 사례에 필요한 매일/평일 `HH:MM`만 지원한다. 임의 cron 표현식 파서는 추가하지 않는다.

### 5.4 무인 실행 안전 경계

- 기본 권한은 `read_only`로 고정한다.
- 파일 변경·명령 실행·외부 전송은 예약 작업에서 실행하지 않는다.
- 각 실행은 `RunConfig`의 반복·시간 예산을 별도로 낮춘다.
- 실패는 기록하되 같은 슬롯을 무한 재시도하지 않는다.
- 산출물은 외부 채널로 바로 보내지 않고 Review Inbox에 저장한다.
- 비밀값, credential reference, 원문 전체 메시지는 일지에 포함하지 않는다.

## 6. P1 구현: 일일 업무일지와 미완료 이월

원문의 Slack·Gmail·Calendar 수집을 바로 도입하지 않고 다음 로컬 신호를 먼저 사용한다.

1. 당일 Talo 세션과 완료/중단 상태
2. 확정·수정된 decision/rule
3. handoff의 `next_actions`
4. Git commit 및 working tree 요약
5. 전날 일지에서 완료되지 않은 체크박스

기본 우선순위는 `마감/중단된 실행 > 다른 사람이 기다리는 검토 > 오늘 일정 연관 > 일반 후속 작업`이다. 일정과 상대방 정보가 없는 P1 초기판에서는 근거가 없는 우선순위를 추측하지 않고 `확인 필요`로 표시한다.

산출물 경로 제안:

```text
~/.talo/projects/<project-id>/daily/YYYY-MM-DD.md
```

외부 Notion/Slack 게시가 필요해도 이 로컬 원본을 먼저 생성하고 사람이 검토한 뒤 전송한다.

## 7. P1 구현: 영속 Review Inbox

현재 동기 `approval.required` 이벤트를 보존하면서, 비대화형 실행의 승인 요청을 SQLite에 남긴다.

```sql
CREATE TABLE approval_requests (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  scope_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('pending','approved','denied')),
  created_at REAL NOT NULL,
  decided_at REAL,
  decided_by TEXT
);
```

승인 이후 원래 도구 호출을 자동 재생하는 기능은 별도 단계다. 초기 구현은 요청·결정·감사 이력 보존에 집중한다.

## 8. 비목표

- Hermes Agent 소스 포크 또는 내장
- Telegram/Slack/Discord/WhatsApp 게이트웨이
- Gmail 전체 메일 OAuth 수집
- RSS/스크래핑 뉴스 집계
- 범용 cron 표현식 파서
- CLI SQLite와 Web JSON DB의 즉시 통합
- 승인 전 외부 채널 자동 발송

## 9. 검증 전략

단일 검증 명령:

```bash
npm run verify
```

이 명령은 ESLint, TypeScript, Node 계약 테스트, CLI pytest, Next.js production build를 순서대로 실행한다.

P0 핵심 회귀:

- 제안 → 확정 → 수정 → 폐기 전체 상태 전이
- 같은 상태 전이 재요청의 버전 불변
- 다른 프로젝트 기억 변경 거절
- 프로젝트 편집 모드에서 라이프사이클 변경 승인 필요
- delegated 모드에서 명시적 위임 실행 허용

## 10. 단계별 완료 기준

### P0 — 이번 변경

- [x] 기억 확정·수정·폐기 도구 등록
- [x] 사람 승인 경계
- [x] 멱등 상태 전이
- [x] 프로젝트 격리 회귀 테스트
- [x] 단일 Web·CLI 검증 명령

### P1 — 구현 완료

- [x] `scheduled_jobs` / `scheduled_runs` 마이그레이션과 슬롯 중복 선점 방지
- [x] `talo cron add/list/disable/run-due/history`
- [x] macOS launchd install/uninstall/status 및 설치 가이드
- [x] 일일 Markdown 업무일지와 cron 실행 후 원자 생성
- [x] handoff `next_actions` 및 전날 미완료 체크박스 이월
- [x] 영속 Review Inbox와 저장 전 비밀값 정제

### P2 — 실제 수요 확인 후

- [ ] Notion Inbox 게시 어댑터
- [ ] Slack/Gmail/Calendar 읽기 전용 수집기
- [ ] 프로젝트 회고 뉴스레터

## 11. 결정 요약

Talo는 Hermes처럼 “무엇이든 대신 실행하는 봇”보다 “어떤 모델을 쓰더라도 검증된 기억과 작업 맥락이 이어지는 시스템”에 집중한다. P0는 기존 메모리 도메인 로직을 도구·권한·테스트 계층까지 연결했고, P1은 OS 스케줄러, SQLite 멱등성, 읽기 전용 실행, 사람 Review Inbox라는 네 가지 제약 안에서 자동화를 완성했다.
