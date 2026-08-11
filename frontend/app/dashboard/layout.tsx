"use client";

import React from 'react';
import { useAuth } from '@/context/AuthContext';
import { useRouter, usePathname } from 'next/navigation';
import { LogOut, LayoutDashboard, Server, UserCircle, Settings, Moon, Building2, Terminal } from 'lucide-react';
import Link from 'next/link';

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  if (!user) return <div className="min-h-screen bg-void flex items-center justify-center font-console text-gray-500">Loading cozy space...</div>;

  const navItems = [
    { icon: <LayoutDashboard size={20}/>, label: 'Overview', path: '/dashboard' },
    { icon: <Server size={20}/>, label: 'MCP Servers', path: '/dashboard/servers' },
    { icon: <UserCircle size={20}/>, label: 'Account', path: '/dashboard/account' },
    { icon: <Settings size={20}/>, label: 'System Settings', path: '/dashboard/settings' },
    { icon: <Terminal size={20}/>, label: 'Debug Log', path: '/dashboard/debug' },
  ];

  // Add Organization tab for Superusers
  if (user.role === 'superuser') {
    navItems.push({ 
      icon: <Building2 size={20}/>, 
      label: 'Organization', 
      path: '/dashboard/organization' 
    });
  }

  return (
    <div className="min-h-screen bg-void text-white flex overflow-hidden">
      {/* Sidebar */}
      <aside className="w-64 bg-void-surface border-r border-void-border flex flex-col p-4 space-y-8 shrink-0">
        <div className="flex items-center gap-3 px-2 mb-4">
          <div className="p-2 bg-eepy-lavender rounded-lg text-void">
            <Moon size={20} />
          </div>
          <span className="font-bold text-xl tracking-tight font-console">Eepy Host</span>
        </div>

        <nav className="flex-1 space-y-2">
          {navItems.map((item) => {
            const isActive = pathname === item.path;
            return (
              <Link key={item.label} href={item.path}>
                <div className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-all font-console text-sm cursor-pointer ${
                  isActive ? 'bg-eepy-lavender text-void font-bold shadow-[0_0_15px_rgba(195,177,225,0.3)]' : 'text-gray-400 hover:bg-void-border hover:text-white'
                }`}>
                  {item.icon} {item.label}
                </div>
              </Link>
            );
          })}
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

      {/* Main Content Wrapper */}
      <main className="flex-1 overflow-y-auto relative bg-gradient-to-br from-void via-void to-void-surface">
        {/* Global Background Glow for "Cyber Cozy" effect */}
        <div className="absolute top-0 right-0 w-[50%] h-[50%] bg-eepy-lavender/5 blur-[120px] rounded-full -z-10 pointer-events-none" />
        <div className="p-8">
          {children}
        </div>
      </main>
    </div>
  );
}
