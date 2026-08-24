'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { useAuth } from '@/context/AuthContext';
import { Plug, PlugZap, Loader2, Wifi, Bot, Cpu } from 'lucide-react';
import { getApiUrl } from '@/lib/api';
import OpenWebUIExportPanel from '@/src/components/OpenWebUIExportPanel';
import AIPlatformConnectorPanel from '@/src/components/AIPlatformConnectorPanel';
import PixelMoon from '@/src/components/PixelMoon';

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
  const [mcpPanelOpen, setMcpPanelOpen] = useState(false);

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
          <span className="chip">
            <Loader2 size={12} className="animate-spin" /> Checking...
          </span>
        );
      case 'connected':
        return (
          <span className="chip chip-sage">
            <span className="led bg-eepy-sage animate-led" />
            Connected
          </span>
        );
      case 'key-only':
        return (
          <span className="chip chip-amber">
            <span className="led bg-eepy-amber" />
            Key Active - No Tools Yet
          </span>
        );
      case 'not-connected':
        return (
          <span className="chip">
            <span className="led bg-ink-dim" />
            Not Connected
          </span>
        );
    }
  })();

  return (
    <div className="space-y-10 max-w-6xl mx-auto">
      <header className="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4 mb-8">
        <div>
          <h2 className="font-pixel font-bold text-2xl sm:text-3xl text-px-sm">
            Welcome back, <span className="text-eepy-blush">{displayName || user?.fullName || user?.username}</span>
          </h2>
          <p className="text-ink-dim font-console text-[15px] mt-1">
            current role: {user?.role.toUpperCase()}
          </p>
        </div>
        <span className="chip chip-sage self-start sm:self-auto whitespace-nowrap">
          <span className="led bg-eepy-sage animate-led" />
          System Status: Cozy
        </span>
      </header>

      {/* Open WebUI - the single external tool server connection */}
      <section className="panel pixel-caps p-4 sm:p-6 md:p-8 [--cap:theme('colors.eepy.lilac')]">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-start gap-4">
            <div className={`well p-3 shrink-0 ${owState === 'connected' ? 'text-eepy-sage' : 'text-eepy-lilac'}`}>
              {owState === 'connected' ? <Wifi size={22} /> : <Plug size={22} />}
            </div>
            <div>
              <div className="flex items-center gap-3 flex-wrap">
                <h3 className="font-pixel font-bold text-xl text-ink">Open WebUI</h3>
                {statusBadge}
              </div>
              <p className="text-ink-faint font-body text-sm mt-2 max-w-xl leading-relaxed">
                One connection gives your agent every Eepy tool - all integrations you have connected, plus
                every one you connect later. No per-server setup, ever.
                {owState === 'not-connected' && ' Set up your tool server below to link your agent.'}
                {owState === 'key-only' && ' Connect at least one integration and your tools go live in Open WebUI automatically.'}
              </p>
            </div>
          </div>
          <button
            onClick={() => { setPanelOpen(true); loadOwStatus(); }}
            className="btn btn-blush px-5 py-2.5 text-sm self-start sm:self-auto w-full sm:w-auto"
          >
            <PlugZap size={15} />
            {owState === 'connected' ? 'Manage Tool Server' : 'Set Up Tool Server'}
          </button>
        </div>
      </section>

      {/* AI Platforms - native MCP endpoint for coding agents */}
      <section className="panel pixel-caps p-4 sm:p-6 md:p-8 [--cap:theme('colors.eepy.sage')]">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-start gap-4">
            <div className={`well p-3 shrink-0 ${owState === 'connected' ? 'text-eepy-sage' : 'text-eepy-blush'}`}>
              {owState === 'connected' ? <Cpu size={22} /> : <Bot size={22} />}
            </div>
            <div>
              <div className="flex items-center gap-3 flex-wrap">
                <h3 className="font-pixel font-bold text-xl text-ink">AI Platforms (MCP)</h3>
                {statusBadge}
              </div>
              <p className="text-ink-faint font-body text-sm mt-2 max-w-xl leading-relaxed">
                Native Model Context Protocol endpoint - coding agents like opencode, Claude Desktop, and Cursor
                connect directly to every Eepy tool you have connected. No OpenAPI import, no translation layer.
                {owState === 'not-connected' && ' Create a key below and point your agent at the endpoint.'}
                {owState === 'key-only' && ' Connect at least one integration and your tools go live in your agent automatically.'}
              </p>
            </div>
          </div>
          <button
            onClick={() => { setMcpPanelOpen(true); loadOwStatus(); }}
            className="btn btn-sage px-5 py-2.5 text-sm self-start sm:self-auto w-full sm:w-auto"
          >
            <Bot size={15} />
            {owState === 'connected' ? 'Manage MCP Connection' : 'Set Up MCP Connection'}
          </button>
        </div>
      </section>

      {/* Dashboard Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Main Stat Card */}
        <div className="md:col-span-2 panel pixel-caps p-4 sm:p-6 md:p-8 [--cap:theme('colors.eepy.blush')] overflow-hidden group hover:border-eepy-blush/60 transition-colors">
          <div className="absolute top-4 right-4 opacity-15 group-hover:opacity-25 transition-opacity">
            <PixelMoon size={88} />
          </div>
          <h3 className="font-pixel font-bold text-xl mb-4 text-eepy-blush">Host Status</h3>
          <p className="text-ink-soft font-body text-sm leading-relaxed max-w-md">
            {activeConfigs.some((c) => c.is_active) ? (
              <>
                You have <span className="text-eepy-sage font-bold">{activeConfigs.filter((c) => c.is_active).length}</span> active
                integration{activeConfigs.filter((c) => c.is_active).length !== 1 ? 's' : ''}. All tool calls route through the
                unified Eepy proxy - credentials stay encrypted at rest.
              </>
            ) : (
              <>
                Your MCP infrastructure is currently in <span className="text-ink font-bold underline decoration-eepy-sage decoration-2 underline-offset-4">Deep Sleep</span>.
                Connect an integration from the MCP Library to wake it up.
              </>
            )}
          </p>
          <a href="/dashboard/servers" className="btn btn-ghost px-5 py-2 text-sm mt-6">
            Open MCP Servers
          </a>
        </div>

        {/* Quick Actions Card */}
        <div className="panel pixel-caps p-4 sm:p-6 md:p-8 space-y-5 [--cap:theme('colors.eepy.amber')]">
          <h3 className="font-pixel font-bold text-xl text-eepy-amber">Quick Actions</h3>
          <div className="space-y-3">
            {[
              { label: 'Connect an Integration', href: '/dashboard/servers/library', led: 'bg-eepy-blush' },
              { label: 'Manage Account', href: '/dashboard/account', led: 'bg-eepy-sage' },
              { label: 'View Debug Log', href: '/dashboard/debug', led: 'bg-eepy-amber' },
            ].map((action) => (
              <a
                key={action.label}
                href={action.href}
                className="card w-full py-3 px-4 font-body text-sm text-ink-soft hover:border-eepy-blush/70 hover:text-ink transition-colors flex justify-between items-center group"
              >
                {action.label}
                <span className={`led ${action.led}`} />
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

      {mcpPanelOpen && (
        <AIPlatformConnectorPanel
          onClose={() => {
            setMcpPanelOpen(false);
            loadOwStatus();
          }}
        />
      )}
    </div>
  );
}
