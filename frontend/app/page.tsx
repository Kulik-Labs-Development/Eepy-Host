import React from 'react';
import Link from 'next/link';
import { Zap, Sparkles, Globe, ShieldCheck } from 'lucide-react';
import PixelMoon from '../src/components/PixelMoon';

export default function LandingPage() {
  return (
    <div className="min-h-screen flex flex-col items-center p-6 relative overflow-hidden">
      {/* Top Navigation */}
      <nav className="w-full max-w-6xl flex items-center justify-between p-4 z-20">
        <div className="flex items-center gap-3">
          <PixelMoon size={40} />
          <span className="font-pixel font-bold text-xl tracking-tight text-ink text-px-sm">
            Eepy <span className="text-eepy-blush">Host</span>
          </span>
        </div>
        <Link href="/auth">
          <button className="btn btn-ghost px-5 py-2 text-sm">Log In</button>
        </Link>
      </nav>

      <main className="z-10 text-center space-y-12 max-w-4xl flex-grow flex flex-col justify-center py-12 w-full">
        {/* Hero mascot */}
        <div className="flex justify-center mb-2">
          <div className="relative panel pixel-caps p-8 sm:p-10 [--cap:theme('colors.eepy.pink')]">
            <div className="relative inline-block">
              <PixelMoon size={128} />
              <span className="absolute -right-7 top-4 font-pixel font-bold text-eepy-lilac text-lg animate-float-z">z</span>
              <span className="absolute -right-12 top-0 font-pixel font-bold text-eepy-lilac/80 text-xl animate-float-z" style={{ animationDelay: '0.9s' }}>z</span>
              <span className="absolute -right-16 top-[-14px] font-pixel font-bold text-eepy-lilac/60 text-2xl animate-float-z" style={{ animationDelay: '1.8s' }}>z</span>
            </div>
          </div>
        </div>

        <div className="space-y-5 sm:space-y-6">
          <h1 className="font-pixel font-bold text-5xl sm:text-6xl md:text-7xl tracking-tight leading-tight text-px">
            Eepy <span className="text-eepy-blush">Host</span>
          </h1>
          <p className="text-ink-soft text-lg sm:text-2xl max-w-2xl mx-auto leading-relaxed font-medium">
            The cozy corner of the internet for the{' '}
            <span className="text-eepy-pink font-bold">Vibe Coder</span>. Host your MCP
            servers in a space built for focus, flow, and a good long nap.
          </p>
        </div>

        <div className="flex gap-4 justify-center pt-2 flex-wrap">
          <Link href="/auth">
            <button className="btn btn-blush px-10 py-3.5 text-base shadow-glow-blush">Get Started</button>
          </Link>
          <Link href="/auth">
            <button className="btn btn-ghost px-8 py-3.5 text-base">Log In</button>
          </Link>
        </div>

        {/* Core Feature Highlight — a game dialog box */}
        <div className="mt-8 sm:mt-12 panel pixel-caps p-6 sm:p-8 max-w-2xl mx-auto text-left space-y-4 [--cap:theme('colors.eepy.lilac')]">
          <div className="flex items-center gap-3">
            <span className="chip chip-lilac">The Engine</span>
            <Globe size={16} className="text-eepy-sage" />
          </div>
          <h2 className="font-pixel font-bold text-xl sm:text-2xl text-ink">
            Connecting Models to the World
          </h2>
          <p className="text-ink-faint text-sm sm:text-base leading-relaxed">
            Eepy Host is a cozy MCP platform that lets you pick from a curated
            library of <span className="text-eepy-sage font-semibold">pre-configured servers</span>.
            Instantly connect your AI models to real-time data, APIs, and local tools —
            while you rest easy.
          </p>
          <div className="pt-2 flex flex-wrap gap-x-5 gap-y-2">
            <span className="chip"><Zap size={13} className="text-eepy-amber" /> High Performance</span>
            <span className="chip"><Sparkles size={13} className="text-eepy-blush" /> Zero Friction</span>
          </div>
        </div>

        {/* Self-Hosted Pairing Note */}
        <p className="text-ink-dim text-sm font-console text-[15px] max-w-lg mx-auto leading-relaxed">
          Best paired with self-hosted LLM interfaces like{' '}
          <span className="text-eepy-amber">Open WebUI</span> for a{' '}
          <span className="text-ink-soft underline decoration-eepy-sage decoration-2 underline-offset-4">fully private stack</span>.
          Your data, your vibes, zero leaks.
        </p>

        {/* Feature cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 sm:gap-6 mt-8 sm:mt-12 pb-8 w-full max-w-4xl mx-auto">
          {[
            { icon: <Zap size={22} />, tint: 'text-eepy-amber', cap: "[--cap:theme('colors.eepy.amber')]", title: 'Fast', desc: 'Streamable HTTP endpoints that keep up with your imagination.' },
            { icon: <ShieldCheck size={22} />, tint: 'text-eepy-sage', cap: "[--cap:theme('colors.eepy.sage')]", title: 'Private', desc: 'Fully self-hosted. Total data sovereignty, encrypted at rest.' },
            { icon: <Sparkles size={22} />, tint: 'text-eepy-blush', cap: "[--cap:theme('colors.eepy.pink')]", title: 'Cozy', desc: 'A warm little UI that never screams at you. Just soft beeps.' },
          ].map((feature) => (
            <div key={feature.title} className={`panel pixel-caps lift p-6 text-left ${feature.cap}`}>
              <div className={`well inline-flex p-3 mb-4 ${feature.tint}`}>{feature.icon}</div>
              <h3 className="font-pixel font-bold text-lg mb-2 text-ink">{feature.title}</h3>
              <p className="text-ink-faint text-sm leading-relaxed">{feature.desc}</p>
            </div>
          ))}
        </div>
      </main>

      <footer className="w-full py-8 text-center text-ink-dim font-console text-[15px]">
        &copy; 2026 Eepy Host &bull; Stay cozy.
      </footer>
    </div>
  );
}
