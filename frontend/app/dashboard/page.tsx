"use client";

import React from 'react';
import { useAuth } from '@/context/AuthContext';
import { Moon } from 'lucide-react';

export default function OverviewPage() {
  const { user } = useAuth();

  return (
    <div className="space-y-12">
      <header className="flex justify-between items-center mb-8">
        <div>
          <h2 className="text-3xl font-bold font-console">Welcome back, <span className="text-eepy-lavender">{user?.username}</span></h2>
          <p className="text-gray-500 font-console text-sm mt-1 italic">Current Role: {user?.role.toUpperCase()}</p>
        </div>
        
        <div className="flex items-center gap-4">
           <div className="px-3 py-1 bg-void-surface border border-void-border rounded-full text-xs font-console text-eepy-mint animate-pulse">
             System Status: Cozy
           </div>
        </div>
      </header>

      {/* Dashboard Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Main Stat Card */}
        <div className="md:col-span-2 p-8 bg-void-surface border-4 border-void-border rounded-eepy relative overflow-hidden group hover:border-eepy-lavender/50 transition-colors shadow-xl">
          <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
            <Moon size={80} />
          </div>
          <h3 className="text-xl font-bold font-console mb-4 text-eepy-lavender">Host Status</h3>
          <p className="text-gray-400 font-console text-sm leading-relaxed max-w-md">
            Your MCP infrastructure is currently in <span className="text-white underline decoration-eepy-mint">Deep Sleep</span>. 
            All streamable endpoints are idling and waiting for your API tokens to be linked.
          </p>
          <button className="mt-6 px-6 py-2 bg-void border border-void-border rounded-lg font-console text-xs hover:bg-void-border transition-colors">
            View System Logs
          </button>
        </div>

        {/* Quick Actions Card */}
        <div className="p-8 bg-void-surface border-4 border-void-border rounded-eepy space-y-6 group hover:border-eepy-peach/50 transition-colors shadow-xl">
          <h3 className="text-xl font-bold font-console text-eepy-peach">Quick Actions</h3>
          <div className="space-y-3">
            {[
              { label: 'Add New Server', color: 'bg-eepy-lavender' },
              { label: 'Rotate API Keys', color: 'bg-eepy-mint' },
              { label: 'Clear Cache', color: 'bg-eepy-peach' },
            ].map((action) => (
              <button key={action.label} className="w-full py-3 px-4 bg-void border border-void-border rounded-xl text-left font-console text-xs hover:border-white transition-all flex justify-between items-center group">
                {action.label} <div className={`w-2 h-2 rounded-full ${action.color}`} />
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
