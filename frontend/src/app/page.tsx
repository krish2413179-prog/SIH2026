import Link from 'next/link';
import AeroShards from '@/components/ReactBits/AeroShards';
import { ArrowRight, Shield, Activity, Search } from 'lucide-react';

export default function LandingPage() {
  return (
    <div className="relative min-h-screen bg-black text-gray-100 overflow-hidden flex flex-col">
      {/* Fallback Animated Gradient Layer */}
      <div className="absolute inset-0 z-0 bg-gradient-to-br from-gray-950 via-black to-gray-900 animate-pulse-slow"></div>

      {/* WebGPU Animation Layer */}
      <div className="absolute inset-0 z-0">
        <AeroShards
          backgroundColor="#000000"
          shardColor="#3B82F6"
          accentColor="#60A5FA"
          placement="full"
          flow="stream"
          material="pearl"
          detail="balanced"
          effect="none"
          scale={1}
          spread={1}
          depth={1}
          speed={0.3}
          spin={1}
          interaction="repel"
          density={1.5}
          shardSize={1.1}
          stretch={1}
          turbulence={1}
          glow={1}
          edgeSoftness={2}
          bloom={0.5}
          grain={0.02}
          chromaticAberration={0.005}
          transitionDuration={1}
          interactionRadius={1.5}
          interactionStrength={0.5}
          rippleIntensity={1}
          holdToGather={true}
        />
      </div>

      {/* Foreground Content */}
      <div className="relative z-10 flex flex-col min-h-screen">
        <header className="px-8 py-6 flex items-center justify-between border-b border-white/10 bg-black/40 backdrop-blur-md">
          <div className="flex items-center gap-3">
            <div className="bg-blue-600 p-2 rounded-lg text-white">
              <Shield className="h-6 w-6" />
            </div>
            <span className="font-bold text-xl tracking-tight text-white">VASP Engine</span>
          </div>
          <nav className="flex items-center gap-6">
            <Link href="/auth/login" className="text-sm font-medium text-gray-400 hover:text-white transition-colors">
              Sign In
            </Link>
            <Link href="/dashboard" className="text-sm font-medium bg-blue-600 text-white px-5 py-2.5 rounded-full hover:bg-blue-700 shadow-sm hover:shadow-md transition-all hover:-translate-y-0.5">
              Go to Dashboard
            </Link>
          </nav>
        </header>

        <main className="flex-1 flex flex-col items-center justify-center px-4 sm:px-6 lg:px-8 text-center max-w-5xl mx-auto w-full">
          <div className="space-y-8 animate-fade-in-up">
            <div className="inline-flex items-center rounded-full px-4 py-1.5 text-sm font-semibold text-blue-300 bg-blue-500/10 backdrop-blur-sm border border-blue-500/30 shadow-sm">
              <span className="flex h-2 w-2 rounded-full bg-blue-400 mr-2 animate-pulse"></span>
              Next-Gen Blockchain Intelligence
            </div>
            
            <h1 className="text-5xl sm:text-6xl md:text-7xl font-extrabold tracking-tight text-white drop-shadow-sm">
              <span className="block">Attribution Engine for</span>
              <span className="block text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-indigo-400 pb-2">LEA Investigations</span>
            </h1>
            
            <p className="mt-6 text-xl text-gray-400 max-w-2xl mx-auto leading-relaxed font-medium">
              Real-time trace visualization, dynamic risk scoring, and intelligent entity resolution, wrapped in a blazing fast, intuitive interface.
            </p>
            
            <div className="mt-10 flex flex-col sm:flex-row gap-4 justify-center items-center">
              <Link href="/dashboard" className="inline-flex items-center justify-center px-8 py-4 text-base font-semibold text-white bg-blue-600 border border-transparent rounded-full hover:bg-blue-700 shadow-lg hover:shadow-blue-500/30 transition-all hover:-translate-y-1 w-full sm:w-auto">
                Start Investigating
                <ArrowRight className="ml-2 h-5 w-5" />
              </Link>
              <Link href="/cases" className="inline-flex items-center justify-center px-8 py-4 text-base font-semibold text-gray-300 bg-white/10 backdrop-blur-md border border-white/20 rounded-full hover:bg-white/20 shadow-sm hover:shadow-md transition-all hover:-translate-y-1 w-full sm:w-auto">
                Browse Cases
              </Link>
            </div>
          </div>
          
          <div className="mt-24 grid grid-cols-1 sm:grid-cols-3 gap-6 w-full max-w-4xl mx-auto pb-12">
            {[
              { title: 'Real-time Tracing', icon: Activity, desc: 'Live monitoring of on-chain asset flow and VASP interaction.' },
              { title: 'Smart Search', icon: Search, desc: 'Advanced heuristic-driven wallet and transaction search.' },
              { title: 'Threat Intel', icon: Shield, desc: 'Continuous cross-referencing with known threat databases.' }
            ].map((feature, i) => (
              <div key={i} className="bg-white/5 backdrop-blur-xl border border-white/10 p-6 rounded-2xl shadow-sm hover:shadow-blue-900/20 hover:shadow-lg transition-all hover:-translate-y-1 text-left">
                <div className="bg-blue-500/10 w-12 h-12 rounded-xl flex items-center justify-center mb-4 border border-blue-500/20">
                  <feature.icon className="h-6 w-6 text-blue-400" />
                </div>
                <h3 className="text-lg font-bold text-white mb-2">{feature.title}</h3>
                <p className="text-gray-400 text-sm leading-relaxed">{feature.desc}</p>
              </div>
            ))}
          </div>
        </main>
      </div>
    </div>
  );
}
