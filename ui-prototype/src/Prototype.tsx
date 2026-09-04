import { useState } from "react";
import {
  ArrowLeftIcon, BookmarkIcon, CaretDownIcon, ChatBubbleIcon, CheckCircledIcon,
  ChevronRightIcon, ClockIcon, Cross2Icon, FileTextIcon, GearIcon,
  LockClosedIcon, PaperPlaneIcon, Pencil2Icon, PersonIcon, PlayIcon, PlusIcon, ReloadIcon,
} from "@radix-ui/react-icons";
import { KeyboardInput, MobileScroll, useKeyboardInsets } from "./mobile";

type Screen = "home" | "think" | "switch" | "settings";
type Model = "GPT-5" | "Claude Sonnet" | "Gemini 2.5 Pro";

const models: { name: Model; provider: string; account: string; tone: string }[] = [
  { name: "GPT-5", provider: "GPT", account: "개인 계정", tone: "green" },
  { name: "Claude Sonnet", provider: "Claude", account: "개인 계정", tone: "orange" },
  { name: "Gemini 2.5 Pro", provider: "Gemini", account: "업무 계정", tone: "blue" },
];

function ThinkLogo() {
  return <span className="think-logo" aria-hidden="true"><ChatBubbleIcon /></span>;
}

function SaveActions() {
  return <div className="save-actions"><button><BookmarkIcon />기억</button><button><CheckCircledIcon />결정</button><button><FileTextIcon />근거</button></div>;
}

function BottomNav({ onSettings }: { onSettings: () => void }) {
  return <nav className="bottom-nav" aria-label="주요 메뉴"><button className="active"><ReloadIcon /><span>Journey</span></button><button><ChatBubbleIcon /><span>Insight</span></button><button onClick={onSettings}><PersonIcon /><span>Profile</span></button></nav>;
}

function HomeScreen({ model, onContinue, onSwitch, onSettings }: { model: Model; onContinue: () => void; onSwitch: () => void; onSettings: () => void }) {
  const current = models.find((item) => item.name === model)!;
  return <div className="home-shell">
    <MobileScroll className="app-screen home-scroll"><main className="home-screen" data-testid="home-screen">
      <header className="home-header"><h1>Think Along</h1><button><GearIcon />프로젝트</button></header>
      <p className="current-label"><span />현재 진행 중인 프로젝트</p>
      <section className="project-heading"><span className="folder-icon"><FileTextIcon /></span><div><h2>마케팅 전략 <Pencil2Icon /></h2><p>브랜드 성장과 퍼널 전환을 위한 마케팅 전략 수립</p></div></section>
      <section className="project-summary">
        <div className="summary-row"><CheckCircledIcon /><div><b>마지막 결정</b><strong>MVP에서는 사용자가 모델을 직접 선택</strong><small>2026-08-21 · 5분 전</small></div><span className="round-icon"><ChatBubbleIcon /></span></div>
        <div className="summary-divider" />
        <button className="summary-row next-task" onClick={onContinue}><ClockIcon /><div><b>다음에 이어갈 과제</b><strong>채널별 메시지 전략과 KPI 설정을 구체화하기</strong></div><ChevronRightIcon /></button>
      </section>
      <div className="home-actions"><button className="continue-button" onClick={onContinue}><PlayIcon />이어서 생각하기</button><button onClick={onContinue}><PlusIcon />새 Thinking</button></div>
      <button className="home-model" onClick={onSwitch}><span className={`provider-mark ${current.tone}`}>{current.provider.slice(0, 2)}</span><span>{current.provider} · {current.account} · {current.name}</span><CaretDownIcon /></button>
      <section className="recent"><h3>최근 Conversation</h3><div className="recent-list">{[["타겟 페르소나와 주요 페인포인트 정리","사용자 리서치 기반 인사이트 도출","1시간 전"],["경쟁사 포지셔닝과 차별점 분석","시장 반응과 강점 정리","어제"],["메시지 전략 초안 수립","핵심 메시지와 톤앤매너 정의","2일 전"]].map(([title,detail,time]) => <button key={title} onClick={onContinue}><span className="round-icon"><ChatBubbleIcon /></span><span><b>{title}</b><small>{detail}</small></span><time>{time}</time><ChevronRightIcon /></button>)}<button className="all-conversations" onClick={onContinue}>모든 Conversation 보기 <ChevronRightIcon /></button></div></section>
    </main></MobileScroll>
    <div className="home-nav"><BottomNav onSettings={onSettings} /></div>
  </div>;
}

