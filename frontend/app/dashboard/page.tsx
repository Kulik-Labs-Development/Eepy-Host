"use client";

import React from 'react';
import { useAuth } from '@/context/AuthContext';
import { useRouter } from 'next/navigation';
import { LogOut, LayoutDashboard, Server, UserCircle, Settings, Moon } from 'lucide-react';

export default function Dashboard() {
  const { user, logout } = useAuth();
  const router = useRouter();

  // In a real app, we'd check if user exists and redirect to login. 
  // I'll implement a proper Route Guard in the layout soon.
  if (!user) return <div className="min-h-screen bg-void flex items-center justify-center font-console text-gray-500">Loading cozy space...</div>;

  return (
    <div className="min-h-screen bg-void text-white flex overflow-hidden">
      {/* Sidebar */}
      <aside className="w-64 bg-void-surface border-r border-void-border flex flex-col p-4 space-y-8">
        <div className="flex items-center gap-3 px-2 mb-4">
          <div className="p-2 bg-eepy-lavender rounded-lg text-void">
            <Moon size={20} />
          </div>
          <span className="font-bold text-xl tracking-tight font-console">Eepy Host</span>
        </div>

        <nav className="flex-1 space-y-2">
          {[
            { icon: <LayoutDashboard size={20}/>, label: 'Overview', active: true },
            { icon: <Server size={20}/>, label: 'MCP Servers', active: false },
            { icon: <UserCircle size={20}/>, label: 'Account', active: false },
            { icon: <Settings size={20}/>, label: 'System Settings', active: false },
          ].map((item) => (
            <button 
              key={item.label}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-all font-console text-sm ${
                item.active ? 'bg-eepy-lavender text-void font-bold shadow-[0_0_15px_rgba(195,177,225,0.3)]' : 'text-gray-400 hover:bg-void-border hover:text-white'
              }`}
            >
              {item.icon} {item.label}
            </button>
          ))}
        </nav>

        <div className="pt-8 border-t border-void-border">
          <button 
            onClick={logout}
            className="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-gray-400 hover:bg-red-500/10 hover:text-red-400 transition-all font-console text-sm"
          >
            <LogOut size={20} /> Logout
          </button>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 overflow-y-auto relative p-8 bg-gradient-to-br from-void via-void to-void-surface">
        {/* Background Glow for "Cyber Cozy" effect */}
        <div className="absolute top-0 right-0 w-[50%] h-[50%] bg-eepy-lavender/5 blur-[120px] rounded-full -z-10" />
        
        <header className="flex justify-between items-center mb-12">
          <div>
            <h2 className="text-3xl font-bold font-console">Welcome back, <span className="text-eepy-lavender">{user.username}</span></h2>
            <p className="text-gray-500 font-console text-sm mt-1 italic">Current Role: {user.role.toUpperCase()}</p>
          </div>
          
          <div className="flex items-center gap-4">
             <div className="px-3 py-1 bg-void-surface border border-void-border rounded-full text-xs font-console text-eepy-mint animate-pulse">
               System Status: Cozy
             </div>
          </div>
        </header>

        {/* Dashboard Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Main Stat Card - The "Bedroom" feeling card */}
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
      </main>
    </div>
  );
}
