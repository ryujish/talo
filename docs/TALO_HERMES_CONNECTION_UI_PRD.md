# [PRD] Talo AI Connection Hub — 헤르메스(Hermes) UI 스타일 연결 시스템 기획서

- **문서 버전**: v1.0.0
- **상태**: Draft / Review
- **대상 모듈**: Talo CLI (`cli/src/talo`), Talo Web (`app/`, `components/`)
- **작성일**: 2026-09-03
- **참조 벤치마크**: Hermes Agent TUI (`hermes --tui`), Hermes Setup Wizard (`hermes setup`), Hermes Web Dashboard

---

## 1. 배경 및 문제 정의 (Problem Statement)

### 1.1 현황 (As-Is)
현재 Talo의 `talo connect`는 순수 OpenAI 호환 HTTP API(`/chat/completions`)의 수동 파라미터 등록 방식만 제공합니다.
사용자는 로컬 환경에 이미 설치되어 동작 중인 도구들(DeepCode, Codex, AGY, OpenCode 등)을 연결하기 위해 다음과 같은 복잡하고 번거로운 과정을 거쳐야 합니다:

```bash
# 사용자가 직접 엔드포인트 URL, 모델 ID, 환경변수 플래그를 모두 조사하고 수동 입력해야 함
talo connect add --provider deepcode \
  --base-url "$BASE_URL" \
  --model-id "$MODEL" \
  --api-key-env API_KEY

# 연결 후에도 수동으로 검증 및 사용 지정 필요
talo connect validate
talo connect use deepcode:deepseek-v4-pro
```

### 1.2 핵심 페인 포인트 (Pain Points)
1. **암기형·명령줄 피로 (CLI Fatigue)**:
   - 각 공급자별 base URL 규격(`v1`, `v1beta/openai`), 모델명 식별자, 환경변수 이름을 사용자가 외우거나 스크립트로 파악해야 함.
2. **도구별 인증 체계의 불일치**:
   - **DeepCode**: 환경변수(`BASE_URL`, `MODEL`, `API_KEY`) 사용.
   - **Codex**: ChatGPT OAuth 토큰(`~/.codex/auth.json`)을 사용하여 일반 HTTP API 키 연결 불가.
   - **AGY**: 자체 인증 구조를 사용하여 엔드포인트 수동 우회 필요.
   - **OpenCode**: `~/.local/share/opencode/auth.json`에 저장된 provider 키를 수동으로 추출해야 함.
3. **시각적 상태 및 피드백 부재**:
   - 어떤 공급자가 정상 연결되었는지, 지연시간(latency)은 얼마인지, 어떤 모델이 사용 가능한지 터미널이나 웹에서 한눈에 파악하기 어려움.
4. **프로토콜 제한성**:
   - 순수 HTTP 엔드포인트만 허용하여, CLI 서브프로세스나 MCP(Model Context Protocol) 기반 연동(예: `codex mcp-server`, Think Along MCP)을 활용하지 못함.

---

## 2. 제품 비전 및 목표 (Vision & Goals)

> **"Zero-Memorization, 1-Click Auto-Discovery, Multi-Bridge"**
> 명령어를 외우지 않아도 로컬에 설치된 도구를 1초 만에 감지하고,
> Hermes UI 스타일의 직관적인 인터랙티브 마법사(TUI)와 웹 대시보드로 손쉽게 AI를 전환·관리한다.

### 2.1 핵심 목표
1. **로컬 자동 감지 (Auto-Discovery Engine)**:
   - DeepCode, Codex, AGY, OpenCode, Ollama, LM Studio를 시작 시 자동 스캔하여 **"1-Click 등록"** 제안.
2. **Hermes 스타일 인터랙티브 TUI 마법사 (`talo setup` / `talo connect -i`)**:
   - 화살표 키, 숫자 단축키(`1-9`), 상태 뱃지, 실시간 연결 프로브(Live Ping)가 포함된 터미널 인터페이스 제공.
