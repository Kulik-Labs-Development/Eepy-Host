'use client';

// MCP Servers - the single hub for your active connections (primary) and the
// browsable Integration Library (secondary, searchable). Library templates come
// from the backend; "Connect" opens a schema-driven wizard that stores
// credentials (encrypted at rest). Active servers show the unified proxy URL, a
// live connection test, and disconnect.

import { useCallback, useEffect, useMemo, useState } from 'react';
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
} from 'lucide-react';
import { getApiUrl } from '@/lib/api';
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

function authHeaders(): Record<string, string> {
  if (typeof window === 'undefined') return {};
  const token = localStorage.getItem('eepy_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export default function ServersPage() {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [configs, setConfigs] = useState<MyConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [wizardTemplate, setWizardTemplate] = useState<Template | null>(null);

  // Per-config ephemeral UI state.
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const [testingId, setTestingId] = useState<number | null>(null);
  const [testResults, setTestResults] = useState<Record<number, { status: string; detail: string }>>({});

  // Search box for the (potentially long) integration library.
  const [search, setSearch] = useState('');

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

  const runTest = useCallback(async (templateName: string, configId: number) => {
    setTestingId(configId);
    setTestResults((prev) => ({ ...prev, [configId]: { status: 'testing', detail: 'Contacting HappyFox...' } }));
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
    <div className="space-y-8">
      <header className="flex justify-between items-center mb-2">
        <div>
          <h2 className="text-3xl font-bold font-console text-white">MCP Server Engine</h2>
          <p className="text-gray-500 font-console text-sm mt-1 flex items-center gap-1">
            <ShieldCheck size={14} className="text-eepy-mint" />
            Admin-approved integrations. Credentials encrypted at rest.
          </p>
        </div>
        <button
          onClick={refresh}
          className="px-4 py-2 bg-void border border-void-border rounded-xl hover:bg-void-border transition-all flex items-center gap-2 font-console text-sm"
        >
          <PlugZap size={16} /> Refresh
        </button>
      </header>

      {error && (
        <div className="p-4 bg-void-surface border-l-2 border-red-500 rounded text-sm text-red-400 flex items-center justify-between">
          <span>{error}</span>
          <button onClick={refresh} className="text-gray-400 hover:text-white text-xs underline">
            Retry
          </button>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-24 text-gray-500">
          <Loader2 className="animate-spin mr-2" size={20} /> Loading integrations...
        </div>
      ) : (
        <>
          {/* Active servers (primary, at top) */}
          <section className="p-8 bg-void-surface/30 border border-void-border rounded-eepy backdrop-blur-sm">
            <h3 className="text-xl font-bold font-console mb-6 flex items-center gap-2">
              <Server size={20} className="text-eepy-mint" /> Your Active Servers
            </h3>
            {configs.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-center space-y-2 border-2 border-dashed border-void-border rounded-xl">
                <p className="text-gray-600 font-console text-sm italic">No servers connected yet.</p>
                <p className="text-gray-700 font-console text-xs">Pick one from the integration library below to begin.</p>
              </div>
            ) : (
              <div className="space-y-4">
                {configs.map((config) => {
                  const result = testResults[config.id];
                  const isTemplate = templates.find((t) => t.id === config.template_name);
                  return (
                    <div key={config.id} className="p-5 bg-void border border-void-border rounded-xl">
                      <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-3">
                          <div className={`p-2 rounded-lg ${config.is_active ? 'bg-eepy-mint/10 text-eepy-mint' : 'bg-void border border-void-border text-gray-500'}`}>
                            {config.is_active ? <Wifi size={18} /> : <WifiOff size={18} />}
                          </div>
                          <div>
                            <p className="font-console text-white font-bold">
                              {isTemplate?.name || config.name_display || config.template_name}
                            </p>
                            <p className="text-xs text-gray-500 font-console">
                              {config.template_name}
                              {config.last_used_at ? ` · last used ${new Date(config.last_used_at).toLocaleDateString()}` : ' · never used'}
                            </p>
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => runTest(config.template_name, config.id)}
                            disabled={testingId === config.id}
                            className="px-3 py-2 bg-void border border-void-border rounded-lg text-xs font-console hover:bg-void-border transition-colors flex items-center gap-1.5 disabled:opacity-50"
                          >
                            <FlaskConical size={14} /> {testingId === config.id ? 'Testing...' : 'Run Live Test'}
                          </button>
                          <button
                            onClick={() => disconnect(config.template_name, config.id)}
                            className="p-2 border border-void-border rounded-lg hover:bg-red-500/10 hover:text-red-400 transition-colors"
                            title="Disconnect"
                          >
                            <Trash2 size={16} />
                          </button>
                        </div>
                      </div>

                      <div className="flex items-center gap-2">
                        <span className="text-xs font-console text-gray-500 flex items-center gap-1 shrink-0">
                          <ExternalLink size={13} />
                        </span>
                        <code className="flex-1 text-xs bg-void border border-void-border rounded px-3 py-2 text-eepy-mint break-all">
                          {typeof window !== 'undefined' ? `${window.location.origin}${proxyUrl(config.template_name)}` : proxyUrl(config.template_name)}
                        </code>
                        <button
                          onClick={() => copyUrl(config.template_name, config.id)}
                          className="p-2 border border-void-border rounded-lg hover:bg-void-border transition-colors"
                          title="Copy proxy URL"
                        >
                          {copiedId === config.id ? <Check size={16} className="text-eepy-mint" /> : <Copy size={16} />}
                        </button>
                      </div>

                      {result && (
                        <p
                          className={`text-xs mt-3 p-2.5 rounded border-l-2 bg-void ${
                            result.status === 'ok' ? 'text-eepy-mint border-eepy-mint' : 'text-red-400 border-red-500'
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

          {/* Integration Library (browsable catalog, filtered) */}
          <section>
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
              <h3 className="text-xl font-bold font-console flex items-center gap-2">
                <PlugZap size={20} className="text-eepy-lavender" /> Integration Library
                <span className="text-xs font-normal text-gray-600">({filteredTemplates.length})</span>
              </h3>
              {templates.length > 0 && (
                <div className="relative">
                  <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                  <input
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search integrations..."
                    className="w-full sm:w-72 pl-9 pr-3 py-2 bg-void border border-void-border rounded-lg text-sm text-white font-console placeholder:text-gray-600 focus:outline-none focus:border-eepy-lavender transition-colors"
                  />
                </div>
              )}
            </div>
            {templates.length === 0 ? (
              <div className="p-8 bg-void-surface/30 border border-void-border rounded-eepy text-center text-gray-600 font-console text-sm italic">
                No approved integrations yet. Check back soon.
              </div>
            ) : filteredTemplates.length === 0 ? (
              <div className="p-8 bg-void-surface/30 border border-void-border rounded-eepy text-center text-gray-600 font-console text-sm italic">
                No integrations match "{search}".
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {filteredTemplates.map((template) => {
                  const isConnected = configs.some((c) => c.template_name === template.id);
                  return (
                    <div
                      key={template.id}
                      className="p-6 bg-void-surface border-t-4 border-eepy-lavender border-x border-b border-void-border rounded-eepy group hover:scale-[1.02] transition-all shadow-xl flex flex-col"
                    >
                      <div className="flex justify-between items-start mb-4">
                        <div className="p-3 bg-void rounded-lg text-gray-400 group-hover:text-white transition-colors">
                          <PlugZap size={24} />
                        </div>
                        {template.config_schema?.category && (
                          <span className="px-2 py-1 bg-void border border-void-border text-[10px] font-console text-gray-500 rounded uppercase tracking-tighter">
                            {template.config_schema.category}
                          </span>
                        )}
                      </div>
                      <h4 className="text-lg font-bold font-console mb-2 text-eepy-mint">{template.name}</h4>
                      <p className="text-gray-500 text-sm mb-6 leading-relaxed flex-1">{template.description}</p>
                      {isConnected ? (
                        <div className="w-full py-2 bg-void border border-eepy-mint rounded-lg text-xs font-console text-eepy-mint flex items-center justify-center gap-2">
                          <Check size={14} /> Connected
                        </div>
                      ) : (
                        <button
                          onClick={() => setWizardTemplate(template)}
                          className="w-full py-2 bg-eepy-lavender text-void rounded-lg text-xs font-console font-bold hover:bg-opacity-90 transition-all"
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
        </>
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
