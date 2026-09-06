# Talo

Talo는 한 프로젝트의 세션·기억·검증 기록을 유지하면서 OpenAI, Claude,
DeepSeek, Kimi, OpenCode Zen, Google AGY 등 여러 AI 모델을 전환해 사용하는
개발자 CLI입니다. 활성 제품 코어는 `cli/`의 Python 패키지입니다.

루트의 Next.js 코드는 Think Along에서 이어진 웹 코드이며, 현재는 Talo의 공급자
계정·모델 선택·연결 테스트 UI를 담당합니다. CLI와 웹을 분리하기 전까지 호환
웹 인터페이스로 유지합니다.

## 저장소 구조

| 경로 | 역할 |
| --- | --- |
| `cli/src/talo/` | Talo CLI, 런타임, 모델 연결, 기억 및 도구 |
| `cli/tests/` | Python CLI 단위·통합 테스트 |
| `app/`, `components/`, `lib/` | Think Along 기반 Talo 웹 연결 인터페이스 |
| `tests/` | 웹 아키텍처 계약 테스트 |
| `docs/` | 연결 UI, 자동화 및 아키텍처 설계 문서 |

## CLI v0.2 빠른 시작

이미 개발 환경이 설치된 경우:

```bash
cli/.venv/bin/talo demo
cli/.venv/bin/talo
```

로컬 런타임 포함 배포본은 `./cli/dist/portable/talo/talo`로 실행합니다.
`portable/talo` 폴더 전체가 필요하며 별도 Python·Node 설치는 필요하지 않습니다.
첫 실행 지연과 배포 검증 범위는 아래 CLI v0.2 안내에 기록했습니다.
새 개발 환경 설치는 Python만으로 CLI를 구성할 수 있습니다:

```bash
python3 -m venv cli/.venv
cli/.venv/bin/pip install -e cli
cli/.venv/bin/talo setup
```

Node/npm은 웹 개발용입니다. CLI 사용자용 독립 실행 파일에는 Python 런타임을 포함합니다.
Homebrew 공개 등록은 아직 수행하지 않았습니다.

v0.2는 파일 변경 제안·컬러 diff 검토·체크포인트·`/undo`, 최근 세션 재개와 구조화 인계,
macOS 외부 CLI 파일 쓰기 격리, `talo serve` stdio 코어를 제공합니다.
구현 범위·실행법·남은 배포 단계는 [CLI v0.2 안내](docs/TALO_CLI_v0.2_IMPLEMENTATION.md)를 참고하세요.

대화 중 `/model`로 공급자 계열과 하위 모델을 선택하고, `/help`로 전체 명령을
확인합니다. 종료는 `/quit` 또는 유휴 상태에서 `Ctrl+C` 두 번입니다.

로컬 OAuth CLI를 직접 등록할 수도 있습니다.

```bash
cli/.venv/bin/talo connect add --provider codex --model-id gpt-5.6-sol
cli/.venv/bin/talo connect add --provider opencode --model-id opencode/big-pickle
cli/.venv/bin/talo connect add --provider agy --model-id gemini-3.8-flash-high
```

외부 CLI 연결은 macOS 임시 작업 공간에서 파일 쓰기를 제한해 실행합니다.
원본 파일은 변경 결과를 검토한 뒤 적용합니다. CLI 자체 인증·캐시 호환성은 도구별 확인이 필요합니다.

설정·모델 메뉴는 `↑`/`↓`와 Enter로 탐색합니다. Think Along MCP와 Orca 작업
주입은 다음 명령으로 연결합니다.

```bash
THINK_ALONG_OAUTH_KEY=... cli/.venv/bin/talo mcp think-along
cli/.venv/bin/talo mcp stdio -- codex mcp-server
cli/.venv/bin/talo orchestrate TASK_ID TERMINAL_HANDLE --run RUN_ID
```

`orchestrate`는 Orca가 반환한 작업 preamble을 지정한 Talo 터미널에 그대로
주입합니다. 웹 동기화는 API 키가 아닌 공급자·모델·상태 메타데이터만 서버에
저장합니다.

## 주요 기능

- 세션·메시지·공유 기억의 SQLite 영속화와 모델 전환 후 연속성
- 프로젝트 범위 도구 권한, 승인 Inbox, 비밀값 정제
- Codex·OpenCode·AGY OAuth CLI 및 OpenAI 호환 API 연결
- HTTP/SSE·stdio MCP 연결과 Orca 터미널 작업 주입
- 파일 잠금 기반 다중 Talo 설정 병합, 웹·서버 AI 연결 메타데이터 동기화
- 예약 작업, macOS launchd 연동, 일일 Markdown 업무일지
- Think Along 웹의 AI 공급자 계정·모델 선택·연결 테스트 UI

## 개발 및 검증

```bash
npm run dev
npm run verify
```

`npm run verify`는 ESLint, TypeScript, Node 계약 테스트, Python CLI 테스트,
Next.js 프로덕션 빌드를 한 번에 실행합니다.

상세 설계는 `docs/TALO_HERMES_AUTOMATION_TECH_DESIGN.md`와
`docs/TALO_HERMES_CONNECTION_UI_PRD.md`를 참고하세요.