3. **Talo Web Connection Dashboard**:
   - 웹 애플리케이션 내에 공급자별 상태 카드, 모델 드롭다운(실시간 `/models` 패치), 레이턴시 표시, 시각적 토글 스위치 구축.
4. **하이브리드 멀티 브릿지 (Multi-Bridge Architecture)**:
   - Direct HTTP API뿐만 아니라 **CLI 서브프로세스 브릿지** 및 **MCP 서버 브릿지**(Think Along 공식 MCP 포함)를 통합 지원.

---

## 3. 시스템 아키텍처 (Architecture)

```
┌────────────────────────────────────────────────────────────────────────┐
│                        User Interfaces (UI Layer)                      │
│                                                                        │
│   [ Talo CLI TUI ]                            [ Talo Web Dashboard ]   │
│   - `talo setup` (인터랙티브 마법사)           - `/settings/connections`│
│   - `talo connect -i` (화살표 네비게이션)      - 공급자 카드 & 실시간 토글│
│   - 마스킹 비밀번호 & Keychain 연동           - 실시간 모델 드롭다운    │
└──────────────────┬─────────────────────────────────┬───────────────────┘
                   │                                 │
                   ▼                                 ▼
┌────────────────────────────────────────────────────────────────────────┐
│               Talo Unified Connection Manager (Core Layer)             │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Auto-Discovery Scanner                        │  │
│  │  - Env Scanner (DeepCode, OpenAI, Gemini, OpenRouter)            │  │
│  │  - Local Auth Scanner (~/.codex, ~/.local/share/opencode)        │  │
│  │  - Local Port Probe (Ollama :11434, LM Studio :1234, vLLM)       │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Multi-Bridge Dispatcher                       │  │
│  │  [Bridge A: Direct HTTP]  [Bridge B: CLI Process] [Bridge C: MCP] │  │
│  │  OpenAI-compat API        Subprocess JSON-RPC     stdio / SSE /     │
│  │  (OpenRouter, DeepSeek)   (Codex, OpenCode)       Think Along MCP   │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │             Credential & Config Vault (~/.talo/config.toml)      │  │
│  │  - macOS Keychain / Linux SecretService / Env References         │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 4. 상세 기능 기획 (Feature Specifications)

### 4.1 Feature 1: 로컬 AI 환경 자동 감지 (Auto-Discovery Engine)

Talo 실행 또는 `talo connect` 진입 시 로컬 머신의 환경을 비동기 스캔하여 즉시 연결 가능한 프리셋을 도출합니다.

| 대상 도구 | 감지 소스 / 로직 | 자동 제안 형태 | 연결 방식 |
|---|---|---|---|
| **DeepCode** | `$BASE_URL`, `$MODEL`, `$API_KEY` 환경변수 존재 여부 | `DeepCode (deepseek-v4-pro)` [즉시 활성화] | Direct HTTP API (`api.deepseek.com`) |
| **Codex** | 1) `~/.codex/auth.json` 존재<br>2) `which codex` 바이너리 존재 | `Codex CLI Bridge` 또는 `OpenAI API Key 입력` | CLI stdio MCP (`codex mcp-server`) 또는 OpenAI Direct |
| **OpenCode** | `~/.local/share/opencode/auth.json` 파싱 | `OpenCode Provider (등록된 키 재사용)` | Direct HTTP (추출된 Base URL + API Key) |
| **AGY** | `~/.gemini`, `GEMINI_API_KEY`, 또는 gcloud 인증 | `AGY / Google Gemini 3.8` [프리셋 완성] | Gemini OpenAI 호환 엔드포인트 |
| **로컬 오픈웨이트** | `localhost:11434` (Ollama), `localhost:1234` (LM Studio) | `Ollama (llama3.1 / qwen2.5)` 감지됨 | Local OpenAI-compat HTTP |
| **Think Along 공식 MCP** | 내장 프리셋 제공 | `Think Along Cloud MCP` | MCP Stream (`https://mcp.flowpulse.ai.kr/mcp`) |

