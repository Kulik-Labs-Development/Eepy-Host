"use client";

import React, { useEffect, useState } from 'react';
import { useAuth } from '@/context/AuthContext';
import { usePathname } from 'next/navigation';
import { LogOut, LayoutDashboard, Server, UserCircle, Settings, Moon, Building2, Terminal, Menu, X } from 'lucide-react';
import Link from 'next/link';

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  const pathname = usePathname();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  // Close the mobile drawer whenever the route changes.
  useEffect(() => {
    setMobileNavOpen(false);
  }, [pathname]);

  // Prevent background scroll while the drawer is open.
  useEffect(() => {
    if (typeof document === 'undefined') return;
    document.body.style.overflow = mobileNavOpen ? 'hidden' : '';
    return () => { document.body.style.overflow = ''; };
  }, [mobileNavOpen]);

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

  const navLinks = navItems.map((item) => {
    // Exact match only. Prefix matching made 'Overview' (=/dashboard) stay
    // highlighted on every /dashboard/* sub-page.
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
  });

  const logo = (
    <div className="flex items-center gap-3 px-2 mb-4">
      <div className="p-2 bg-eepy-lavender rounded-lg text-void">
        <Moon size={20} />
      </div>
      <span className="font-bold text-xl tracking-tight font-console">Eepy Host</span>
    </div>
  );

  const logoutButton = (
    <button 
      onClick={logout}
      className="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-gray-400 hover:bg-red-500/10 hover:text-red-400 transition-all font-console text-sm"
    >
      <LogOut size={20} /> Logout
    </button>
  );

  return (
    <div className="min-h-screen bg-void text-white flex overflow-hidden">
      {/* Sidebar - desktop only */}
      <aside className="hidden md:block w-64 bg-void-surface border-r border-void-border flex flex-col p-4 space-y-8 shrink-0">
        {logo}
        <nav className="flex-1 space-y-2">{navLinks}</nav>
        <div className="pt-8 border-t border-void-border">{logoutButton}</div>
      </aside>

      {/* Mobile top bar */}
      <div className="md:hidden fixed top-0 inset-x-0 z-40 bg-void-surface/95 backdrop-blur-md border-b border-void-border flex items-center justify-between px-4 h-14">
        <div className="flex items-center gap-2">
          <div className="p-1.5 bg-eepy-lavender rounded-lg text-void">
            <Moon size={18} />
          </div>
          <span className="font-bold text-lg tracking-tight font-console">Eepy Host</span>
        </div>
        <button
          onClick={() => setMobileNavOpen(true)}
          className="p-2 -mr-2 text-gray-400 hover:text-white transition-colors"
          aria-label="Open navigation menu"
        >
          <Menu size={24} />
        </button>
      </div>

      {/* Mobile drawer */}
      {mobileNavOpen && (
        <div className="md:hidden fixed inset-0 z-50">
          <div
            className="absolute inset-0 bg-black/70 backdrop-blur-sm"
            onClick={() => setMobileNavOpen(false)}
          />
          <aside className="absolute left-0 top-0 bottom-0 w-72 max-w-[85vw] bg-void-surface border-r border-void-border flex flex-col p-4 space-y-8">
            <div className="flex items-center justify-between">
              {logo}
              <button
                onClick={() => setMobileNavOpen(false)}
                className="p-2 -mr-2 text-gray-400 hover:text-white transition-colors"
                aria-label="Close navigation menu"
              >
                <X size={22} />
              </button>
            </div>
            <nav className="flex-1 space-y-2 overflow-y-auto">{navLinks}</nav>
            <div className="border-t border-void-border pt-2">{logoutButton}</div>
          </aside>
        </div>
      )}

      {/* Main Content Wrapper */}
      <main className="flex-1 overflow-y-auto relative bg-gradient-to-br from-void via-void to-void-surface min-w-0">
        {/* Global Background Glow for "Cyber Cozy" effect */}
        <div className="absolute top-0 right-0 w-[50%] h-[50%] bg-eepy-lavender/5 blur-[120px] rounded-full -z-10 pointer-events-none" />
        <div className="p-4 sm:p-6 md:p-8 pt-20 md:pt-8">
          {children}
        </div>
      </main>
    </div>
  );
}
