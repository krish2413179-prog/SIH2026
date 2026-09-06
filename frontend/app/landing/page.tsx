'use client';

import dynamic from 'next/dynamic';
import Link from 'next/link';
import DepthText from '@/components/depth-text';

// Globe uses WebGL canvas — load client-side only to avoid SSR issues
const Globe = dynamic(() => import('@/components/ui/globe-tw'), { ssr: false });

export default function LandingPage() {
  return (
    <main className="relative flex min-h-screen w-full overflow-hidden bg-black">

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
      <section className="relative z-10 flex flex-1 flex-col items-start justify-center px-12 md:px-20 lg:px-28 gap-8">

        {/* eyebrow */}
        <span className="text-xs font-semibold tracking-[0.28em] uppercase text-white">
          Blockchain Intelligence &amp; VASP Attribution Engine
        </span>

        {/* 3-D extruded headline */}
        <DepthText
          text="CRYPTO"
          layers={32}
          depth={2.2}
          faceColor="#ffffff"
          depthColor="#ffffff"
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
          text="TRAVERSE"
          layers={32}
          depth={2.2}
          faceColor="#ffffff"
          depthColor="#ffffff"
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

        {/* tagline */}
        <p className="max-w-md text-sm leading-relaxed text-white">
          Automated transaction tracing, VASP attribution, and risk-scoring
          for Law Enforcement Agencies — powered by multi-chain graph
          intelligence.
        </p>

        {/* CTA */}
        <Link
          href="/dashboard"
          className="mt-2 inline-flex items-center gap-2 rounded-lg bg-black px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-gray-900/50 transition-all hover:bg-gray-800 hover:shadow-gray-700/60 active:scale-95"
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

      {/* ── RIGHT: Globe ── */}
      <section
        aria-label="Interactive globe showing global crypto flows"
        className="relative z-10 hidden md:flex flex-1 items-center justify-center"
      >
        {/* subtle vignette / glow behind the globe */}
        <div
          aria-hidden="true"
          className="absolute inset-0 pointer-events-none"
          style={{
            background:
              'radial-gradient(ellipse 70% 70% at 60% 50%, rgba(99,102,241,0.12) 0%, transparent 70%)',
          }}
        />

        <div className="w-[min(90%,600px)] aspect-square">
          <Globe />
        </div>
      </section>
    </main>
  );
}
