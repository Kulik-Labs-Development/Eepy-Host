"use client";

import React, { useEffect, useState } from 'react';
import { useAuth } from '@/context/AuthContext';
import { usePathname } from 'next/navigation';
import { LogOut, LayoutDashboard, Server, UserCircle, Settings, Building2, Terminal, Menu, X } from 'lucide-react';
import Link from 'next/link';
import PixelMoon from '@/src/components/PixelMoon';

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

  if (!user) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-5">
        <PixelMoon size={72} className="animate-twinkle" />
        <p className="font-pixel font-bold text-ink-faint text-px-sm">Loading cozy space...</p>
      </div>
    );
  }

  const navItems = [
    { icon: <LayoutDashboard size={18} />, label: 'Overview', path: '/dashboard' },
    { icon: <Server size={18} />, label: 'MCP Servers', path: '/dashboard/servers' },
    { icon: <UserCircle size={18} />, label: 'Account', path: '/dashboard/account' },
    { icon: <Settings size={18} />, label: 'System Settings', path: '/dashboard/settings' },
    { icon: <Terminal size={18} />, label: 'Debug Log', path: '/dashboard/debug' },
  ];

  // Add Organization tab for Superusers
  if (user.role === 'superuser') {
    navItems.push({
      icon: <Building2 size={18} />,
      label: 'Organization',
      path: '/dashboard/organization',
    });
  }

  const navLinks = navItems.map((item) => {
    // Exact match only. Prefix matching made 'Overview' (=/dashboard) stay
    // highlighted on every /dashboard/* sub-page.
    const isActive = pathname === item.path;
    return (
      <Link key={item.label} href={item.path}>
        <div
          className={`w-full flex items-center gap-3 px-3 py-2.5 font-pixel font-bold text-sm border-2 transition-colors ${
            isActive
              ? 'bg-eepy-blush border-eepy-pink text-night-deep shadow-pixel-sm'
              : 'border-transparent text-ink-soft hover:text-ink hover:bg-night-raise hover:border-night-border'
          }`}
        >
          {item.icon} {item.label}
        </div>
      </Link>
    );
  });

  const logo = (
    <div className="flex items-center gap-3 px-1 mb-6">
      <PixelMoon size={36} />
      <span className="font-pixel font-bold text-xl tracking-tight text-ink text-px-sm">
        Eepy <span className="text-eepy-blush">Host</span>
      </span>
    </div>
  );

  const logoutButton = (
    <button
      onClick={logout}
      className="btn btn-danger w-full py-2.5 text-sm"
    >
      <LogOut size={16} /> Logout
    </button>
  );

  return (
    <div className="min-h-screen flex overflow-hidden">
      {/* Sidebar - desktop only */}
      <aside className="hidden md:block w-64 bg-night-surface border-r-2 border-night-border flex flex-col p-4 space-y-6 shrink-0">
        {logo}
        <nav className="flex-1 space-y-2">{navLinks}</nav>
        <div className="pt-4 border-t-2 border-night-line">{logoutButton}</div>
      </aside>

      {/* Mobile top bar */}
      <div className="md:hidden fixed top-0 inset-x-0 z-40 bg-night-surface/95 backdrop-blur-md border-b-2 border-night-border flex items-center justify-between px-4 h-14">
        <div className="flex items-center gap-2">
          <PixelMoon size={30} />
          <span className="font-pixel font-bold text-lg tracking-tight text-ink">
            Eepy <span className="text-eepy-blush">Host</span>
          </span>
        </div>
        <button
          onClick={() => setMobileNavOpen(true)}
          className="btn-icon"
          aria-label="Open navigation menu"
        >
          <Menu size={20} />
        </button>
      </div>

      {/* Mobile drawer */}
      {mobileNavOpen && (
        <div className="md:hidden fixed inset-0 z-50">
          <div
            className="absolute inset-0 bg-night-deep/80 backdrop-blur-sm"
            onClick={() => setMobileNavOpen(false)}
          />
          <aside className="absolute left-0 top-0 bottom-0 w-72 max-w-[85vw] bg-night-surface border-r-2 border-night-border flex flex-col p-4 space-y-6">
            <div className="flex items-center justify-between">
              {logo}
              <button
                onClick={() => setMobileNavOpen(false)}
                className="btn-icon"
                aria-label="Close navigation menu"
              >
                <X size={18} />
              </button>
            </div>
            <nav className="flex-1 space-y-2 overflow-y-auto">{navLinks}</nav>
            <div className="border-t-2 border-night-line pt-4">{logoutButton}</div>
          </aside>
        </div>
      )}

      {/* Main Content Wrapper — the global starry backdrop shows through */}
      <main className="flex-1 overflow-y-auto relative min-w-0">
        <div className="p-4 sm:p-6 md:p-8 pt-20 md:pt-8">
          {children}
        </div>
      </main>
    </div>
  );
}
