'use client';

// MCP Servers - the single hub for integrations, split into two sub-tabs so
// the page stays scannable as the catalog grows:
//   - "My MCP Servers" (default): your active connections. Each shows the
//     unified proxy URL, a live connection test, and disconnect.
//   - "MCP Library": the browsable, searchable catalog of admin-approved
//     templates. "Connect" opens a schema-driven wizard that stores
//     credentials (encrypted at rest). Superusers additionally get the Tool
//     Discovery panel (captures real tools/list schemas per template).
//
// The active sub-tab persists in the ?tab= query param (deep-linkable).
//
// NOTE: the Open WebUI tool-server setup lives on the Overview page
// (/dashboard) - this page is purely integrations in/out.

import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import {
  Server,
  Loader2,
  PlugZap,
  Copy,
  Check,
  FlaskConical,
  ShieldCheck,
  ExternalLink,
  Trash2,
  Wifi,
  WifiOff,
  Search,
  Radar,
  Library,
} from 'lucide-react';
import { getApiUrl } from '@/lib/api';
import { useAuth } from '@/context/AuthContext';
import MCPConnectionWizard, { TemplateSchema } from '@/src/components/MCPConnectionWizard';

interface Template {
  id: string;
  name: string;
  description: string;
  config_schema?: TemplateSchema & { category?: string };
  image_tag?: string | null;
}

interface MyConfig {
  id: number;
  template_name: string;
  name_display: string | null;
  is_active: boolean;
  last_used_at: string | null;
}

interface DiscoveryRow {
  id: string;
  name: string;
  runtime: string;
  tool_count: number;
  tools_discovered_at: string | null;
}

