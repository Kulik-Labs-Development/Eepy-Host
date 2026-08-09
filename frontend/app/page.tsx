import React from 'react';
import { Cloud, Moon, Zap } from 'lucide-react';

export default function LandingPage() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-6 relative overflow-hidden">
      {/* Background Decorative Glows */}
      <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-eepy-lavender/10 blur-[120px] rounded-full" />
      <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-eepy-mint/10 blur-[120px] rounded-full" />

      <main className="z-10 text-center space-y-8 max-w-3xl">
        <div className="flex justify-center mb-6">
          <div className="p-4 bg-void-surface border border-void-border rounded-eepy shadow-[0_0_20px_rgba(195,177,225,0.2)]">
            <Moon size={48} className="text-eepy-lavender animate-pulse" />
          </div>
        </div>

        <h1 className="text-6xl font-bold tracking-tight">
          Eepy <span className="text-eepy-lavender italic">Host</span>
        </h1>
        
        <p className="text-gray-400 text-xl max-w-lg mx-auto leading-relaxed">
          The coziest place to host your MCP servers. 
          Powerful infrastructure, wrapped in a soft blanket of simplicity.
        </p>

        <div className="flex gap-4 justify-center pt-4">
          <button className="px-8 py-3 bg-eepy-lavender text-void font-bold rounded-full hover:bg-opacity-90 transition-all transform hover:scale-105 shadow-[0_0_15px_rgba(195,177,225,0.4)]">
            Get Started
          </button>
          <button className="px-8 py-3 bg-void-surface border border-void-border text-white rounded-full hover:bg-void-border transition-all transform hover:scale-105">
            View Docs
          </button>
        </div>

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

      <footer className="absolute bottom-8 text-gray-600 text-sm">
        &copy; 2026 Eepy Host &bull; Stay cozy.
      </footer>
    </div>
  );
}
