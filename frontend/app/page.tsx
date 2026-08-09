import React from 'react';
import Link from 'next/link';
import { Cloud, Moon, Zap, Sparkles, Globe } from 'lucide-react';

export default function LandingPage() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-6 relative overflow-hidden bg-void">
      {/* Background Decorative Glows - Enhanced Visual Flare */}
      <div className="absolute top-[-10%] left-[-10%] w-[50%] h-[50%] bg-eepy-lavender/10 blur-[120px] rounded-full animate-pulse" />
      <div className="absolute bottom-[-10%] right-[-10%] w-[50%] h-[50%] bg-eepy-mint/10 blur-[120px] rounded-full" />
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[80%] h-[80%] bg-eepy-peach/5 blur-[150px] rounded-full" />

      {/* Top Navigation */}
      <nav className="absolute top-0 left-0 right-0 p-6 flex justify-end z-20">
        <Link 
          href="/login" 
          className="px-6 py-2 bg-void-surface border border-void-border text-white rounded-full hover:border-eepy-lavender transition-all font-console text-sm backdrop-blur-md"
        >
          Log In
        </Link>
      </nav>

      <main className="z-10 text-center space-y-8 max-w-4xl">
        <div className="flex justify-center mb-6">
          <div className="p-4 bg-void-surface border border-void-border rounded-eepy shadow-[0_0_30px_rgba(195,177,225,0.3)] relative group">
            <Moon size={48} className="text-eepy-lavender animate-pulse" />
            {/* Tiny decorative sparks */}
            <Sparkles size={16} className="absolute -top-2 -right-2 text-eepy-peach animate-bounce" />
            <Sparkles size={16} className="absolute -bottom-2 -left-2 text-eepy-mint animate-pulse" />
          </div>
        </div>

        <div className="space-y-4">
          <h1 className="text-7xl font-bold tracking-tight leading-tight">
            Eepy <span className="text-eepy-lavender italic">Host</span>
          </h1>
          <p className="text-gray-400 text-2xl max-w-2xl mx-auto leading-relaxed font-light">
            The ultimate playground for the <span className="text-eepy-peach font-semibold">Vibe Coder</span>. 
            Host your MCP servers in a space designed for focus and flow.
          </p>
        </div>

        <div className="flex gap-4 justify-center pt-4">
          <Link href="/signup">
            <button className="px-10 py-4 bg-eepy-lavender text-void font-bold rounded-full hover:bg-opacity-90 transition-all transform hover:scale-105 shadow-[0_0_20px_rgba(195,177,225,0.5)] animate-gradient-border font-console">
              Get Started
            </button>
          </Link>
        </div>

        {/* Core Feature Highlight */}
        <div className="mt-16 p-8 bg-void-surface/30 border border-void-border rounded-eepy backdrop-blur-sm max-w-2xl mx-auto space-y-4 relative overflow-hidden group">
          <div className="absolute top-0 left-0 w-1 h-full bg-eepy-lavender" />
          <div className="flex items-center gap-3 mb-2 justify-center">
            <Globe size={20} className="text-eepy-mint" />
            <span className="text-xs font-console uppercase tracking-widest text-gray-500">The Engine</span>
          </div>
          <h2 className="text-xl font-semibold text-white">Connecting Models to the World</h2>
          <p className="text-gray-400 text-sm leading-relaxed">
            Eepy Host is a powerful MCP platform that lets you pick from a curated library of 
            <span className="text-eepy-mint font-medium"> pre-configured servers</span>. 
            Instantly connect your AI models to real-time data, APIs, and local tools.
          </p>
          <div className="pt-4 flex justify-center gap-6 text-xs font-console text-gray-500">
             <span className="flex items-center gap-1"><Zap size={12} /> High Performance</span>
             <span className="flex items-center gap-1"><Moon size={12} /> Zero Friction</span>
          </div>
        </div>

        {/* Self-Hosted Pairing Note */}
        <p className="text-gray-500 text-sm font-console italic">
          ✨ Best paired with self-hosted LLM interfaces like <span className="text-eepy-peach">Open WebUI</span> for the ultimate private stack.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-20">
          {[
            { icon: <Zap size={24} />, title: "Fast", desc: "Streamable HTTP endpoints." },
            { icon: <Cloud size={24} />, title: "Flexible", desc: "Your tokens, your config." },
            { icon: <Moon size={24} />, title: "Cozy", desc: "A UI that doesn't scream at you." },
          ].map((feature, i) => (
            <div key={i} className="p-6 bg-void-surface/50 border border-void-border rounded-eepy backdrop-blur-sm hover:border-eepy-lavender/50 transition-colors group">
              <div className="text-eepy-lavender mb-3 group-hover:scale-110 transition-transform">{feature.icon}</div>
              <h3 className="font-semibold text-lg mb-2">{feature.title}</h3>
              <p className="text-gray-500 text-sm">{feature.desc}</p>
            </div>
          ))}
        </div>
      </main>

      <footer className="absolute bottom-8 text-gray-600 text-sm font-console">
        &copy; 2026 Eepy Host &bull; Stay cozy.
      </footer>
    </div>
  );
}