function authHeaders(): Record<string, string> {
  if (typeof window === 'undefined') return {};
  const token = localStorage.getItem('eepy_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

type ServerTab = 'library' | 'mine';

function ServersPageInner() {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [configs, setConfigs] = useState<MyConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [wizardTemplate, setWizardTemplate] = useState<Template | null>(null);

  // Sub-tab: ?tab=library deep-links to the catalog; default is the user's
  // own servers. Written with history.replaceState (no push), so the back
  // button behaves normally.
  const searchParams = useSearchParams();
  const [tab, setTab] = useState<ServerTab>(() =>
    searchParams.get('tab') === 'library' ? 'library' : 'mine'
  );

  const switchTab = (next: ServerTab) => {
    setTab(next);
    if (typeof window === 'undefined') return;
    const url = new URL(window.location.href);
    if (next === 'library') url.searchParams.set('tab', 'library');
    else url.searchParams.delete('tab');
    window.history.replaceState(null, '', url.toString());
  };

  // Per-config ephemeral UI state.
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const [testingId, setTestingId] = useState<number | null>(null);
  const [testResults, setTestResults] = useState<Record<number, { status: string; detail: string }>>({});

  // Search box for the (potentially long) integration library.
  const [search, setSearch] = useState('');

  // Superuser-only Tool Discovery: captures each integration's real tool
  // schemas (tools/list) so the unified OpenAPI spec is typed. Without it a
  // template serves name-only untyped tools and Open WebUI cannot pass
  // arguments to them (upstream 'Field required').
  const { user } = useAuth();
  const isSuperuser = user?.role === 'SUPERUSER';
  const [discovery, setDiscovery] = useState<DiscoveryRow[]>([]);
  const [discoveringId, setDiscoveringId] = useState<string | null>(null);
  const [discoveryResults, setDiscoveryResults] = useState<Record<string, { status: string; detail: string }>>({});

  const loadDiscovery = useCallback(async () => {
    if (!isSuperuser) return;
    try {
      const res = await fetch(`${getApiUrl()}/superuser/mcp/templates`, { headers: authHeaders(), cache: 'no-store' });
      if (res.ok) {
        const data = await res.json();
        setDiscovery(Array.isArray(data) ? data : []);
      }
    } catch {
      // Non-fatal: the section simply stays empty.
    }
  }, [isSuperuser]);

  const runDiscover = useCallback(
    async (templateId: string) => {
      setDiscoveringId(templateId);
      setDiscoveryResults((prev) => ({
        ...prev,
        [templateId]: { status: 'running', detail: 'Contacting the integration sidecar (tools/list)...' },
      }));
      try {
        const res = await fetch(`${getApiUrl()}/superuser/mcp/templates/${templateId}/discover`, {
          method: 'POST',
          headers: authHeaders(),
        });
        const data = await res.json().catch(() => ({}));
        setDiscoveryResults((prev) => ({
          ...prev,
          [templateId]: res.ok
            ? {
                status: 'ok',
                detail: `Discovered ${data.tool_count ?? 0} tools. Re-import the Open WebUI tool server to pick up the new schemas.`,
              }
            : { status: 'failed', detail: data.detail || `HTTP ${res.status}` },
        }));
        if (res.ok) await loadDiscovery();
      } catch {
        setDiscoveryResults((prev) => ({ ...prev, [templateId]: { status: 'failed', detail: 'Could not reach the backend.' } }));
      } finally {
        setDiscoveringId(null);
      }
    },
    [loadDiscovery]
  );

  const filteredTemplates = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return templates;
    return templates.filter((t) =>
      [t.name, t.description, t.id, t.config_schema?.category || ''].join(' ').toLowerCase().includes(q)
    );
  }, [templates, search]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [tplRes, cfgRes] = await Promise.all([
        fetch(`${getApiUrl()}/api/mcp/templates/list`, { headers: authHeaders(), cache: 'no-store' }),
        fetch(`${getApiUrl()}/api/mcp/config/list`, { headers: authHeaders(), cache: 'no-store' }),
      ]);
      if (tplRes.status === 401 || cfgRes.status === 401) {
        setError('Session expired. Please sign in again.');
        setLoading(false);
        return;
      }
      if (!tplRes.ok) throw new Error(`Library backend returned ${tplRes.status}`);
      const tplData = await tplRes.json();
      setTemplates(Array.isArray(tplData) ? tplData : tplData.templates || []);

      // Configs are optional (200 or 404-ish is fine).
      if (cfgRes.ok) {
        const cfgData = await cfgRes.json();
        setConfigs(Array.isArray(cfgData) ? cfgData : cfgData.configs || []);
      }
    } catch (err) {
      console.error('MCP load error:', err instanceof Error ? err.message : String(err));
      setError('Could not reach the MCP backend. Is the API service running?');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const runTest = useCallback(async (templateName: string, configId: number, displayName?: string) => {
    setTestingId(configId);
    setTestResults((prev) => ({ ...prev, [configId]: { status: 'testing', detail: `Contacting ${displayName || templateName}...` } }));
    try {
      const res = await fetch(`${getApiUrl()}/api/mcp/config/${templateName}/test`, {
        method: 'POST',
        headers: authHeaders(),
      });
      const data = await res.json().catch(() => ({}));
      setTestResults((prev) => ({
        ...prev,
        [configId]: { status: data.status || (res.ok ? 'ok' : 'failed'), detail: data.detail || `HTTP ${res.status}` },
      }));
    } catch {
      setTestResults((prev) => ({ ...prev, [configId]: { status: 'failed', detail: 'Could not reach the backend.' } }));
    } finally {
      setTestingId(null);
    }
  }, []);

  const disconnect = useCallback(
    async (templateName: string, configId: number) => {
      const res = await fetch(`${getApiUrl()}/api/mcp/config/${templateName}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (res.ok) {
        setConfigs((prev) => prev.filter((c) => c.id !== configId));
        setTestResults((prev) => {
          const next = { ...prev };
          delete next[configId];
          return next;
        });
      } else {
        setTestResults((prev) => ({ ...prev, [configId]: { status: 'failed', detail: 'Failed to disconnect.' } }));
      }
    },
    []
  );

  const proxyUrl = (templateName: string) => `/api/mcp/proxy/${templateName}`;

  const copyUrl = (templateName: string, configId: number) => {
    const full = typeof window !== 'undefined' ? `${window.location.origin}${proxyUrl(templateName)}` : proxyUrl(templateName);
    navigator.clipboard
      .writeText(full)
      .then(() => {
        setCopiedId(configId);
        setTimeout(() => setCopiedId(null), 1500);
      })
      .catch(() => {});
  };

  return (
    <div className="space-y-8 max-w-6xl mx-auto">
      <header className="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4 mb-2">
        <div>
          <h2 className="font-pixel font-bold text-2xl sm:text-3xl text-ink text-px-sm">MCP Server Engine</h2>
          <p className="text-ink-dim font-body text-sm mt-1 flex items-center gap-1.5">
            <ShieldCheck size={14} className="text-eepy-sage shrink-0" />
            Admin-approved integrations. Credentials encrypted at rest.
          </p>
        </div>
        <button
          onClick={refresh}
          className="btn btn-ghost px-4 py-2 text-sm shrink-0 self-start sm:self-auto"
        >
          <PlugZap size={16} /> Refresh
        </button>
      </header>

      {error && (
        <div className="p-4 bg-eepy-ember/10 border-2 border-eepy-ember/50 text-eepy-ember text-sm font-body flex items-center justify-between">
          <span>{error}</span>
          <button onClick={refresh} className="text-ink-soft hover:text-ink text-xs underline font-body">
            Retry
          </button>
        </div>
      )}

      {/* Sub-tabs: split the hub into the catalog and the user's own connections */}
      <div className="flex flex-wrap gap-2" role="group" aria-label="MCP servers sections">
        <button
          onClick={() => switchTab('library')}
          aria-pressed={tab === 'library'}
          className={`btn px-4 py-2 ${tab === 'library' ? 'btn-blush' : 'btn-ghost'}`}
        >
          <Library size={16} /> MCP Library
          {!loading && <span className="opacity-70">({templates.length})</span>}
        </button>
        <button
          onClick={() => switchTab('mine')}
          aria-pressed={tab === 'mine'}
          className={`btn px-4 py-2 ${tab === 'mine' ? 'btn-blush' : 'btn-ghost'}`}
        >
          <Server size={16} /> My MCP Servers
          {!loading && <span className="opacity-70">({configs.length})</span>}
        </button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-24 text-ink-faint">
          <Loader2 className="animate-spin mr-3" size={20} />
          <span className="font-pixel font-bold">Loading integrations...</span>
        </div>
      ) : tab === 'library' ? (
        <>
          {/* Integration Library (browsable catalog, filtered) */}
          <section>
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
              <h3 className="font-pixel font-bold text-xl flex items-center gap-2.5 text-ink">
                <PlugZap size={20} className="text-eepy-lilac" /> Integration Library
                <span className="text-xs font-normal text-ink-dim font-body">({filteredTemplates.length})</span>
              </h3>
              {templates.length > 0 && (
                <div className="relative w-full sm:w-72">
                  <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-dim" />
                  <input
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search integrations..."
                    className="input-pixel pl-9 py-2.5 text-sm"
                  />
                </div>
              )}
            </div>
            {templates.length === 0 ? (
              <div className="panel p-8 text-center text-ink-dim font-body text-sm italic">
                No approved integrations yet. Check back soon.
              </div>
            ) : filteredTemplates.length === 0 ? (
              <div className="panel p-8 text-center text-ink-dim font-body text-sm italic">
                No integrations match &ldquo;{search}&rdquo;.
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-6">
                {filteredTemplates.map((template) => {
                  const isConnected = configs.some((c) => c.template_name === template.id);
                  return (
                    <div
                      key={template.id}
                      className="panel pixel-caps lift p-6 [--cap:theme('colors.eepy.blush')] hover:border-eepy-blush/60 flex flex-col"
                    >
                      <div className="flex justify-between items-start mb-4">
                        <div className="well p-3 text-ink-faint">
                          <PlugZap size={22} />
                        </div>
                        {template.config_schema?.category && (
                          <span className="chip">{template.config_schema.category}</span>
                        )}
                      </div>
                      <h4 className="font-pixel font-bold text-lg mb-2 text-eepy-sage">{template.name}</h4>
                      <p className="text-ink-faint font-body text-sm mb-6 leading-relaxed flex-1">{template.description}</p>
                      {isConnected ? (
                        <div className="w-full chip chip-sage justify-center py-2">
                          <Check size={14} /> Connected
                        </div>
                      ) : (
                        <button
                          onClick={() => setWizardTemplate(template)}
                          className="btn btn-blush w-full py-2.5 text-sm"
                        >
                          Connect
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </section>

          {/* Tool Discovery (superuser only) */}
          {isSuperuser && (
            <section className="panel pixel-caps p-4 sm:p-6 md:p-8 [--cap:theme('colors.eepy.amber')]">
              <h3 className="font-pixel font-bold text-xl mb-2 flex items-center gap-2.5 text-ink">
                <Radar size={20} className="text-eepy-amber" /> Tool Discovery
                <span className="chip chip-amber text-[11px]">superuser</span>
              </h3>
              <p className="text-ink-dim font-body text-xs mb-5 leading-relaxed">
                Captures each integration&apos;s real tool schemas from its upstream server
                (tools/list) using YOUR OWN stored connection to it. The Open WebUI spec is
                built from this data &mdash; a template at 0 tools serves UNTYPED tools, so
                Open WebUI cannot pass arguments to them. Re-run whenever the upstream
                integration changes.
              </p>
              {discovery.length === 0 ? (
                <p className="text-ink-faint font-body text-sm italic">No approved templates found.</p>
              ) : (
                <div className="space-y-3">
                  {discovery.map((t) => {
                    const result = discoveryResults[t.id];
                    const runnable = t.runtime === 'mcp-server';
                    return (
                      <div key={t.id} className="card p-4">
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                          <div className="min-w-0">
                            <p className="font-pixel font-bold text-ink truncate">{t.name}</p>
                            <p className="text-[13px] text-ink-dim font-console truncate">
                              {t.id}
                              {t.tool_count > 0
                                ? ` · ${t.tool_count} tools discovered` +
                                  (t.tools_discovered_at
                                    ? ` · ${new Date(t.tools_discovered_at).toLocaleString()}`
                                    : '')
                                : ' · NO schemas discovered — Open WebUI tools will be UNTYPED'}
                            </p>
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            {t.tool_count === 0 && runnable && (
                              <span className="chip chip-ember text-[11px]">needs discovery</span>
                            )}
                            <button
                              onClick={() => runDiscover(t.id)}
                              disabled={discoveringId !== null || !runnable}
                              className="btn btn-amber px-3 py-2 text-xs flex items-center gap-1.5"
                            >
                              {discoveringId === t.id ? (
                                <Loader2 size={14} className="animate-spin" />
                              ) : (
                                <Radar size={14} />
                              )}
                              {discoveringId === t.id ? 'Discovering...' : 'Discover tools'}
                            </button>
                          </div>
                        </div>
                        {result && (
                          <p
                            className={`text-sm mt-3 p-2.5 font-body border-l-4 ${
                              result.status === 'ok'
                                ? 'text-eepy-sage border-eepy-sage bg-eepy-sage/5'
                                : 'text-eepy-ember border-eepy-ember bg-eepy-ember/5'
                            }`}
                          >
                            {result.detail}
                          </p>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </section>
          )}
        </>
      ) : (
        /* My MCP Servers (active connections) */
        <section className="panel pixel-caps p-4 sm:p-6 md:p-8 [--cap:theme('colors.eepy.sage')]">
          <h3 className="font-pixel font-bold text-xl mb-6 flex items-center gap-2.5 text-ink">
            <Server size={20} className="text-eepy-sage" /> Your Active Servers
          </h3>
          {configs.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center space-y-2 border-2 border-dashed border-night-border">
              <p className="text-ink-faint font-body text-sm italic">No servers connected yet.</p>
              <button
                onClick={() => switchTab('library')}
                className="btn btn-ghost px-4 py-2 text-xs mt-1 flex items-center gap-1.5"
              >
                <Library size={14} /> Browse the MCP Library
              </button>
            </div>
          ) : (
            <div className="space-y-4">
              {configs.map((config) => {
                const result = testResults[config.id];
                const isTemplate = templates.find((t) => t.id === config.template_name);
                return (
                  <div key={config.id} className="card p-4 sm:p-5">
                    <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3 mb-3">
                      <div className="flex items-center gap-3 min-w-0">
                        <div className={`well p-2 shrink-0 ${config.is_active ? 'text-eepy-sage' : 'text-ink-dim'}`}>
                          {config.is_active ? <Wifi size={18} /> : <WifiOff size={18} />}
                        </div>
                        <div className="min-w-0">
                          <p className="font-pixel font-bold text-ink truncate">
                            {isTemplate?.name || config.name_display || config.template_name}
                          </p>
                          <p className="text-[13px] text-ink-dim font-console truncate">
                            {config.template_name}
                            {config.last_used_at ? ` · last used ${new Date(config.last_used_at).toLocaleDateString()}` : ' · never used'}
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center gap-2 shrink-0 self-end lg:self-auto">
                        <button
                          onClick={() => runTest(config.template_name, config.id, isTemplate?.name || config.name_display || config.template_name)}
                          disabled={testingId === config.id}
                          className="btn btn-ghost px-3 py-2 text-xs flex items-center gap-1.5"
                        >
                          <FlaskConical size={14} /> {testingId === config.id ? 'Testing...' : 'Run Live Test'}
                        </button>
                        <button
                          onClick={() => disconnect(config.template_name, config.id)}
                          className="btn-icon"
                          title="Disconnect"
                        >
                          <Trash2 size={16} />
                        </button>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 min-w-0">
                      <span className="text-ink-dim flex items-center gap-1 shrink-0">
                        <ExternalLink size={13} />
                      </span>
                      <code className="well flex-1 text-[15px] px-3 py-2 text-eepy-sage break-all font-console leading-snug">
                        {typeof window !== 'undefined' ? `${window.location.origin}${proxyUrl(config.template_name)}` : proxyUrl(config.template_name)}
                      </code>
                      <button
                        onClick={() => copyUrl(config.template_name, config.id)}
                        className="btn-icon"
                        title="Copy proxy URL"
                      >
                        {copiedId === config.id ? <Check size={16} className="text-eepy-sage" /> : <Copy size={16} />}
                      </button>
                    </div>

                    {result && (
                      <p
                        className={`text-sm mt-3 p-2.5 font-body border-l-4 ${
                          result.status === 'ok'
                            ? 'text-eepy-sage border-eepy-sage bg-eepy-sage/5'
                            : 'text-eepy-ember border-eepy-ember bg-eepy-ember/5'
                        }`}
                      >
                        {result.detail}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </section>
      )}

      {wizardTemplate && (
        <MCPConnectionWizard
          templateId={wizardTemplate.id}
          templateName={wizardTemplate.name}
          schema={wizardTemplate.config_schema}
          onSuccess={() => {
            setWizardTemplate(null);
            refresh();
          }}
          onClose={() => setWizardTemplate(null)}
        />
      )}

    </div>
  );
}

export default function ServersPage() {
  // Suspense boundary: Next statically pre-renders this client page, and
  // useSearchParams() requires a Suspense fallback during that prerender.
  return (
    <Suspense fallback={null}>
      <ServersPageInner />
    </Suspense>
  );
}
