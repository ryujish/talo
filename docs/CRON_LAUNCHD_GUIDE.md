# macOS launchd 기반 Talo cron 무인 자동화 가이드

Talo의 `cron` 기능은 별도의 24시간 상주 백그라운드 데몬을 띄우지 않고, macOS의 표준 시스템 스케줄러인 `launchd`를 통해 매분 멱등성 있게 작업을 실행합니다.

---

## 1. 보안 및 설계 원칙

1. **자격증명 및 환경변수 격리**:
   - 생성되는 LaunchAgent plist에는 `talo cron run-due`와 프로젝트 작업 디렉터리(`WorkingDirectory`)만 기록됩니다.
   - API 키, 토큰, 환경변수(`EnvironmentVariables`)는 plist에 **절대 저장되지 않으며**, Talo가 실행될 때 자체 설정(`~/.talo/config.toml`)과 macOS Keychain에서 안전하게 해석합니다.
2. **엄격한 파일 권한 (0600)**:
   - plist 파일은 소유자만 읽고 쓸 수 있는 `0600` (`-rw-------`) 권한으로 생성됩니다.
3. **표준 주기 및 즉시 로드**:
   - `StartInterval`: `60`초 (매 1분마다 due 작업 점검).
   - `RunAtLoad`: `true` (로그인/부팅 시 자동 로드 및 점검).
4. **무인 실행 안전 경계 (Zero-Write)**:
   - `cron run-due`에 의해 실행되는 모델 작업은 기본적으로 `read_only` 권한 및 낮은 반복 예산(최대 8회)으로 격리 실행됩니다.
   - 승인이 필요한 작업은 임의 실행되지 않고 일시 정지됩니다.

---

## 2. CLI 명령어 사용법

### 2.1 예약 작업 등록
프로젝트 내에서 원하는 시각(HH:MM)과 요일의 작업을 등록합니다.

```bash
# 매일 오전 08:30 실행
talo cron add --name daily-standup --at 08:30 --prompt "어제 세션과 Git 변경점을 요약해줘"

# 평일(월~금) 오전 09:00 실행
talo cron add --name weekday-review --at 09:00 --weekdays mon,tue,wed,thu,fri --prompt "오늘 우선순위 체크리스트 작성"

# 등록된 예약 작업 목록 확인
talo cron list
```

### 2.2 LaunchAgent plist 생성 및 설치
프로젝트에 대응하는 macOS LaunchAgent plist 파일을 생성합니다.

```bash
# 1. 파일 내용 사전 미리보기 (Dry Run)
talo cron install --dry-run

# 2. 실제 plist 파일 생성 (~/Library/LaunchAgents/ai.talo.cron.<project_id>.plist)
talo cron install

# 3. 기존 파일 덮어쓰기 필요 시
talo cron install --force
```

### 2.3 launchd 서비스 등록 (활성화)
생성된 plist를 macOS `launchctl`에 등록합니다:

```bash
# 최신 macOS (macOS 11+ 권장):
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.talo.cron.<project_id>.plist

# 또는 레거시 방식:
launchctl load ~/Library/LaunchAgents/ai.talo.cron.<project_id>.plist
```

### 2.4 상태 점검
LaunchAgent plist 파일의 권한, 설정값 및 `launchctl` 활성 상태를 확인합니다:

```bash
talo cron status
```

출력 예시:
```text
macOS LaunchAgent 상태 — proj_0d488bdc8c5a
  서비스 라벨: ai.talo.cron.proj_0d488bdc8c5a
  파일 위치:   /Users/.../Library/LaunchAgents/ai.talo.cron.proj_0d488bdc8c5a.plist
  설치 여부:   설치됨
  파일 권한:   0o600 (0600 권장)
  실행 간격:   60초
  RunAtLoad:   True
  작업 경로:   /Users/.../Documents/Aitime/Talo
  launchd 등록: 활성 (loaded)
```

### 2.5 비활성화 및 제거

```bash
# 1. launchctl 서비스 등록 해제
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/ai.talo.cron.<project_id>.plist
# (또는 레거시 방식: launchctl unload ~/Library/LaunchAgents/ai.talo.cron.<project_id>.plist)

# 2. LaunchAgent plist 파일 삭제
talo cron uninstall
```

---

## 3. 로그 및 실행 이력 확인

- **CLI 실행 이력**:
  ```bash
  talo cron history
  talo cron history <job-id>
  ```
- **macOS launchd 출력 로그**:
  - 표준 출력: `~/.talo/projects/<project-id>/cron-<project-id>.log`
  - 표준 에러: `~/.talo/projects/<project-id>/cron-<project-id>.err`
