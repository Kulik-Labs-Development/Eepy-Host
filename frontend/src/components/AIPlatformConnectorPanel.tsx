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
  KeyRound,
  Loader2,
  Bot,
  Trash2,
  ShieldAlert,
  RefreshCw,
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

export default function AIPlatformConnectorPanel({ onClose }: Props) {
  const [keys, setKeys] = useState<ToolKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState<string | null>(null);
  const [keyName, setKeyName] = useState('AI Platform');

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

  const generate = async (replace: boolean) => {
    if (replace && activeKeys.length > 0) {
      const ok = window.confirm(
        `Replace your current Eepy API key?\n\nThe active key (${activeKeys[0].key_prefix}...) stops working immediately - update the key in your AI platform's MCP config.`,
      );
      if (!ok) return;
    }
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
      const stale = replace ? keys.filter((k) => k.is_active).map((k) => k.id) : [];
      setKeys((prev) => [data, ...prev.map((k) => (stale.includes(k.id) ? { ...k, is_active: false } : k))]);
      for (const id of stale) {
        await fetch(`${getApiUrl()}/api/mcp/api-keys/${id}`, { method: 'DELETE', headers: authHeaders() });
      }
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
                <ShieldAlert size={13} /> Pasted into the configs below - copy them before closing this window.
              </p>
            </div>
          )}

          <button
            onClick={() => generate(activeKeys.length > 0)}
            disabled={generating || (loading && keys.length > 0)}
            className="btn btn-sage w-full py-2.5 text-xs flex items-center justify-center gap-2"
          >
            {generating ? (
              <>
                <Loader2 size={16} className="animate-spin" /> {activeKeys.length > 0 ? 'Replacing key...' : 'Creating key...'}
              </>
            ) : activeKeys.length > 0 ? (
              <>
                <RefreshCw size={16} /> Replace Eepy API Key
              </>
            ) : (
              <>
                <KeyRound size={16} /> Create Eepy API Key
              </>
            )}
          </button>
          {activeKeys.length > 0 && (
            <p className="text-[11px] text-ink-dim mt-2 font-body">
              No key yet in the snippets below? Create one here - it is embedded in the configs automatically.
            </p>
          )}

          {keys.length > 0 && (
            <div className="mt-4 space-y-2">
              <p className="text-[13px] font-console text-ink-dim">Your Eepy API keys</p>
              {keys.map((k) => (
                <div key={k.id} className="card flex items-center justify-between px-3 py-2 gap-3">
                  <div className="flex items-center gap-2.5 min-w-0">
                    <span className={`led ${k.is_active ? 'bg-eepy-sage' : 'bg-ink-dim'}`} title={k.is_active ? 'Active' : 'Revoked'} />
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
