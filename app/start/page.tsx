'use client';

import { ArrowRight, Bot, Brain, Check, ChevronRight, Sparkles } from 'lucide-react';
import { useMemo, useState } from 'react';

const examples = ['새 사업 아이디어를 정리하고 싶어요', '이직할지 계속 고민 중이에요', 'AI를 활용한 서비스를 만들고 싶어요'];
const models = ['GPT', 'Claude', 'Gemini'];

function finishOnboarding(firstThought?: string) {
  try {
    if (firstThought?.trim()) {
      window.localStorage.setItem('think_along_first_thought', firstThought.trim());
    }
    window.localStorage.setItem('think_along_onboarding_v1', 'done');
  } catch {}
  document.cookie = 'think_along_onboarding_v1=done; path=/; max-age=31536000; SameSite=Lax';
  window.location.replace('/?onboarding=complete');
}


export default function StartPage() {
  const [step, setStep] = useState(0);
  const [thought, setThought] = useState('');
  const progress = [18, 58, 100][step];
  const previewTitle = useMemo(() => {
    const value = thought.trim();
    if (!value) return '나의 첫 Thinking';
    return value.length > 28 ? `${value.slice(0, 28)}…` : value;
  }, [thought]);

  return (
    <main className="min-h-screen px-4 py-5 sm:px-6" style={{ backgroundColor: 'var(--bg-primary)', color: 'var(--text-primary)' }}>
      <section className="mx-auto flex min-h-[calc(100vh-40px)] w-full max-w-[520px] flex-col overflow-hidden rounded-[24px] border shadow-[0_24px_90px_rgba(0,0,0,0.32)]" style={{ borderColor: 'var(--border-primary)', backgroundColor: 'var(--bg-secondary)' }}>
        <header className="flex items-center gap-3 px-6 pb-4 pt-6">
          <div className="grid h-10 w-10 place-items-center rounded-xl text-[#021b12]" style={{ backgroundColor: 'var(--accent-green)' }}>
            <Sparkles size={21} fill="currentColor" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[15px] font-black tracking-tight">Think Along</p>
            <p className="text-[11px] font-semibold" style={{ color: 'var(--text-secondary)' }}>30초면 핵심을 체험할 수 있어요</p>
          </div>
          <button onClick={() => finishOnboarding()} className="text-[12px] font-bold" style={{ color: 'var(--text-secondary)' }}>건너뛰기</button>
        </header>

        <div className="mx-6 h-1 overflow-hidden rounded-full" style={{ backgroundColor: 'var(--border-primary)' }}>
          <div className="h-full rounded-full transition-all duration-500" style={{ width: `${progress}%`, backgroundColor: 'var(--accent-green)' }} />
        </div>

        {step === 0 && (
          <div className="flex flex-1 flex-col px-6 pb-7 pt-10">
            <p className="text-[12px] font-black uppercase tracking-[0.16em]" style={{ color: 'var(--accent-green)' }}>One memory. Any AI.</p>
            <h1 className="mt-4 text-[34px] font-black leading-[1.18] tracking-[-0.045em]">
              AI는 바뀌어도,<br />당신의 생각은 이어집니다.
            </h1>
            <p className="mt-5 text-[15px] font-semibold leading-7" style={{ color: 'var(--text-secondary)' }}>
              Think Along은 AI를 고르는 앱이 아니라, <strong style={{ color: 'var(--text-primary)' }}>당신의 생각과 맥락을 기억하는 공간</strong>입니다.
            </p>

            <div className="mt-9 rounded-2xl border p-4" style={{ borderColor: 'var(--border-primary)', backgroundColor: 'var(--bg-tertiary)' }}>
              <div className="flex items-center gap-3">
                <span className="grid h-11 w-11 place-items-center rounded-xl" style={{ backgroundColor: 'var(--accent-green-soft)', color: 'var(--accent-green)' }}><Brain size={22} /></span>
                <div>
                  <p className="text-[13px] font-black">하나의 Shared Memory</p>
                  <p className="mt-1 text-[11px] font-semibold" style={{ color: 'var(--text-secondary)' }}>프로젝트 · 결정 · 질문 · 맥락</p>
                </div>
              </div>
              <div className="mt-4 grid grid-cols-3 gap-2">
                {models.map((model) => (
                  <div key={model} className="rounded-xl border px-2 py-3 text-center" style={{ borderColor: 'var(--border-primary)', backgroundColor: 'var(--bg-secondary)' }}>
                    <Bot className="mx-auto" size={17} style={{ color: 'var(--accent-green)' }} />
                    <p className="mt-1 text-[11px] font-extrabold">{model}</p>
                    <p className="mt-1 text-[9px] font-semibold" style={{ color: 'var(--text-secondary)' }}>같은 맥락</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="mt-auto pt-8">
              <button onClick={() => setStep(1)} className="flex h-13 w-full items-center justify-center gap-2 rounded-xl px-5 text-[15px] font-black text-[#021b12] shadow-[0_12px_28px_var(--shadow-glow)]" style={{ height: 52, backgroundColor: 'var(--accent-green)' }}>
                내 생각으로 체험하기 <ArrowRight size={18} />
              </button>
              <p className="mt-3 text-center text-[11px] font-semibold" style={{ color: 'var(--text-tertiary)' }}>로그인 · API Key 없이 먼저 체험합니다.</p>
            </div>
          </div>
        )}

        {step === 1 && (
          <div className="flex flex-1 flex-col px-6 pb-7 pt-10">
            <p className="text-[12px] font-black" style={{ color: 'var(--accent-green)' }}>STEP 2 · 첫 Thinking</p>
            <h1 className="mt-3 text-[29px] font-black leading-[1.25] tracking-[-0.04em]">지금 머릿속에 있는<br />생각 하나만 적어보세요.</h1>
            <p className="mt-4 text-[14px] font-semibold leading-6" style={{ color: 'var(--text-secondary)' }}>완성된 질문일 필요 없습니다. Think Along은 여기서부터 맥락을 쌓습니다.</p>

            <label className="mt-7 block">
              <span className="sr-only">첫 Thinking</span>
              <textarea autoFocus value={thought} onChange={(event) => setThought(event.target.value)} maxLength={280} placeholder="예: 여러 AI를 쓰고 싶은데 매번 처음부터 설명하는 게 너무 번거로워요." className="h-36 w-full resize-none rounded-2xl border bg-transparent p-4 text-[16px] font-semibold leading-7 outline-none" style={{ borderColor: thought.trim() ? 'var(--accent-green)' : 'var(--border-primary)', backgroundColor: 'var(--bg-tertiary)', color: 'var(--text-primary)' }} />
              <p className="mt-2 text-right text-[10px] font-semibold" style={{ color: 'var(--text-tertiary)' }}>{thought.length}/280</p>
            </label>

            <div className="mt-4 flex flex-wrap gap-2">
              {examples.map((example) => (
                <button key={example} onClick={() => setThought(example)} className="rounded-full border px-3 py-2 text-left text-[11px] font-bold" style={{ borderColor: 'var(--border-primary)', backgroundColor: 'var(--bg-tertiary)', color: 'var(--text-secondary)' }}>{example}</button>
              ))}
            </div>

            <div className="mt-auto pt-8">
              <button disabled={!thought.trim()} onClick={() => setStep(2)} className="flex h-[52px] w-full items-center justify-center gap-2 rounded-xl text-[15px] font-black text-[#021b12] disabled:opacity-30" style={{ backgroundColor: 'var(--accent-green)' }}>
                이 생각을 이어가기 <ChevronRight size={18} />
              </button>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="flex flex-1 flex-col px-6 pb-7 pt-9">
            <div className="mx-auto grid h-14 w-14 place-items-center rounded-full" style={{ backgroundColor: 'var(--accent-green-soft)', color: 'var(--accent-green)' }}><Check size={28} strokeWidth={3} /></div>
            <p className="mt-5 text-center text-[12px] font-black" style={{ color: 'var(--accent-green)' }}>첫 Thinking 준비 완료</p>
            <h1 className="mt-2 text-center text-[28px] font-black leading-[1.25] tracking-[-0.04em]">다음 AI에게<br />다시 설명하지 마세요.</h1>

            <div className="mt-7 rounded-2xl border p-4" style={{ borderColor: 'var(--border-primary)', backgroundColor: 'var(--bg-tertiary)' }}>
              <p className="text-[10px] font-black uppercase tracking-[0.12em]" style={{ color: 'var(--accent-green)' }}>Your Thinking</p>
              <p className="mt-2 text-[15px] font-extrabold leading-6">{previewTitle}</p>
              <div className="my-4 h-px" style={{ backgroundColor: 'var(--border-primary)' }} />
              <div className="flex items-center gap-3">
                <span className="grid h-10 w-10 place-items-center rounded-xl" style={{ backgroundColor: 'var(--accent-green-soft)', color: 'var(--accent-green)' }}><Brain size={20} /></span>
                <div className="flex-1">
                  <p className="text-[12px] font-black">이 생각의 맥락을 계속 유지</p>
                  <p className="mt-1 text-[10px] font-semibold" style={{ color: 'var(--text-secondary)' }}>GPT → Claude → Gemini로 바꿔도 이어지는 구조</p>
                </div>
              </div>
            </div>

            <div className="mt-5 rounded-xl border p-4" style={{ borderColor: 'color-mix(in srgb, var(--accent-green) 35%, transparent)', backgroundColor: 'var(--accent-green-soft)' }}>
              <p className="text-[12px] font-extrabold">앞으로 Think Along이 기억할 것</p>
              <div className="mt-3 space-y-2 text-[11px] font-semibold" style={{ color: 'var(--text-secondary)' }}>
                {['무엇을 고민 중인지', '어떤 결정을 했는지', '어디까지 생각했는지'].map((item) => <p key={item} className="flex items-center gap-2"><Check size={13} style={{ color: 'var(--accent-green)' }} />{item}</p>)}
              </div>
            </div>

            <div className="mt-auto pt-7">
              <button onClick={() => finishOnboarding(thought)} className="flex h-[52px] w-full items-center justify-center gap-2 rounded-xl text-[15px] font-black text-[#021b12]" style={{ backgroundColor: 'var(--accent-green)' }}>
                Think Along 시작하기 <ArrowRight size={18} />
              </button>
              <p className="mt-3 text-center text-[11px] font-semibold" style={{ color: 'var(--text-tertiary)' }}>첫 생각은 이 브라우저에 보관됩니다. AI 연결은 앱에서 나중에 할 수 있어요.</p>
            </div>
          </div>
        )}
      </section>
    </main>
  );
}
