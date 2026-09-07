'use client';

import dynamic from 'next/dynamic';
import Link from 'next/link';
import DepthText from '@/components/depth-text';

// Globe uses WebGL canvas — load client-side only to avoid SSR issues
const Globe = dynamic(() => import('@/components/globe'), { ssr: false });

export default function LandingPage() {
  return (
    <main className="relative flex min-h-screen w-full flex-col md:flex-row items-center justify-between overflow-x-hidden bg-black py-10 md:py-0">

      {/* ── subtle radial glow behind the text ── */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            'radial-gradient(ellipse 60% 80% at 20% 50%, rgba(99,102,241,0.18) 0%, transparent 70%)',
        }}
      />

      {/* ── LEFT: branding + CTA ── */}
      <section className="relative z-10 flex flex-1 flex-col items-start justify-center px-6 sm:px-12 md:px-16 lg:px-24 py-8 md:py-12 gap-6 md:gap-8 max-w-2xl">

        {/* eyebrow */}
        <span className="text-xs font-semibold tracking-[0.28em] uppercase text-indigo-400/80">
          Blockchain Intelligence &amp; VASP Attribution Engine
        </span>

        {/* 3-D extruded headline in CamelCase */}
        <div className="flex flex-col gap-1 select-none">
          <DepthText
            text="Crypto"
            layers={32}
            depth={2.2}
            faceColor="#ffffff"
            depthColor="#4f46e5"
            tilt={8}
            pointerTracking
            smoothing={0.12}
            perspective={900}
            autoOrbit
            orbitSpeed={0.28}
            fontSize="clamp(3.5rem, 8vw, 7.5rem)"
            fontWeight={900}
            shadow
          />

          <DepthText
            text="Traverse"
            layers={32}
            depth={2.2}
            faceColor="#ffffff"
            depthColor="#7c3aed"
            tilt={8}
            pointerTracking
            smoothing={0.12}
            perspective={900}
            autoOrbit
            orbitSpeed={0.28}
            fontSize="clamp(3.5rem, 8vw, 7.5rem)"
            fontWeight={900}
            shadow
          />
        </div>

        {/* tagline */}
        <p className="max-w-md text-sm sm:text-base leading-relaxed text-neutral-400">
          Automated transaction tracing, VASP attribution, and risk-scoring
          for Law Enforcement Agencies — powered by multi-chain graph
          intelligence.
        </p>

        {/* CTA */}
        <Link
          href="/dashboard"
          className="mt-2 inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-6 py-3.5 text-sm font-semibold text-white shadow-lg shadow-indigo-900/50 transition-all hover:bg-indigo-500 hover:shadow-indigo-700/60 active:scale-95"
        >
          Enter Dashboard
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="size-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
            aria-hidden="true"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </Link>
      </section>

      {/* ── RIGHT: Interactive Globe (Enlarged & Responsive) ── */}
      <section
        aria-label="Interactive globe showing global crypto flows"
        className="relative z-10 flex flex-1 items-center justify-center w-full min-h-[420px] sm:min-h-[520px] md:min-h-[640px] lg:min-h-[750px] xl:min-h-[850px] px-2 sm:px-6"
      >
        {/* atmospheric ambient glow behind the globe */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 flex items-center justify-center"
        >
          <div className="w-[85%] h-[85%] rounded-full bg-gradient-to-tr from-indigo-600/20 via-purple-600/15 to-cyan-500/20 blur-3xl" />
        </div>

        <div className="relative w-full max-w-[480px] sm:max-w-[600px] md:max-w-[700px] lg:max-w-[840px] xl:max-w-[960px] aspect-square flex items-center justify-center">
          <Globe />
        </div>
      </section>
    </main>
  );
}
