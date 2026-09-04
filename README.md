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

## 빠른 시작

```bash
npm install
python3.12 -m venv cli/.venv
cli/.venv/bin/pip install -e cli
cli/.venv/bin/talo setup
cli/.venv/bin/talo
```

대화 중 `/model`로 공급자 계열과 하위 모델을 선택하고, `/help`로 전체 명령을
확인합니다. 종료는 `/quit` 또는 유휴 상태에서 `Ctrl+C` 두 번입니다.

로컬 OAuth CLI를 직접 등록할 수도 있습니다.

```bash
cli/.venv/bin/talo connect add --provider codex --model-id gpt-5.6-sol
cli/.venv/bin/talo connect add --provider opencode --model-id opencode/big-pickle
cli/.venv/bin/talo connect add --provider agy --model-id gemini-3.8-flash-high
```

AGY 연결은 사용자가 명시적으로 선택한 경우 `--dangerously-skip-permissions`로
실행됩니다. 프로젝트 수정 권한을 부여하기 전에 대상 저장소를 확인하세요.

## 주요 기능

- 세션·메시지·공유 기억의 SQLite 영속화와 모델 전환 후 연속성
- 프로젝트 범위 도구 권한, 승인 Inbox, 비밀값 정제
- Codex·OpenCode·AGY OAuth CLI 및 OpenAI 호환 API 연결
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
