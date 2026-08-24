'use client';

// Open WebUI setup panel - ONE connection for the entire Eepy tool surface.
// Manages the user-scoped, revocable Eepy Tool API Keys (auth uses a SHA-256
// hash; a Fernet-encrypted copy lets the owner re-view a key later, with
// password re-entry) and walks the user through importing the single OpenAPI
// spec URL into Open WebUI's external "Tool Server" connector.
// Every integration the user has connected - now and in the future - is exposed
// through this one connection; no per-server imports, ever.

import { useCallback, useEffect, useState } from 'react';
import {
  X,
  Copy,
  Check,
  Loader2,
  Plug,
  Trash2,
  ShieldAlert,
  MoreHorizontal,
  Eye,
  Lock,
  Plus,
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
  can_reveal?: boolean;
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
  const [keyName, setKeyName] = useState('Open WebUI');
  const [menuFor, setMenuFor] = useState<number | null>(null);
  const [revealFor, setRevealFor] = useState<ToolKey | null>(null);
  const [revealPassword, setRevealPassword] = useState('');
  const [revealBusy, setRevealBusy] = useState(false);
  const [revealError, setRevealError] = useState('');
  const [revealedKey, setRevealedKey] = useState<string | null>(null);

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

  const activeKeys = keys.filter((k) => k.is_active);

  // ADDS a key - never replaces or revokes existing ones, so one key can live
  // per device/client and each is revoked or removed independently.
  const generate = async () => {
    setGenerating(true);
    setError('');
    try {
      const res = await fetch(`${getApiUrl()}/api/mcp/api-keys`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ name: keyName.trim() || 'Open WebUI' }),
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

  const removeKey = async (keyId: number) => {
    const res = await fetch(`${getApiUrl()}/api/mcp/api-keys/${keyId}?hard=true`, {
      method: 'DELETE',
      headers: authHeaders(),
    });
    if (res.ok) {
      setKeys((prev) => prev.filter((k) => k.id !== keyId));
    } else {
      setError('Failed to remove the key.');
    }
  };

  const closeReveal = () => {
    setRevealFor(null);
    setRevealPassword('');
    setRevealError('');
    setRevealedKey(null);
  };

  const submitReveal = async () => {
    if (!revealFor) return;
    setRevealBusy(true);
    setRevealError('');
    try {
      const res = await fetch(`${getApiUrl()}/api/mcp/api-keys/${revealFor.id}/reveal`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ password: revealPassword }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `Backend returned ${res.status}`);
      setRevealedKey(data.key);
    } catch (err) {
      setRevealError(err instanceof Error ? err.message : String(err));
    } finally {
      setRevealBusy(false);
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
            you can view, revoke, or remove it here at any time.
          </p>

          <label className="label-pixel mb-1.5 block">Key label</label>
          <input
            type="text"
            value={keyName}
            onChange={(e) => setKeyName(e.target.value)}
            maxLength={60}
            placeholder="Open WebUI"
            className="input-pixel w-full mb-4"
          />

          {newestKey && (
            <div className="mb-4">
              <div className="flex flex-col sm:flex-row sm:items-center gap-2">
                <span className="text-[13px] font-console text-ink-dim shrink-0 sm:w-auto">New key:</span>
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
                <ShieldAlert size={13} /> Paste it into Open WebUI now - you can also re-view it any time from the list below (password required).
              </p>
            </div>
          )}

          <button
            onClick={() => generate()}
            disabled={generating || (loading && keys.length > 0)}
            className="btn btn-blush w-full py-2.5 text-xs flex items-center justify-center gap-2"
          >
            {generating ? (
              <>
                <Loader2 size={16} className="animate-spin" /> Adding key...
              </>
            ) : (
              <>
                <Plus size={16} /> Add Eepy API Key
              </>
            )}
          </button>
          {activeKeys.length > 0 ? (
            <p className="text-[11px] text-ink-dim mt-2 font-body">
              Adding a key never replaces your existing ones - each works independently, so you can keep one per
              device or client. Use the ... menu on any key to view, revoke, or remove it.
            </p>
          ) : (
            <p className="text-[11px] text-ink-dim mt-2 font-body">
              Then paste the key into Open WebUI (Settings &rarr; Tools &rarr; your Tool Server entry).
            </p>
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
                    {!k.is_active && <span className="text-[11px] font-body text-ink-dim">revoked</span>}
                  </div>
                  <div className="relative shrink-0">
                    <button
                      onClick={() => setMenuFor(menuFor === k.id ? null : k.id)}
                      className="btn-icon"
                      title="Key options"
                      aria-label={`Options for key ${k.key_prefix}`}
                    >
                      <MoreHorizontal size={15} />
                    </button>
                    {menuFor === k.id && (
                      <>
                        <div className="fixed inset-0 z-40" onClick={() => setMenuFor(null)} />
                        <div className="absolute right-0 top-8 z-50 w-44 card p-1 shadow-pixel">
                          {k.can_reveal && (
                            <button
                              onClick={() => { setMenuFor(null); setRevealFor(k); }}
                              className="w-full text-left text-[11px] font-body font-semibold text-ink-soft hover:bg-night-raise hover:text-ink px-2.5 py-1.5 flex items-center gap-1.5 transition-colors"
                            >
                              <Eye size={13} /> View key
                            </button>
                          )}
                          {k.is_active ? (
                            <button
                              onClick={() => { setMenuFor(null); revoke(k.id); }}
                              className="w-full text-left text-[11px] font-body font-semibold text-eepy-ember hover:bg-eepy-ember/10 px-2.5 py-1.5 flex items-center gap-1.5 transition-colors"
                            >
                              <Trash2 size={13} /> Revoke
                            </button>
                          ) : (
                            <button
                              onClick={() => { setMenuFor(null); removeKey(k.id); }}
                              className="w-full text-left text-[11px] font-body font-semibold text-eepy-ember hover:bg-eepy-ember/10 px-2.5 py-1.5 flex items-center gap-1.5 transition-colors"
                            >
                              <Trash2 size={13} /> Remove entry
                            </button>
                          )}
                        </div>
                      </>
                    )}
                  </div>
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

      {revealFor && (
        <div className="fixed inset-0 bg-night-deep/80 flex items-center justify-center p-4 z-[1000]">
          <div className="panel pixel-caps border-eepy-blush/60 p-4 sm:p-5 max-w-sm w-full shadow-pixel-lg [--cap:theme('colors.eepy.blush')]">
            <header className="flex items-center justify-between gap-3 mb-4 pb-3 border-b-2 border-night-line">
              <h3 className="font-pixel font-bold text-sm flex items-center gap-2 text-ink">
                <Lock className="text-eepy-blush" size={15} /> Re-enter your password
              </h3>
              <button onClick={closeReveal} className="btn-icon shrink-0" aria-label="Close">
                <X size={16} />
              </button>
            </header>
            <p className="text-xs text-ink-faint mb-3 font-body leading-relaxed">
              Required to view the <span className="text-ink-soft font-semibold">{revealFor.name}</span> key
              ({revealFor.key_prefix}…).
            </p>
            {revealedKey ? (
              <div>
                <div className="flex items-center gap-2">
                  <code className="well flex-1 min-w-0 text-[14px] px-3 py-2 text-eepy-sage break-all font-console leading-snug">
                    {revealedKey}
                  </code>
                  <button
                    onClick={() => copy(revealedKey, 'revealed')}
                    className="btn-icon shrink-0"
                    title="Copy key"
                  >
                    {copied === 'revealed' ? <Check size={15} className="text-eepy-sage" /> : <Copy size={15} />}
                  </button>
                </div>
                <p className="text-[11px] text-ink-dim mt-3 font-body leading-relaxed">
                  Stored encrypted on the server - you can re-view it any time with your password.
                </p>
              </div>
            ) : (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  submitReveal();
                }}
              >
                <input
                  type="password"
                  value={revealPassword}
                  onChange={(e) => setRevealPassword(e.target.value)}
                  autoFocus
                  placeholder="Account password"
                  className="input-pixel w-full"
                />
                {revealError && (
                  <p className="text-xs text-eepy-ember mt-2 font-body">{revealError}</p>
                )}
                <button
                  type="submit"
                  disabled={revealBusy || !revealPassword}
                  className="btn btn-blush w-full py-2.5 text-xs flex items-center justify-center gap-2 mt-3"
                >
                  {revealBusy ? (
                    <>
                      <Loader2 size={15} className="animate-spin" /> Revealing...
                    </>
                  ) : (
                    <>
                      <Eye size={15} /> View key
                    </>
                  )}
                </button>
              </form>
            )}
          </div>
        </div>
      )}
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