function ThinkScreen({ model, onBack, onSwitch, onSettings }: { model: Model; onBack: () => void; onSwitch: () => void; onSettings: () => void }) {
  const { bottomInset } = useKeyboardInsets();
  const [message, setMessage] = useState("");
  const current = models.find((item) => item.name === model)!;
  return <div className="think-shell">
    <header className="think-header"><button className="icon-button" onClick={onBack} aria-label="프로젝트로 돌아가기"><ArrowLeftIcon /></button><button className="project-button" onClick={onBack}>마케팅 전략 <ChevronRightIcon /></button><strong>Think</strong><button className="model-button" onClick={onSwitch}>{current.provider} · {current.account} · {current.name}<CaretDownIcon /></button></header>
    <MobileScroll className="app-screen think-scroll"><main className="conversation" data-testid="think-screen">
      <p className="manual-note">사용자가 모델을 직접 선택합니다.</p>
      <div className="user-row"><span>오전 9:28</span><CheckCircledIcon /><div className="user-bubble">우리가 확정한 MVP 원칙을 정리해줘</div></div>
      <article className="message-block"><div className="message-meta"><ThinkLogo /><b>Think</b><span>오전 9:29</span><em className="status confirmed"><CheckCircledIcon />확정 결정</em></div><div className="assistant-card"><p>확정된 MVP 원칙을 다음과 같이 정리했습니다.</p><ol><li>핵심 문제에 집중한다.</li><li>한 가지 핵심 흐름만 제공한다.</li><li>측정 가능한 지표로 검증한다.</li><li>빠르게 만들고 빠르게 배운다.</li><li>사용자 피드백을 제품에 반영한다.</li></ol><SaveActions /></div></article>
      <article className="message-block"><div className="message-meta"><ThinkLogo /><b>Think</b><span>오전 9:33</span><em className="status reviewing"><ClockIcon />검토 중</em></div><div className="assistant-card compact"><p>모델 전환 시 전달 범위를 보여드립니다.</p><ul><li>현재 프로젝트: 마케팅 전략</li><li>현재 컨텍스트: 최근 12개 메시지</li><li>포함 항목: 확정 결정 1개, 검토 중 1개, 기억 2개</li><li>다음 모델에서도 위 범위를 유지합니다.</li></ul><SaveActions /></div></article>
    </main></MobileScroll>
    <div className="composer-area" style={{ bottom: bottomInset }}><div className="composer"><button aria-label="파일 첨부"><PlusIcon /></button><KeyboardInput value={message} onChange={(event) => setMessage(event.target.value)} placeholder="메시지를 입력하세요" aria-label="메시지" /><button className="send-button" aria-label="보내기"><PaperPlaneIcon /></button></div><BottomNav onSettings={onSettings} /></div>
  </div>;
}

