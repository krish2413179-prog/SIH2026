'use client';

import Link from 'next/link';
import dynamic from 'next/dynamic';
import { ArrowRight, Shield, Activity, Search, Lock, Zap, Globe } from 'lucide-react';

const AeroShards = dynamic(() => import('@/components/ReactBits/AeroShards'), { ssr: false });
const DepthText  = dynamic(() => import('@/components/ReactBits/DepthText'),  { ssr: false });
const CardSwap   = dynamic(() => import('@/components/ReactBits/CardSwap').then(m => m.default), { ssr: false });
const Card       = dynamic(() => import('@/components/ReactBits/CardSwap').then(m => m.Card),    { ssr: false });

const CARDS = [
  {
    icon:   Activity,
    label:  'Real-time Tracing',
    accent: '#3B82F6',
    blob:   'radial-gradient(ellipse at 25% 75%, #1d4ed8 0%, #0ea5e9 45%, #06b6d4 75%, transparent 100%)',
    stat:   '6',
    body:   'Live BFS across ETH, BSC, MATIC, TRX, SOL, BTC — native + ERC-20',
  },
  {
    icon:   Search,
    label:  'Smart Attribution',
    accent: '#8B5CF6',
    blob:   'radial-gradient(ellipse at 65% 60%, #5b21b6 0%, #8b5cf6 50%, #a78bfa 75%, transparent 100%)',
    stat:   '∞',
    body:   'VASP tagging, mixer detection, peel-chain identification',
  },
  {
    icon:   Shield,
    label:  'AI Risk Scoring',
    accent: '#EF4444',
    blob:   'radial-gradient(ellipse at 40% 65%, #991b1b 0%, #ef4444 50%, #f87171 75%, transparent 100%)',
    stat:   'AI',
    body:   'LLM suspicion score 0-100 with per-wallet reasoning',
  },
  {
    icon:   Zap,
    label:  'Async Workers',
    accent: '#F59E0B',
    blob:   'radial-gradient(ellipse at 50% 60%, #78350f 0%, #f59e0b 50%, #fcd34d 78%, transparent 100%)',
    stat:   '4',
    body:   'Celery queue — 5-min deadline, 20-node minimum guarantee',
  },
  {
    icon:   Lock,
    label:  'SAHYOG Integration',
    accent: '#10B981',
    blob:   'radial-gradient(ellipse at 35% 65%, #064e3b 0%, #10b981 50%, #34d399 75%, transparent 100%)',
    stat:   'LEA',
    body:   'Supervisor sign-off + court-ready PDF reports',
  },
  {
    icon:   Globe,
    label:  'Multi-chain Graph',
    accent: '#06B6D4',
    blob:   'radial-gradient(ellipse at 55% 60%, #164e63 0%, #06b6d4 50%, #67e8f9 75%, transparent 100%)',
    stat:   '6',
    body:   'Unified hierarchical Dagre graph across all chains',
  },
];

const CARD_W = 440;
const CARD_H = 300;

