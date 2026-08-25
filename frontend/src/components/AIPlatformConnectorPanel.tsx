'use client';

// AI Platform connector panel - Eepy's native MCP endpoint.
// Eepy serves a real Model Context Protocol (streamable-HTTP) server at
// /api/mcp/mcp: any MCP client (opencode, Claude Desktop, Cursor, ...) connects
// with the URL + a Tool API Key and gets every integration the user has
// connected - the same one-key-unlocks-everything contract as the Open WebUI
// tool server, but speaking MCP directly (no OpenAPI translation on the
// client side).

import { useCallback, useEffect, useState } from 'react';
import {
  X,
  Copy,
  Check,
  Loader2,
  Bot,
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

export default function AIPlatformConnectorPanel({ onClose }: Props) {
  const [keys, setKeys] = useState<ToolKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState<string | null>(null);
  const [keyName, setKeyName] = useState('AI Platform');
  const [menuFor, setMenuFor] = useState<number | null>(null);
  const [revealFor, setRevealFor] = useState<ToolKey | null>(null);
  const [revealPassword, setRevealPassword] = useState('');
  const [revealBusy, setRevealBusy] = useState(false);
  const [revealError, setRevealError] = useState('');
  const [revealedKey, setRevealedKey] = useState<string | null>(null);

  const mcpUrl = `${getApiUrl()}/api/mcp/mcp`;

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
        body: JSON.stringify({ name: keyName.trim() || 'AI Platform' }),
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

  // The just-created key (plaintext, shown once) is embedded straight into the
  // snippets below; otherwise they carry a placeholder to replace.
  const newestKey = keys.find((k) => k.key);
  const keyInSnippets = newestKey?.key ?? 'eekey_REPLACE_WITH_YOUR_TOOL_KEY';

  const opencodeConfig = JSON.stringify(
    {
      $schema: 'https://opencode.ai/config.json',
      mcp: {
        eepy: {
          type: 'remote',
          url: mcpUrl,
          headers: { Authorization: `Bearer ${keyInSnippets}` },
        },
      },
    },
    null,
    2,
  );

  const claudeDesktopConfig = JSON.stringify(
    {
      mcpServers: {
        eepy: {
          url: mcpUrl,
          headers: { Authorization: `Bearer ${keyInSnippets}` },
        },
      },
    },
    null,
    2,
  );

  const cursorConfig = JSON.stringify(
    {
      mcpServers: {
        eepy: {
          url: mcpUrl,
          headers: { Authorization: `Bearer ${keyInSnippets}` },
        },
      },
    },
    null,
    2,
  );

  const snippets = [
    { id: 'opencode', client: 'opencode', file: 'opencode.json (project root or ~/.config/opencode/)', code: opencodeConfig },
    { id: 'claude', client: 'Claude Desktop', file: 'claude_desktop_config.json', code: claudeDesktopConfig },
    { id: 'cursor', client: 'Cursor', file: '.cursor/mcp.json (project) or ~/.cursor/mcp.json', code: cursorConfig },
  ];

  return (
    <div className="fixed inset-0 bg-night-deep/80 flex items-end sm:items-center justify-center sm:p-4 z-[999] backdrop-blur-sm">
      <div className="panel pixel-caps border-eepy-sage/60 p-4 sm:p-6 max-w-2xl w-full relative shadow-pixel-lg max-h-[92vh] overflow-y-auto [--cap:theme('colors.eepy.sage')]">
        <header className="flex items-center justify-between mb-5 pb-4 border-b-2 border-night-line gap-3">
          <div>
            <h2 className="font-pixel font-bold text-base sm:text-lg flex items-center gap-2 text-ink">
              <Bot className="text-eepy-sage" size={18} /> Connect an AI Platform (MCP)
            </h2>
            <p className="text-xs text-ink-dim mt-1.5 font-body">
              Native Model Context Protocol - opencode, Claude Desktop, Cursor and more.
            </p>
          </div>
          <button onClick={onClose} className="btn-icon shrink-0" aria-label="Close">
            <X size={16} />
          </button>
        </header>

        {error && (
          <p className="text-sm text-eepy-ember mb-4 bg-eepy-ember/10 border-l-4 border-eepy-ember p-3 font-body">{error}</p>
        )}

        {/* Step 1 - key */}
        <Step title="Use your Eepy API Key" step="1">
          <p className="text-xs text-ink-faint mb-3 leading-relaxed font-body">
            The same key you use for Open WebUI works here - it covers{' '}
            <span className="text-eepy-sage font-semibold">every integration you have connected</span>, only on Eepy&apos;s
            MCP routes, and you can revoke it any time.
          </p>

          <label className="label-pixel mb-1.5 block">Key label</label>
          <input
            type="text"
            value={keyName}
            onChange={(e) => setKeyName(e.target.value)}
            maxLength={60}
            placeholder="AI Platform"
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
                <ShieldAlert size={13} /> Pasted into the configs below - copy them before closing this window.
              </p>
            </div>
          )}

          <button
            onClick={() => generate()}
            disabled={generating || (loading && keys.length > 0)}
            className="btn btn-sage w-full py-2.5 text-xs flex items-center justify-center gap-2"
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
              Your key is embedded in the config snippets below automatically.
            </p>
          )}

          {keys.length > 0 && (
            <div className="mt-4 space-y-2">
              <p className="text-[13px] font-console text-ink-dim">Your Eepy API keys</p>
              {keys.map((k) => (
                <div key={k.id} className="card flex items-center justify-between px-3 py-2 gap-3">
                  <div className="flex items-center gap-2.5 min-w-0">
                    <span className={`led ${k.is_active ? 'bg-eepy-sage' : 'bg-ink-dim'}`} title={k.is_active ? 'Active' : 'Revoked'} />
                    <span className="text-[15px] text-ink font-body truncate">{k.name}</span>
                    <code className="text-[11px] text-ink-faint font-console shrink-0">
                      {k.key_prefix}
                      <span className="text-ink-dim">…</span>
                    </code>
                    {!k.is_active && <span className="text-[11px] font-body text-ink-dim">revoked</span>}
                  </div>
                  <div className="relative shrink-0">
                    <button
                      onClick={() => setMenuFor(menuFor === k.id ? null : k.id)}
                      className="btn-icon"
                      title="Key options"
                      aria-label={`Options for key ${k.name}`}
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

        {/* Step 2 - MCP endpoint */}
        <Step title="Copy the Eepy MCP endpoint" step="2">
          <div className="flex flex-col sm:flex-row sm:items-center gap-2 min-w-0">
            <span className="text-[13px] font-console text-ink-dim shrink-0">MCP:</span>
            <div className="flex items-center gap-2 min-w-0 flex-1">
              <code className="well flex-1 min-w-0 text-[15px] px-3 py-2 text-eepy-lilac break-all font-console leading-snug">
                {mcpUrl}
              </code>
              <button onClick={() => copy(mcpUrl, 'url')} className="btn-icon shrink-0" title="Copy MCP URL">
                {copied === 'url' ? <Check size={15} className="text-eepy-sage" /> : <Copy size={15} />}
              </button>
            </div>
          </div>
        </Step>

        {/* Step 3 - client configs */}
        <Step title="Paste the config into your AI platform" step="3">
          <ol className="text-[13px] text-ink-soft space-y-2 list-decimal list-inside leading-relaxed font-body mb-4">
            <li>Create a key above (step 1) - it is embedded in the configs below.</li>
            <li>
              Save the matching snippet to the file shown. Your client picks it up on
              <span className="text-ink font-bold"> restart / reconnect</span> (opencode: quit + relaunch).
            </li>
            <li>Done - every Eepy tool appears in your agent. New integrations you connect later show up automatically.</li>
          </ol>

          <div className="space-y-3">
            {snippets.map((s) => (
              <div key={s.id} className="card p-3">
                <div className="flex items-center justify-between gap-3 mb-2">
                  <div className="min-w-0">
                    <span className="font-pixel font-bold text-xs text-ink">{s.client}</span>
                    <span className="text-[11px] text-ink-dim font-body ml-2 truncate">{s.file}</span>
                  </div>
                  <button
                    onClick={() => copy(s.code, s.id)}
                    className="btn-icon shrink-0"
                    title={`Copy ${s.client} config`}
                  >
                    {copied === s.id ? <Check size={15} className="text-eepy-sage" /> : <Copy size={15} />}
                  </button>
                </div>
                <pre className="well p-3 overflow-x-auto text-[13px] leading-relaxed font-console text-ink-soft whitespace-pre">
                  {s.code}
                </pre>
              </div>
            ))}
          </div>
        </Step>

        <p className="text-[11px] text-ink-dim leading-relaxed font-body">
          Security note: the key only authenticates MCP tool calls for your account - it cannot touch your Eepy
          profile, billing, or other areas - and every tool call still requires that you have that integration
          connected. Revoke it here any time to cut access instantly. Other MCP clients that accept a URL +
          headers work the same way: point them at the endpoint and send{' '}
          <code className="font-console text-eepy-lilac">Authorization: Bearer eekey_…</code>.
        </p>
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
        <span className="well w-6 h-6 inline-flex items-center justify-center font-pixel text-[12px] text-eepy-sage shrink-0">
          {step}
        </span>
        {title}
      </h3>
      {children}
    </div>
  );
}
