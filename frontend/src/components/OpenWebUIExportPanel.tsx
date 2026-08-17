'use client';

// Open WebUI setup panel - ONE connection for the entire Eepy tool surface.
// Generates a user-scoped, revocable Eepy Tool API Key (plaintext shown ONCE;
// only a SHA-256 hash is stored) and walks the user through importing the
// single OpenAPI spec URL into Open WebUI's external "Tool Server" connector.
// Every integration the user has connected - now and in the future - is exposed
// through this one connection; no per-server imports, ever.

import { useCallback, useEffect, useState } from 'react';
import {
  X,
  Copy,
  Check,
  KeyRound,
  Loader2,
  Plug,
  Trash2,
  ShieldAlert,
} from 'lucide-react';
import { getApiUrl } from '@/lib/api';

interface Props {
  onClose: () => void;
}

interface ToolKey {
  id: number;
  name: string;
  key_prefix: string;
  is_active: boolean;
  created_at: string | null;
  last_used_at: string | null;
  key?: string; // only present on the just-created key
}

function authHeaders(): Record<string, string> {
  if (typeof window === 'undefined') return {};
  const token = localStorage.getItem('eepy_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export default function OpenWebUIPanel({ onClose }: Props) {
  const [keys, setKeys] = useState<ToolKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState<string | null>(null);

  // The single spec URL the user pastes into Open WebUI - covers ALL of Eepy.
  const specUrl = `${getApiUrl()}/api/mcp/openapi.json`;

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${getApiUrl()}/api/mcp/api-keys`, { headers: authHeaders(), cache: 'no-store' });
      if (res.ok) {
        const data = await res.json();
        setKeys(Array.isArray(data) ? data : []);
      }
    } catch {
      setError('Could not load your Eepy API keys.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const generate = async () => {
    setGenerating(true);
    setError('');
    try {
      const res = await fetch(`${getApiUrl()}/api/mcp/api-keys`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ name: 'Open WebUI' }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `Backend returned ${res.status}`);
      setKeys((prev) => [data, ...prev]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setGenerating(false);
    }
  };

  const revoke = async (keyId: number) => {
    const res = await fetch(`${getApiUrl()}/api/mcp/api-keys/${keyId}`, {
      method: 'DELETE',
      headers: authHeaders(),
    });
    if (res.ok) {
      setKeys((prev) => prev.map((k) => (k.id === keyId ? { ...k, is_active: false } : k)));
    } else {
      setError('Failed to revoke the key.');
    }
  };

  const copy = (value: string, tag: string) => {
    navigator.clipboard
      .writeText(value)
      .then(() => {
        setCopied(tag);
        setTimeout(() => setCopied(null), 1500);
      })
      .catch(() => {});
  };

  const newestKey = keys.find((k) => k.key);

  return (
    <div className="fixed inset-0 bg-black/75 flex items-center justify-center p-4 z-[999] backdrop-blur-sm">
      <div className="bg-void-surface border-2 border-eepy-lavender rounded-xl p-6 max-w-2xl w-full relative shadow-2xl max-h-[90vh] overflow-y-auto">
        <header className="flex items-center justify-between mb-5 pb-4 border-b border-void-border">
          <div>
            <h2 className="text-lg font-bold flex items-center gap-2">
              <Plug className="text-eepy-mint" size={18} /> Connect Open WebUI to Eepy
            </h2>
            <p className="text-xs text-gray-500 mt-1">
              One connection. Every Eepy integration - now and in the future.
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-white transition-colors">
            <X size={20} />
          </button>
        </header>

        {error && (
          <p className="text-sm text-red-400 mb-4 bg-void border-l-2 border-red-500 p-3 rounded">{error}</p>
        )}

        {/* Step 1 - generate / show key */}
        <Step title="1. Create your Eepy API Key">
          <p className="text-xs text-gray-500 mb-3 leading-relaxed">
            This key covers <span className="text-eepy-mint">every integration you have connected</span> - and every
            one you connect later. It only works on Eepy&apos;s MCP routes (never on your account or billing), and
            you can revoke it here at any time.
          </p>

          {newestKey ? (
            <div className="mb-4">
              <div className="flex items-center gap-2">
                <span className="text-xs font-console text-gray-500 shrink-0">Shown once:</span>
                <code className="flex-1 text-sm bg-void border border-eepy-mint/40 rounded px-3 py-2 text-eepy-mint break-all">
                  {newestKey.key}
                </code>
                <button
                  onClick={() => copy(newestKey.key!, 'newkey')}
                  className="p-2 border border-void-border rounded-lg hover:bg-void-border transition-colors"
                  title="Copy key"
                >
                  {copied === 'newkey' ? <Check size={16} className="text-eepy-mint" /> : <Copy size={16} />}
                </button>
              </div>
              <p className="text-xs text-amber-400/90 flex items-center gap-1 mt-2">
                <ShieldAlert size={13} /> Copy it now - it is not stored in plain text and cannot be retrieved again.
              </p>
            </div>
          ) : (
            <button
              onClick={generate}
              disabled={generating || (loading && keys.length > 0)}
              className="w-full py-2.5 bg-eepy-lavender text-void rounded-lg text-xs font-console font-bold hover:bg-opacity-90 transition-all flex items-center justify-center gap-2 disabled:opacity-50"
            >
              {generating ? (
                <>
                  <Loader2 size={16} className="animate-spin" /> Creating key...
                </>
              ) : (
                <>
                  <KeyRound size={16} /> Create Eepy API Key
                </>
              )}
            </button>
          )}

          {/* Existing keys */}
          {keys.length > 0 && (
            <div className="mt-4 space-y-2">
              <p className="text-xs font-console text-gray-500">Your Eepy API keys</p>
              {keys.map((k) => (
                <div
                  key={k.id}
                  className="flex items-center justify-between bg-void border border-void-border rounded-lg px-3 py-2"
                >
                  <div className="flex items-center gap-2">
                    <span
                      className={`w-2 h-2 rounded-full ${k.is_active ? 'bg-eepy-mint' : 'bg-gray-600'}`}
                      title={k.is_active ? 'Active' : 'Revoked'}
                    />
                    <code className="text-xs text-gray-400 font-console">
                      {k.key_prefix}
                      <span className="text-gray-600">…</span>
                    </code>
                    <span className="text-[10px] font-console text-gray-600">{k.name}</span>
                  </div>
                  {k.is_active ? (
                    <button
                      onClick={() => revoke(k.id)}
                      className="text-[11px] font-console text-gray-500 hover:text-red-400 transition-colors flex items-center gap-1"
                      title="Revoke key"
                    >
                      <Trash2 size={13} /> Revoke
                    </button>
                  ) : (
                    <span className="text-[10px] font-console text-gray-600">revoked</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </Step>

        {/* Step 2 - spec URL */}
        <Step title="2. Copy the Eepy OpenAPI URL">
          <div className="flex items-center gap-2">
            <span className="text-xs font-console text-gray-500 shrink-0">OpenAPI:</span>
            <code className="flex-1 text-xs bg-void border border-void-border rounded px-3 py-2 text-eepy-lavender break-all">
              {specUrl}
            </code>
            <button
              onClick={() => copy(specUrl, 'spec')}
              className="p-2 border border-void-border rounded-lg hover:bg-void-border transition-colors"
              title="Copy spec URL"
            >
              {copied === 'spec' ? <Check size={16} className="text-eepy-mint" /> : <Copy size={16} />}
            </button>
          </div>
        </Step>

        {/* Step 3 - instructions */}
        <Step title="3. In Open WebUI, add the Tool Server">
          <ol className="text-xs text-gray-400 space-y-2 list-decimal list-inside leading-relaxed">
            <li>
              Go to <span className="text-white font-medium">Settings → Tools</span> (or the Tools page) and choose{' '}
              <span className="text-white font-medium">Add New → Tool Server</span> (external / OpenAPI).
            </li>
            <li>
              Set the <span className="text-white font-medium">URL</span> to the Eepy OpenAPI URL from step 2. Open
              WebUI fetches it and lists every Eepy tool automatically.
            </li>
            <li>
              For <span className="text-white font-medium">authentication</span>, select <span className="text-eepy-mint">Bearer</span>{' '}
              and paste the Eepy API Key from step 1 as the token.
            </li>
            <li>
              Save. Done - one connection for all of Eepy. When you connect new integrations in the dashboard
              (Slack, Notion, …) their tools show up here automatically. No re-import, no second connection.
            </li>
          </ol>
          <p className="text-[11px] text-gray-600 mt-3 leading-relaxed">
            Security note: the key only authenticates MCP tool calls for your account - it cannot access your Eepy
            profile, billing, or other areas - and every tool call still requires that you have that integration
            connected. Revoke the key here at any time to cut access instantly.
          </p>
        </Step>
      </div>
    </div>
  );
}

function Step({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-6">
      <h3 className="text-sm font-bold font-console text-eepy-peach mb-3">{title}</h3>
      {children}
    </div>
  );
}