---

### 4.2 Feature 2: Hermes 스타일 인터랙티브 TUI (`talo setup` & `talo connect -i`)

명령줄 인자를 주렁주렁 적지 않고, Hermes TUI(`hermes --tui` 및 `hermes setup`)처럼 키보드로 직관적으로 조작하는 화면입니다.

#### 4.2.1 TUI 진입 화면 (ASCII 목업)
```text
┌─────────────────────────────────────────────────────────────────────────┐
│  Talo AI Connection Hub                                       v0.1.0    │
│  방향키 (↑/↓), 선택 (Enter), 즉시선택 (1-9), 검증 (v), 나가기 (Esc)       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  [ 감지된 로컬 환경 (Auto-Discovered) ]                                  │
│  ● 1. DeepCode        deepseek-v4-pro    [준비됨 - Enter로 활성화]      │
│  ○ 2. OpenCode        claude-3-7-sonnet  [auth.json 감지됨 - 1클릭 등록] │
│  ○ 3. Ollama (Local)  qwen2.5:14b        [localhost:11434 온라인]       │
│                                                                         │
│  [ 클라우드 & 프리셋 공급자 (Cloud & Custom) ]                          │
│  ○ 4. OpenRouter      openrouter/auto    [API 키 필요]                  │
│  ○ 5. OpenAI / Codex  gpt-5.6-sol        [OAuth 또는 API Key]           │
│  ○ 6. Google Gemini   gemini-3.8-flash   [OpenAI 엔드포인트]            │
│  ○ 7. Think Along MCP FlowPulse MCP      [OAuth Key 등록됨]             │
│  ○ 8. 직접 입력 (Custom OpenAI Compatible)                              │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│  [현재 활성 모델]: deepcode:deepseek-v4-pro (지연시간: 142ms, 정상 ●)    │
│  <Enter: 선택/수정>  <Space: 기본모델지정>  <v: 전체검증>  <d: 삭제>     │
└─────────────────────────────────────────────────────────────────────────┘
```

#### 4.2.2 인터랙션 규칙
1. **원클릭 빠른 선택 (Single-Key Quick Pick)**:
   - `1`~`9`를 누르면 즉시 해당 공급자의 설정 모달로 진입.
2. **보안 마스킹 입력**:
   - API 키 입력 시 쉘 히스토리에 남는 플래그 대신, 터미널 숨김 입력(`getpass`) 지원.
   - 키 저장 위치를 1번 클릭으로 선택: `[1] macOS Keychain` / `[2] .env 변수 참조` / `[3] 세션 전용 메모리`.
3. **즉시 연결 프로브 (Live Probe on Confirm)**:
   - 설정을 완료하고 저장을 누르면 백그라운드에서 `models` 또는 `test completion` 호출(100토큰 미만)을 1초 내에 수행.
   - 성공 시 초록색 `● Connected (142ms)` 표시, 실패 시 구체적인 오류 원인(인증 실패, 타임아웃, URL 형식 오류)을 즉시 진단 출력.

---

### 4.3 Feature 3: Talo Web Connection Dashboard (웹 설정 허브)

Think Along / Talo 웹 애플리케이션(`/settings/connections` 또는 모바일 뷰 `/aiAccounts`)의 개선 사양입니다.

#### 4.3.1 화면 레이아웃 & 컴포넌트 구성
1. **발견된 로컬 연결 배너 (Quick Onboarding Banner)**:
   - 페이지 상단에 로컬 데스크톱/CLI에서 감지된 AI 도구가 카드 형태로 표시:
     *"로컬에서 DeepCode 및 OpenCode 환경이 발견되었습니다. 클릭 한 번으로 Talo 웹 세션에 연결하세요."*
