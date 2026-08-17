'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { useAuth } from '@/context/AuthContext';
import { Moon, Plug, PlugZap, Loader2, Wifi, WifiOff } from 'lucide-react';
import { getApiUrl } from '@/lib/api';
import OpenWebUIExportPanel from '@/src/components/OpenWebUIExportPanel';

interface ToolKey {
  id: number;
  name: string;
  key_prefix: string;
  is_active: boolean;
}

interface MyConfig {
  id: number;
  template_name: string;
  is_active: boolean;
}

function authHeaders(): Record<string, string> {
  if (typeof window === 'undefined') return {};
  const token = localStorage.getItem('eepy_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export default function OverviewPage() {
  const { user } = useAuth();
  const [displayName, setDisplayName] = useState<string | null>(null);

  // Open WebUI connection state.
  const [activeKeys, setActiveKeys] = useState<ToolKey[]>([]);
  const [activeConfigs, setActiveConfigs] = useState<MyConfig[]>([]);
  const [owStatus, setOwStatus] = useState<'loading' | 'ready'>('loading');
  const [panelOpen, setPanelOpen] = useState(false);

  const hasActiveKey = activeKeys.some((k) => k.is_active);
  // "Connected" = the user has an active Eepy API key AND at least one active
  // integration behind it. Key without integrations = "Ready, no tools yet".
  const owState: 'connected' | 'key-only' | 'not-connected' | 'loading' =
    owStatus === 'loading'
      ? 'loading'
      : hasActiveKey
        ? activeConfigs.some((c) => c.is_active)
          ? 'connected'
          : 'key-only'
        : 'not-connected';

  useEffect(() => {
    async function fetchLatestProfile() {
      if (!user) return;
      try {
        const apiUrl = getApiUrl();
        const response = await fetch(`${apiUrl}/user/profile`, {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('eepy_token')}`,
          },
        });
        if (response.ok) {
          const data = await response.json();
          setDisplayName(data.full_name || user.username);
        }
      } catch (error) {
        console.error("Failed to fetch latest profile for dashboard:", error);
      }
    }
    fetchLatestProfile();
  }, [user]);

  const loadOwStatus = useCallback(async () => {
    setOwStatus('loading');
    try {
      const [keysRes, cfgRes] = await Promise.all([
        fetch(`${getApiUrl()}/api/mcp/api-keys`, { headers: authHeaders(), cache: 'no-store' }),
        fetch(`${getApiUrl()}/api/mcp/config/list`, { headers: authHeaders(), cache: 'no-store' }),
      ]);
      if (keysRes.ok) {
        const data = await keysRes.json();
        setActiveKeys(Array.isArray(data) ? data : []);
      }
      if (cfgRes.ok) {
        const data = await cfgRes.json();
        const list: MyConfig[] = Array.isArray(data) ? data : data.configs || [];
        setActiveConfigs(list);
      }
    } catch {
      // Offline backend - keep last known state, just stop the spinner.
    } finally {
      setOwStatus('ready');
    }
  }, []);

  useEffect(() => {
    loadOwStatus();
  }, [loadOwStatus]);

  const statusBadge = (() => {
    switch (owState) {
      case 'loading':
        return (
          <span className="px-3 py-1 bg-void border border-void-border rounded-full text-xs font-console text-gray-500 flex items-center gap-2">
            <Loader2 size={12} className="animate-spin" /> Checking...
          </span>
        );
      case 'connected':
        return (
          <span className="px-3 py-1 bg-eepy-mint/10 border border-eepy-mint/40 rounded-full text-xs font-console text-eepy-mint flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-eepy-mint animate-pulse" />
            Connected
          </span>
        );
      case 'key-only':
        return (
          <span className="px-3 py-1 bg-eepy-peach/10 border border-eepy-peach/40 rounded-full text-xs font-console text-eepy-peach flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-eepy-peach" />
            Key Active - No Tools Yet
          </span>
        );
      case 'not-connected':
        return (
          <span className="px-3 py-1 bg-void border border-void-border rounded-full text-xs font-console text-gray-500 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-gray-600" />
            Not Connected
          </span>
        );
    }
  })();

  return (
    <div className="space-y-12">
      <header className="flex justify-between items-center mb-8">
        <div>
          <h2 className="text-3xl font-bold font-console">Welcome back, <span className="text-eepy-lavender">{displayName || user?.fullName || user?.username}</span></h2>
          <p className="text-gray-500 font-console text-sm mt-1 italic">Current Role: {user?.role.toUpperCase()}</p>
        </div>

        <div className="flex items-center gap-4">
           <div className="px-3 py-1 bg-void-surface border border-void-border rounded-full text-xs font-console text-eepy-mint animate-pulse">
             System Status: Cozy
           </div>
        </div>
      </header>

      {/* Open WebUI - the single external tool server connection */}
      <section className="p-8 bg-void-surface/30 border border-void-border rounded-eepy backdrop-blur-sm">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-start gap-4">
            <div className={`p-3 rounded-lg shrink-0 ${owState === 'connected' ? 'bg-eepy-mint/10 text-eepy-mint' : 'bg-eepy-lavender/10 text-eepy-lavender'}`}>
              {owState === 'connected' ? <Wifi size={22} /> : <Plug size={22} />}
            </div>
            <div>
              <div className="flex items-center gap-3 flex-wrap">
                <h3 className="text-xl font-bold font-console">Open WebUI</h3>
                {statusBadge}
              </div>
              <p className="text-gray-500 font-console text-sm mt-1 max-w-xl leading-relaxed">
                One connection gives your agent every Eepy tool - all integrations you have connected, plus
                every one you connect later. No per-server setup, ever.
                {owState === 'not-connected' && ' Set up your tool server below to link your agent.'}
                {owState === 'key-only' && ' Connect at least one integration and your tools go live in Open WebUI automatically.'}
              </p>
            </div>
          </div>
          <button
            onClick={() => { setPanelOpen(true); loadOwStatus(); }}
            className="px-4 py-2.5 bg-eepy-lavender text-void rounded-lg text-xs font-console font-bold hover:bg-opacity-90 transition-all flex items-center gap-2 self-start"
          >
            <PlugZap size={15} />
            {owState === 'connected' ? 'Manage Tool Server' : 'Set Up Tool Server'}
          </button>
        </div>
      </section>

      {/* Dashboard Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Main Stat Card */}
        <div className="md:col-span-2 p-8 bg-void-surface border-4 border-void-border rounded-eepy relative overflow-hidden group hover:border-eepy-lavender/50 transition-colors shadow-xl">
          <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
            <Moon size={80} />
          </div>
          <h3 className="text-xl font-bold font-console mb-4 text-eepy-lavender">Host Status</h3>
          <p className="text-gray-400 font-console text-sm leading-relaxed max-w-md">
            {activeConfigs.some((c) => c.is_active) ? (
              <>
                You have <span className="text-eepy-mint font-bold">{activeConfigs.filter((c) => c.is_active).length}</span> active
                integration{activeConfigs.filter((c) => c.is_active).length !== 1 ? 's' : ''}. All tool calls route through the
                unified Eepy proxy - credentials stay encrypted at rest.
              </>
            ) : (
              <>
                Your MCP infrastructure is currently in <span className="text-white underline decoration-eepy-mint">Deep Sleep</span>.
                Connect an integration from the MCP Servers page to wake it up.
              </>
            )}
          </p>
          <a href="/dashboard/servers" className="inline-block mt-6 px-6 py-2 bg-void border border-void-border rounded-lg font-console text-xs hover:bg-void-border transition-colors">
            Open MCP Servers
          </a>
        </div>

        {/* Quick Actions Card */}
        <div className="p-8 bg-void-surface border-4 border-void-border rounded-eepy space-y-6 group hover:border-eepy-peach/50 transition-colors shadow-xl">
          <h3 className="text-xl font-bold font-console text-eepy-peach">Quick Actions</h3>
          <div className="space-y-3">
            {[
              { label: 'Connect an Integration', href: '/dashboard/servers', color: 'bg-eepy-lavender' },
              { label: 'Manage Account', href: '/dashboard/account', color: 'bg-eepy-mint' },
              { label: 'View Debug Log', href: '/dashboard/debug', color: 'bg-eepy-peach' },
            ].map((action) => (
              <a key={action.label} href={action.href} className="w-full py-3 px-4 bg-void border border-void-border rounded-xl text-left font-console text-xs hover:border-white transition-all flex justify-between items-center group block">
                {action.label} <div className={`w-2 h-2 rounded-full ${action.color}`} />
              </a>
            ))}
          </div>
        </div>
      </div>

      {panelOpen && (
        <OpenWebUIExportPanel
          onClose={() => {
            setPanelOpen(false);
            loadOwStatus();
          }}
        />
      )}
    </div>
  );
}