export default function LandingPage() {
  return (
    /* overflow-x:hidden on outermost only — inner elements need overflow:visible for the card stack */
    <div className="relative min-h-screen bg-[#09090f] text-gray-100 flex flex-col" style={{ overflowX: 'hidden' }}>

      {/* ── Background ── */}
      <div className="absolute inset-0 z-0 opacity-45 pointer-events-none">
        <AeroShards
          backgroundColor="#09090f" shardColor="#3B82F6" accentColor="#818CF8"
          placement="full" flow="stream" material="chrome" detail="fine" effect="none"
          scale={0.7} spread={1.2} depth={1} speed={0.16} spin={0.7}
          interaction="repel" density={0.85} shardSize={0.8} stretch={1}
          turbulence={0.65} glow={0.45} edgeSoftness={2} bloom={0.2}
          grain={0.01} chromaticAberration={0.002} transitionDuration={1}
          interactionRadius={1.2} interactionStrength={0.3} rippleIntensity={0.6}
          holdToGather={false} onError={() => {}}
        />
      </div>
      <div className="absolute inset-0 z-0 pointer-events-none"
        style={{ background: 'radial-gradient(ellipse 90% 55% at 50% 110%, #09090f 55%, transparent 100%)' }} />

      {/* ── Content ── */}
      <div className="relative z-10 flex flex-col min-h-screen">

        {/* Hero — two-column layout */}
        <section
          className="flex flex-col lg:flex-row items-center min-h-screen px-8 sm:px-14 lg:px-20 py-16 gap-0"
          style={{ overflow: 'visible' }}
        >

          {/* Left column */}
          <div className="flex flex-col items-start justify-center flex-1 z-10 pr-0 lg:pr-10 max-w-xl">

            <div className="inline-flex items-center gap-2 rounded-full px-3.5 py-1.5 text-xs font-semibold text-blue-300 bg-blue-500/10 border border-blue-500/25 mb-7">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
              Next-Gen Blockchain Intelligence · LEA Platform
            </div>

            {/* Big DepthText — no fontFamily override */}
            <div className="mb-1">
              <DepthText
                text="Crypto" layers={36} depth={3}
                faceColor="#f8fafc" depthColor="#1d4ed8"
                tilt={9} pointerTracking smoothing={0.1} perspective={1000}
                autoOrbit orbitSpeed={0.22}
                fontSize="clamp(4.5rem, 12vw, 9.5rem)" fontWeight={900} shadow
              />
            </div>
            <div className="mb-7">
              <DepthText
                text="Traverse" layers={36} depth={3}
                faceColor="#93c5fd" depthColor="#1e3a8a"
                tilt={9} pointerTracking smoothing={0.1} perspective={1000}
                autoOrbit orbitSpeed={0.19}
                fontSize="clamp(4.5rem, 12vw, 9.5rem)" fontWeight={900} shadow
              />
            </div>

            <p className="text-base sm:text-lg text-gray-400 max-w-md leading-relaxed font-cantata mb-8">
              Trace funds across six blockchains, score wallets with AI, and generate court-ready reports — all in one platform.
            </p>

            <div className="flex flex-col sm:flex-row gap-3 mb-10">
              <Link href="/dashboard"
                className="inline-flex items-center justify-center gap-2 px-7 py-3.5 text-sm font-semibold text-white bg-blue-600 rounded-full hover:bg-blue-700 shadow-lg shadow-blue-900/40 transition-all hover:-translate-y-0.5">
                Start Investigating <ArrowRight className="h-4 w-4" />
              </Link>
              <Link href="/auth/login"
                className="inline-flex items-center justify-center px-7 py-3.5 text-sm font-semibold text-gray-300 bg-white/5 border border-white/10 rounded-full hover:bg-white/10 transition-all hover:-translate-y-0.5">
                Sign In
              </Link>
            </div>

            <div className="flex gap-8">
              {[
                { value: '6',   label: 'Chains' },
                { value: '20+', label: 'Wallets / trace' },
                { value: 'AI',  label: 'Risk scoring' },
              ].map(s => (
                <div key={s.label} className="flex flex-col">
                  <span className="text-xl font-bold text-white">{s.value}</span>
                  <span className="text-[10px] text-gray-600 uppercase tracking-widest">{s.label}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Right column — position:relative so the absolute CardSwap container anchors here */}
          <div
            className="relative flex-shrink-0 hidden lg:block"
            style={{
              width:    CARD_W + 60 * (CARDS.length - 1) + 80,  // card width + stack offset + breathing room
              height:   '100vh',
              overflow: 'visible',
            }}
          >
            <CardSwap
              width={CARD_W}
              height={CARD_H}
              cardDistance={60}
              verticalDistance={70}
              delay={2600}
              pauseOnHover
              skewAmount={6}
              easing="elastic"
            >
              {CARDS.map((c) => (
                <Card key={c.label} style={{ display: 'flex', flexDirection: 'column' }}>
                  {/* Title bar */}
                  <div className="card-title-bar">
                    <c.icon style={{ color: c.accent, width: 14, height: 14, flexShrink: 0 }} />
                    <span>{c.label}</span>
                  </div>
                  {/* Body */}
                  <div className="card-body" style={{ height: CARD_H - 41 }}>
                    <div className="card-blob" style={{ background: c.blob }} />
                    <div className="card-stat" style={{ color: c.accent }}>{c.stat}</div>
                    <div className="card-body-content">
                      <p className="text-sm text-white/80 leading-relaxed">{c.body}</p>
                    </div>
                  </div>
                </Card>
              ))}
            </CardSwap>
          </div>

        </section>

        {/* Mobile grid */}
        <section className="lg:hidden px-6 pb-12 grid grid-cols-1 sm:grid-cols-2 gap-4">
          {CARDS.map((f) => (
            <div key={f.label} className="bg-white/[0.03] border border-white/8 rounded-2xl p-5 flex flex-col gap-2">
              <div className="w-9 h-9 rounded-xl flex items-center justify-center border border-white/8"
                style={{ backgroundColor: `${f.accent}1a` }}>
                <f.icon className="h-4 w-4" style={{ color: f.accent }} />
              </div>
              <h3 className="text-sm font-bold text-white font-cantata">{f.label}</h3>
              <p className="text-xs text-gray-500 leading-relaxed">{f.body}</p>
            </div>
          ))}
        </section>

        <footer className="border-t border-white/5 bg-black/30 px-6 py-6 text-center">
          <p className="text-xs text-gray-600 font-cantata">
            Crypto Traverse · Built for law enforcement · Designed for speed
          </p>
        </footer>

      </div>
    </div>
  );
}