2. **공급자 카드 그리드 (Provider Cards)**:
   - 각 카드별 항목:
     - 공급자 로고/아이콘 (DeepSeek, OpenAI, Anthropic, Gemini, OpenCode, Hermes 등)
     - 연결 상태 뱃지 (`연결됨`, `미연결`, `오류`, `자동 감지됨`)
     - 현재 선택된 모델명 및 지연시간 태그 (`120ms`)
     - 기능 지원 뱃지 (`Tools`, `Vision`, `Streaming`)
     - [기본 모델로 사용] 라디오 버튼
     - [연결 테스트] 버튼
3. **공급자 추가/편집 모달 (Hermes Studio 스타일)**:
   - **프리셋 탭**: 드롭다운에서 공급자를 선택하면 Base URL이 자동 채워짐.
   - **모델 자동 조회 (Fetch Models)**: Base URL과 API Key를 입력한 뒤 `[모델 목록 불러오기]`를 누르면 `/v1/models` 엔드포인트를 호출하여 드롭다운 리스트를 자동 완성.
   - **인증 방식 선택**: `직접 키 입력 (Keychain/로컬 암호화)`, `환경변수명 참조 ($API_KEY)`, `로컬 파일 연동`.

---

### 4.4 Feature 4: 하이브리드 멀티 브릿지 (Multi-Bridge Engine)

기존의 "OpenAI HTTP API만 허용"하는 제약을 극복하고, 다양한 로컬 도구의 고유 프로토콜을 포용하는 3대 브릿지 구조입니다.

#### 1) Direct HTTP Bridge (기존 확장)
- 표준 OpenAI 호환 `/chat/completions` API를 사용하는 서비스 (OpenRouter, DeepSeek, Ollama 등).
- 스트리밍 SSE 및 JSON 스키마 구조화 출력 지원.

#### 2) CLI Subprocess Bridge (Hermes Bridge 패턴)
- Codex CLI, OpenCode CLI, AGY CLI처럼 로컬 바이너리가 이미 인증 세션을 가지고 있는 경우 활용.
- Think Along의 `hermes_bridge.py` 아키텍처를 계승:
  - `talo`가 백그라운드 서브프로세스로 해당 CLI를 기동하고 표준 입출력(stdio JSON-RPC)으로 대화 패킷 전달.
  - 사용자가 OAuth 토큰을 억지로 꺼내거나 API 키를 이중 발급받을 필요 없이, 로컬 CLI 권한 그대로 활용.

#### 3) MCP Server Bridge (Model Context Protocol)
- stdio 또는 SSE 기반 MCP 서버 연동.
- **Codex MCP**: `codex mcp-server`를 stdio로 등록하여 Codex 도구와 추론 능력을 Talo에 주입.
- **Think Along 서버 MCP (공식 내장)**:
  - 엔드포인트: `https://mcp.flowpulse.ai.kr/mcp`
  - 인증: `THINK_ALONG_OAUTH_KEY` 환경변수 또는 macOS Keychain
  - 원격 메모리, 크로스 세션 컨텍스트, 조직 지식베이스를 Talo 세션에 즉시 바인딩.

---

## 5. 사용자 인터랙션 플로우 (UX Workflows)

### 5.1 시나리오 A: DeepCode 사용자 (10초 온보딩)
1. 사용자가 터미널에서 `talo setup` 실행.
2. 스캐너가 환경변수 `$BASE_URL`, `$MODEL`, `$API_KEY`를 감지하여 1번에 표시:
   `[1] DeepCode (deepseek-v4-pro) - 이미 환경변수가 설정되어 있습니다.`
3. 사용자가 숫자 `1` 또는 `Enter` 입력.
4. 백그라운드 핑 1회 실행 후:
   `✓ DeepCode 연결 성공 (135ms). 기본 모델로 지정되었습니다!`
5. 완료. 더 이상 수동 타이핑 불필요.

### 5.2 시나리오 B: Codex / ChatGPT OAuth 사용자
1. 사용자가 `talo setup` 실행 후 `[Codex]` 선택.
2. Talo가 `~/.codex/auth.json` 감지:
   *"Codex CLI 인증 세션이 감지되었습니다. 연결 방식을 선택하세요:"*
   - `(1) Codex MCP Server Bridge (추천: 기존 로그인 세션 유지)`
   - `(2) OpenAI API Key 직접 입력`
