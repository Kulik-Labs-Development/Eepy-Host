"use client";

import React from 'react';
import { Server, Plus, Globe, Database, Lock } from 'lucide-react';

export default function ServersPage() {
  return (
    <div className="space-y-8">
      <header className="flex justify-between items-center mb-8">
        <div>
          <h2 className="text-3xl font-bold font-console text-white">MCP Server Engine</h2>
          <p className="text-gray-500 font-console text-sm mt-1 italic">Configure your models' access to the world.</p>
        </div>
        <button className="px-4 py-2 bg-eepy-lavender text-void font-bold rounded-xl hover:bg-opacity-90 transition-all flex items-center gap-2 font-console text-sm shadow-[0_0_15px_rgba(195,177,225,0.3)]">
          <Plus size={18} /> Deploy New Server
        </button>
      </header>

      {/* Library of Pre-configured Servers */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {[
          { id: 'github', name: 'GitHub Explorer', icon: <Globe size={24} />, desc: 'Access repositories, issues, and PRs.', tags: ['API', 'Git'], color: 'border-eepy-lavender' },
          { id: 'postgres', name: 'DB Query Engine', icon: <Database size={24} />, desc: 'Direct SQL access to your local databases.', tags: ['SQL', 'Local'], color: 'border-eepy-mint' },
          { id: 'secure-vault', name: 'Secure Secret Vault', icon: <Lock size={24} />, desc: 'Manage encrypted environment variables.', tags: ['Security', 'Vault'], color: 'border-eepy-peach' },
        ].map((server) => (
          <div key={server.id} className={`p-6 bg-void-surface border-t-4 ${server.color} border-x border-b border-void-border rounded-eepy group hover:scale-[1.02] transition-all shadow-xl`}>
            <div className="flex justify-between items-start mb-4">
              <div className="p-3 bg-void rounded-lg text-gray-400 group-hover:text-white transition-colors">
                {server.icon}
              </div>
              <span className="px-2 py-1 bg-void border border-void-border text-[10px] font-console text-gray-500 rounded uppercase tracking-tighter">Available</span>
            </div>
            <h3 className="text-lg font-bold font-console mb-2">{server.name}</h3>
            <p className="text-gray-500 text-sm mb-4 leading-relaxed">{server.desc}</p>
            <div className="flex gap-2 mb-6">
              {server.tags.map(tag => (
                <span key={tag} className="text-[10px] font-console px-2 py-0.5 bg-void border border-void-border text-gray-600 rounded">{tag}</span>
              ))}
            </div>
            <button className="w-full py-2 bg-void border border-void-border rounded-lg text-xs font-console hover:bg-void-border transition-colors">
              Configure Server
            </button>
          </div>
        ))}
      </div>

      {/* Active Servers Section */}
      <div className="mt-12 p-8 bg-void-surface/30 border border-void-border rounded-eepy backdrop-blur-sm">
        <h3 className="text-xl font-bold font-console mb-6 flex items-center gap-2">
          <Server size={20} className="text-eepy-mint" /> Your Active Servers
        </h3>
        <div className="flex flex-col items-center justify-center py-12 text-center space-y-4 border-2 border-dashed border-void-border rounded-xl">
          <p className="text-gray-600 font-console text-sm italic">No servers deployed yet. Pick one from the library above to begin.</p>
        </div>
      </div>
    </div>
  );
}