function SwitchScreen({ current, onBack, onApply, onSettings }: { current: Model; onBack: () => void; onApply: (model: Model) => void; onSettings: () => void }) {
  const [selected, setSelected] = useState<Model>(current === "GPT-5" ? "Claude Sonnet" : "GPT-5");
  const from = models.find((item) => item.name === current)!;
  const to = models.find((item) => item.name === selected)!;
  return <MobileScroll className="app-screen detail-scroll"><main className="detail-screen" data-testid="switch-screen">
    <header className="detail-header"><button className="icon-button" onClick={onBack} aria-label="Think로 돌아가기"><ArrowLeftIcon /></button><h1>모델 전환</h1><button className="settings-link" onClick={onSettings}><GearIcon />AI 설정</button></header>
    <section className="route-card current"><small>현재</small><div><span className={`provider-mark ${from.tone}`}>{from.provider.slice(0, 2)}</span><b>{from.provider} · {from.account} · {from.name}</b></div></section><div className="route-arrow">↓</div>
    <section className="route-card"><small>변경</small><button className="destination" onClick={() => setSelected(selected === "Claude Sonnet" ? "Gemini 2.5 Pro" : "Claude Sonnet")}><span className={`provider-mark ${to.tone}`}>{to.provider.slice(0, 2)}</span><b>{to.provider} · {to.account} · {to.name}</b><CaretDownIcon /></button></section>
    <section className="context-card"><div className="section-title"><h2>전달할 Context</h2><span><CheckCircledIcon />포함 5개</span></div>{[["프로젝트 목표","1개"],["확정 결정 3개","3개"],["검토 중 의견 2개","2개"],["사용자 선호","1개"],["최근 대화 12개","12개"]].map(([label,count]) => <div className={`context-row ${label.startsWith("검토") ? "review" : ""}`} key={label}><CheckCircledIcon /><b>{label}</b><span>{count}</span></div>)}</section>
    <section className="excluded-card"><div className="section-title"><h2>제외</h2><span className="muted">제외 2개</span></div><div className="excluded-row"><LockClosedIcon /><span><b>API Key</b><small>보안 및 계정 연결 정보는 전달되지 않습니다.</small></span><Cross2Icon /></div><div className="excluded-row"><FileTextIcon /><span><b>비공개 파일</b><small>업로드한 비공개 자료는 전달되지 않습니다.</small></span><Cross2Icon /></div></section>
    <div className="continuity"><CheckCircledIcon /><span><b>같은 프로젝트와 세션을 유지합니다</b><small>프로젝트 구조, 결정, 기억과 대화 흐름은 이어집니다.</small></span></div><button className="primary-action" onClick={() => onApply(selected)}><ReloadIcon />이 Context로 전환</button><button className="secondary-action" onClick={onBack}>취소</button>
  </main></MobileScroll>;
}

function SettingsScreen({ model, onBack, onChoose }: { model: Model; onBack: () => void; onChoose: (model: Model) => void }) {
  return <MobileScroll className="app-screen detail-scroll"><main className="detail-screen settings-screen" data-testid="settings-screen"><header className="detail-header"><button className="icon-button" onClick={onBack}><ArrowLeftIcon /></button><h1>AI 설정</h1></header><p className="settings-intro">사용할 AI 계정과 기본 모델을 직접 관리합니다.</p>
    <section className="settings-section"><div className="section-title"><h2>연결된 AI</h2><button>계정 추가</button></div>{models.map((item) => <button className={`account-card ${item.name === model ? "selected" : ""}`} key={item.name} onClick={() => onChoose(item.name)}><span className={`provider-mark ${item.tone}`}>{item.provider.slice(0, 2)}</span><span><b>{item.provider}</b><small>{item.account} · {item.name}</small></span>{item.name === model ? <CheckCircledIcon /> : <ChevronRightIcon />}</button>)}</section>
    <section className="settings-section"><h2>전환 원칙</h2><div className="policy-card"><CheckCircledIcon /><span><b>항상 직접 선택</b><small>한도 초과나 오류가 발생해도 자동으로 다른 모델로 바꾸지 않습니다.</small></span></div><div className="policy-card"><LockClosedIcon /><span><b>Context는 Think Along이 관리</b><small>AI 회사의 독립 기억이나 스레드에 의존하지 않습니다.</small></span></div></section>
  </main></MobileScroll>;
}

export default function Prototype() {
  const [screen, setScreen] = useState<Screen>("home");
  const [model, setModel] = useState<Model>("GPT-5");
  const [switchOrigin, setSwitchOrigin] = useState<"home" | "think">("think");
  const openSwitch = (origin: "home" | "think") => { setSwitchOrigin(origin); setScreen("switch"); };
  if (screen === "switch") return <SwitchScreen current={model} onBack={() => setScreen(switchOrigin)} onApply={(next) => { setModel(next); setScreen(switchOrigin); }} onSettings={() => setScreen("settings")} />;
  if (screen === "settings") return <SettingsScreen model={model} onBack={() => setScreen("home")} onChoose={setModel} />;
  if (screen === "think") return <ThinkScreen model={model} onBack={() => setScreen("home")} onSwitch={() => openSwitch("think")} onSettings={() => setScreen("settings")} />;
  return <HomeScreen model={model} onContinue={() => setScreen("think")} onSwitch={() => openSwitch("home")} onSettings={() => setScreen("settings")} />;
}
