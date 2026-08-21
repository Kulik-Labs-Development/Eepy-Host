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

  // The URL the user pastes into Open WebUI - covers ALL of Eepy. This is the
  // BASE url (without /openapi.json): Open WebUI appends "/openapi.json" to
  // whatever is pasted, so the spec it fetches is <base>/openapi.json.
  // (The backend also serves the spec at <base>/openapi.json/openapi.json, so
  // a spec URL pasted from older instructions still resolves.)
  const specUrl = `${getApiUrl()}/api/mcp`;

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
    <div className="fixed inset-0 bg-night-deep/80 flex items-end sm:items-center justify-center sm:p-4 z-[999] backdrop-blur-sm">
      <div className="panel pixel-caps border-eepy-lilac/60 p-4 sm:p-6 max-w-2xl w-full relative shadow-pixel-lg max-h-[92vh] overflow-y-auto [--cap:theme('colors.eepy.lilac')]">
        <header className="flex items-center justify-between mb-5 pb-4 border-b-2 border-night-line gap-3">
          <div>
            <h2 className="font-pixel font-bold text-base sm:text-lg flex items-center gap-2 text-ink">
              <Plug className="text-eepy-sage" size={18} /> Connect Open WebUI to Eepy
            </h2>
            <p className="text-xs text-ink-dim mt-1.5 font-body">
              One connection. Every Eepy integration - now and in the future.
            </p>
          </div>
          <button onClick={onClose} className="btn-icon shrink-0" aria-label="Close">
            <X size={16} />
          </button>
        </header>

        {error && (
          <p className="text-sm text-eepy-ember mb-4 bg-eepy-ember/10 border-l-4 border-eepy-ember p-3 font-body">{error}</p>
        )}

        {/* Step 1 - generate / show key */}
        <Step title="Create your Eepy API Key" step="1">
          <p className="text-xs text-ink-faint mb-3 leading-relaxed font-body">
            This key covers <span className="text-eepy-sage font-semibold">every integration you have connected</span> - and every
            one you connect later. It only works on Eepy&apos;s MCP routes (never on your account or billing), and
            you can revoke it here at any time.
          </p>

          {newestKey ? (
            <div className="mb-4">
              <div className="flex flex-col sm:flex-row sm:items-center gap-2">
                <span className="text-[13px] font-console text-ink-dim shrink-0 sm:w-auto">Shown once:</span>
                <div className="flex items-center gap-2 min-w-0 flex-1">
                  <code className="well flex-1 min-w-0 text-[15px] px-3 py-2 text-eepy-sage break-all font-console leading-snug">
                    {newestKey.key}
                  </code>
                  <button
                    onClick={() => copy(newestKey.key!, 'newkey')}
                    className="btn-icon shrink-0"
                    title="Copy key"
                  >
                    {copied === 'newkey' ? <Check size={15} className="text-eepy-sage" /> : <Copy size={15} />}
                  </button>
                </div>
              </div>
              <p className="text-xs text-eepy-amber flex items-center gap-1.5 mt-2 font-body">
                <ShieldAlert size={13} /> Copy it now - it is not stored in plain text and cannot be retrieved again.
              </p>
            </div>
          ) : (
            <button
              onClick={generate}
              disabled={generating || (loading && keys.length > 0)}
              className="btn btn-blush w-full py-2.5 text-xs flex items-center justify-center gap-2"
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
              <p className="text-[13px] font-console text-ink-dim">Your Eepy API keys</p>
              {keys.map((k) => (
                <div
                  key={k.id}
                  className="card flex items-center justify-between px-3 py-2 gap-3"
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <span
                      className={`led ${k.is_active ? 'bg-eepy-sage' : 'bg-ink-dim'}`}
                      title={k.is_active ? 'Active' : 'Revoked'}
                    />
                    <code className="text-[15px] text-ink-faint font-console truncate">
                      {k.key_prefix}
                      <span className="text-ink-dim">…</span>
                    </code>
                    <span className="text-[11px] font-body text-ink-dim">{k.name}</span>
                  </div>
                  {k.is_active ? (
                    <button
                      onClick={() => revoke(k.id)}
                      className="text-[11px] font-body font-semibold text-ink-dim hover:text-eepy-ember transition-colors flex items-center gap-1 shrink-0"
                      title="Revoke key"
                    >
                      <Trash2 size={13} /> Revoke
                    </button>
                  ) : (
                    <span className="text-[11px] font-body text-ink-dim shrink-0">revoked</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </Step>

        {/* Step 2 - spec URL */}
        <Step title="Copy the Eepy OpenAPI URL" step="2">
          <div className="flex flex-col sm:flex-row sm:items-center gap-2 min-w-0">
            <span className="text-[13px] font-console text-ink-dim shrink-0">OpenAPI:</span>
            <div className="flex items-center gap-2 min-w-0 flex-1">
              <code className="well flex-1 min-w-0 text-[15px] px-3 py-2 text-eepy-lilac break-all font-console leading-snug">
                {specUrl}
              </code>
              <button
                onClick={() => copy(specUrl, 'spec')}
                className="btn-icon shrink-0"
                title="Copy spec URL"
              >
                {copied === 'spec' ? <Check size={15} className="text-eepy-sage" /> : <Copy size={15} />}
              </button>
            </div>
          </div>
        </Step>

        {/* Step 3 - instructions */}
        <Step title="In Open WebUI, add the Tool Server" step="3">
          <ol className="text-[13px] text-ink-soft space-y-2 list-decimal list-inside leading-relaxed font-body">
            <li>
              Go to <span className="text-ink font-bold">Settings → Tools</span> (or the Tools page) and choose{' '}
              <span className="text-ink font-bold">Add New → Tool Server</span> (external / OpenAPI).
            </li>
            <li>
              Set the <span className="text-ink font-bold">URL</span> to the Eepy URL from step 2, exactly as copied.
              Open WebUI appends <code className="font-console text-[12px] text-eepy-lilac">/openapi.json</code> itself,
              fetches the spec, and lists every Eepy tool automatically.
            </li>
            <li>
              For <span className="text-ink font-bold">authentication</span>, select <span className="text-eepy-sage font-bold">Bearer</span>{' '}
              and paste the Eepy API Key from step 1 as the token.
            </li>
            <li>
              Save. Done - one connection for all of Eepy. When you connect new integrations in the dashboard
              (Slack, Notion, …) their tools show up here automatically. No re-import, no second connection.
            </li>
          </ol>
          <p className="text-[11px] text-ink-dim mt-3 leading-relaxed font-body">
            Security note: the key only authenticates MCP tool calls for your account - it cannot access your Eepy
            profile, billing, or other areas - and every tool call still requires that you have that integration
            connected. Revoke the key here at any time to cut access instantly.
          </p>
        </Step>
      </div>
    </div>
  );
}

function Step({ title, step, children }: { title: string; step: string; children: React.ReactNode }) {
  return (
    <div className="mb-6">
      <h3 className="font-pixel font-bold text-sm mb-3 flex items-center gap-2.5 text-ink">
        <span className="well w-6 h-6 inline-flex items-center justify-center font-pixel text-[12px] text-eepy-blush shrink-0">
          {step}
        </span>
        {title}
      </h3>
      {children}
    </div>
  );
}