3. 사용자가 `1` 선택 시 `codex mcp-server` stdio 브릿지 자동 등록 및 즉시 검증.

### 5.3 시나리오 C: 웹 대시보드에서의 모델 전환
1. 사용자가 Talo 웹 UI 우측 상단의 AI 배지 클릭.
2. 팝업 드롭다운에서 등록된 공급자 카드들이 레이턴시 신호등(초록/노랑)과 함께 노출.
3. 원하는 모델을 클릭하면 현재 작업 세션의 추론 엔진이 즉시 전환됨.

---

## 6. 설정 파일 및 데이터 스키마 (Configuration Schema)

`~/.talo/config.toml` 포맷을 하이브리드 브릿지 구조에 맞게 고도화합니다:

```toml
[general]
default_model = "deepcode:deepseek-v4-pro"
auto_discovery = true

# Bridge Type 1: Direct HTTP
[connections.deepcode]
bridge = "direct_http"
provider = "deepseek"
base_url = "https://api.deepseek.com"
model_id = "deepseek-v4-pro"
credential_ref = "env:API_KEY"
status = "active"

# Bridge Type 2: CLI Subprocess
[connections.codex_cli]
bridge = "cli_subprocess"
command = "codex"
args = ["mcp-server"]
model_id = "gpt-5.6-sol"
status = "active"

# Bridge Type 3: Remote MCP Server
[connections.think_along_mcp]
bridge = "mcp_sse"
url = "https://mcp.flowpulse.ai.kr/mcp"
credential_ref = "env:THINK_ALONG_OAUTH_KEY"
status = "active"
```

---

## 7. 구현 로드맵 및 마일스톤 (Implementation Roadmap)

### Phase 1 (P0): CLI 대화형 온보딩 & 로컬 자동 감지 (1주 차)
- [x] 환경변수 및 로컬 auth 파일(Codex, OpenCode, AGY) 자동 스캔 구현.
- [x] `talo setup` Rich 기반 번호 선택 TUI 마법사 구현. 화살표 탐색은 후속 개선 항목.
- [x] DeepCode, OpenRouter, Gemini 및 로컬 CLI 프리셋 내장.
- [x] API 연결 Live Ping·모델 조회와 로컬 CLI 설치/OAuth 상태 검증 결과 표시.

### Phase 2 (P1): Web AI Connection Hub 고도화 (2주 차)
- [ ] Next.js 웹 내 `/api/ai/discovery` 엔드포인트 신설.
- [x] 웹 공급자 계정 화면, 공급자 카드, 연결 테스트, 모델 선택 UI 제작.
- [ ] 로컬 스토리지 및 서버 계정 간의 양방향 동기화.

### Phase 3 (P2): CLI Subprocess & MCP 하이브리드 브릿지 (3주 차)
- [ ] `talo.integrations.mcp`: stdio 및 HTTP/SSE MCP 클라이언트 연동.
- [ ] Think Along 공식 MCP (`https://mcp.flowpulse.ai.kr/mcp`) 원클릭 프리셋 활성화.
- [x] Codex·OpenCode·AGY OAuth CLI subprocess 브릿지 추가.

---

## 8. 완료 정의 및 검증 기준 (Definition of Done)

1. **사용성 지표 (UX Metric)**:
   - 로컬에 이미 DeepCode 또는 OpenCode 환경이 있는 사용자가 첫 연결까지 걸리는 시간 **< 15초**.
   - 사용자가 긴 URL이나 복잡한 CLI 옵션을 타이핑하는 횟수 **0회**.
2. **품질 및 안정성**:
   - `talo setup` 및 `talo connect`의 모든 분기에 대해 단위 테스트 작성 완료.
   - 키체인 마스킹 저장 및 환경변수 누출 방지(보안 감사 통과).
   - 기존 `npm run verify` 및 Python CLI 테스트 스위트 100% 통과 유지.
