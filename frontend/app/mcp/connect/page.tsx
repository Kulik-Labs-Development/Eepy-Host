'use client';

// MCP Connect route - drives the connection wizard for a selected template,
// shows the success state with the unified proxy URL, and offers a live
// connection test. Reads ?template_id= from the query string.

import { Suspense, useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import {
  ArrowLeft,
  Loader2,
  PlugZap,
  Copy,
  Check,
  FlaskConical,
  ShieldCheck,
  ExternalLink,
} from 'lucide-react';
import { getApiUrl } from '@/lib/api';
import MCPConnectionWizard, { TemplateSchema } from '@/src/components/MCPConnectionWizard';

interface Template {
  id: string;
  name: string;
  description: string;
  config_schema?: TemplateSchema & { category?: string };
}

function authHeaders(): Record<string, string> {
  if (typeof window === 'undefined') return {};
  const token = localStorage.getItem('eepy_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function MCPConnectContent() {
  const searchParams = useSearchParams();
  const templateId = searchParams.get('template_id') || 'happyfox';

  const [template, setTemplate] = useState<Template | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [wizardOpen, setWizardOpen] = useState(false);
  const [connected, setConnected] = useState<{ configId: number; proxyUrl: string } | null>(null);
  const [copied, setCopied] = useState(false);

  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ status: string; detail: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setLoadError('');
      try {
        const res = await fetch(`${getApiUrl()}/api/mcp/templates/list`, {
          headers: authHeaders(),
          cache: 'no-store',
        });
        if (!res.ok) throw new Error(`Backend returned ${res.status}`);
        const data = await res.json();
        const list: Template[] = Array.isArray(data) ? data : data.templates || [];
        if (!cancelled) setTemplate(list.find((t) => t.id === templateId) || list[0] || null);
      } catch (err) {
        if (!cancelled) {
          setLoadError('Could not reach the MCP backend to load the template.');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [templateId]);

  const runTest = useCallback(async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await fetch(`${getApiUrl()}/api/mcp/config/${templateId}/test`, {
        method: 'POST',
        headers: authHeaders(),
      });
      const data = await res.json().catch(() => ({}));
      setTestResult({ status: data.status || (res.ok ? 'ok' : 'failed'), detail: data.detail || `HTTP ${res.status}` });
    } catch {
      setTestResult({ status: 'failed', detail: 'Could not reach the backend.' });
    } finally {
      setTesting(false);
    }
  }, [templateId]);

  const proxyBase = connected?.proxyUrl || `/api/mcp/proxy/${templateId}`;
  const copyProxyUrl = () => {
    const full = typeof window !== 'undefined' ? `${window.location.origin}${proxyBase}` : proxyBase;
    navigator.clipboard.writeText(full).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <div className="min-h-screen bg-void text-white p-8">
      <div className="max-w-3xl mx-auto">
        <Link href="/mcp/library" className="inline-flex items-center gap-2 text-gray-400 hover:text-white mb-6 text-sm">
          <ArrowLeft size={16} /> Back to library
        </Link>

        {loading ? (
          <div className="flex items-center justify-center py-24 text-gray-500">
            <Loader2 className="animate-spin mr-2" size={20} /> Loading template...
          </div>
        ) : loadError || !template ? (
          <div className="py-20 text-center text-gray-500">{loadError || 'Template not found.'}</div>
        ) : (
          <>
            <header className="mb-8">
              <h1 className="text-3xl font-bold flex items-center gap-3">
                <PlugZap className="text-eepy-lavender" size={30} />
                Connect {template.name}
              </h1>
              <p className="text-gray-400 mt-2 text-sm leading-relaxed max-w-2xl">{template.description}</p>
            </header>

            {!connected ? (
              <div className="p-8 bg-void-surface border border-void-border rounded-xl text-center">
                <ShieldCheck className="text-eepy-mint mx-auto mb-4" size={40} />
                <p className="text-gray-300 mb-6">
                  Enter your credentials to establish an encrypted connection. Eepy stores them encrypted and routes
                  your agent&apos;s calls through a single secure proxy.
                </p>
                <button
                  onClick={() => {
                    setWizardOpen(true);
                    setTestResult(null);
                  }}
                  className="px-6 py-3 bg-eepy-lavender text-void font-bold rounded-lg hover:bg-opacity-90 transition-all"
                >
                  {connected ? 'Reconnect' : 'Connect Integration'}
                </button>
              </div>
            ) : (
              <div className="space-y-6">
                <div className="p-6 bg-void-surface border border-eepy-mint rounded-xl">
                  <h2 className="text-lg font-bold flex items-center gap-2 mb-2">
                    <Check className="text-eepy-mint" size={20} /> Connected
                  </h2>
                  <p className="text-gray-400 text-sm">
                    Your <span className="text-white">{template.name}</span> credentials are encrypted and active
                    (config id {connected.configId}).
                  </p>
                </div>

                <div className="p-6 bg-void-surface border border-void-border rounded-xl">
                  <h3 className="text-sm font-bold text-eepy-peach mb-3 flex items-center gap-2">
                    <ExternalLink size={16} /> Unified MCP Proxy URL
                  </h3>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 text-sm bg-void border border-void-border rounded-lg px-4 py-3 text-eepy-mint break-all">
                      {typeof window !== 'undefined' ? `${window.location.origin}${proxyBase}` : proxyBase}
                    </code>
                    <button
                      onClick={copyProxyUrl}
                      className="p-3 border border-void-border rounded-lg hover:bg-void-border transition-colors"
                      title="Copy URL"
                    >
                      {copied ? <Check size={18} className="text-eepy-mint" /> : <Copy size={18} />}
                    </button>
                  </div>
                  <p className="text-xs text-gray-600 mt-3">
                    Point your agent&apos;s MCP client at this endpoint and authenticate with your Eepy Bearer token.
                    Individual tools live at <code className="text-gray-400">{'{proxy}'}/{template.id}/{'{tool}'}</code>.
                  </p>
                </div>

                <div className="p-6 bg-void-surface border border-void-border rounded-xl">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-sm font-bold flex items-center gap-2">
                      <FlaskConical size={16} className="text-eepy-lavender" /> Connection Test
                    </h3>
                    <button
                      onClick={runTest}
                      disabled={testing}
                      className="px-4 py-2 bg-void border border-void-border rounded-lg text-sm hover:bg-void-border transition-colors disabled:opacity-50"
                    >
                      {testing ? 'Testing...' : 'Run Live Test'}
                    </button>
                  </div>
                  {testResult && (
                    <p
                      className={`text-sm p-3 rounded border-l-2 ${
                        testResult.status === 'ok'
                          ? 'text-eepy-mint border-eepy-mint bg-void'
                          : 'text-red-400 border-red-500 bg-void'
                      }`}
                    >
                      {testResult.detail}
                    </p>
                  )}
                </div>

                <button
                  onClick={() => {
                    setConnected(null);
                    setTestResult(null);
                    setWizardOpen(true);
                  }}
                  className="text-sm text-gray-500 hover:text-white underline"
                >
                  Change credentials
                </button>
              </div>
            )}
          </>
        )}
      </div>

      {wizardOpen && template && (
        <MCPConnectionWizard
          templateId={template.id}
          templateName={template.name}
          schema={template.config_schema}
          onSuccess={(result) => {
            setConnected(result);
            setWizardOpen(false);
          }}
          onClose={() => setWizardOpen(false)}
        />
      )}
    </div>
  );
}

export default function MCPConnectPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-void flex items-center justify-center text-gray-500">Loading...</div>
      }
    >
      <MCPConnectContent />
    </Suspense>
  );
}
