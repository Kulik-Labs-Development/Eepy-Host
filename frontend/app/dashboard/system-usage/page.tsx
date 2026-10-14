'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Activity, AlertTriangle, Lock, RefreshCw, Server, Users } from 'lucide-react';
import Link from 'next/link';
import { useAuth } from '@/context/AuthContext';
import { getApiUrl } from '@/lib/api';

interface EnvInfo {
  id: number;
  name: string;
}

interface RamStats {
  usage_bytes: number;
  working_set_bytes: number;
  limit_bytes: number;
}

interface NetStats {
  rx_bytes: number;
  tx_bytes: number;
}

interface UsageRow {
  name: string;
  id: string | null;
  state: string;
  status: string;
  created: number | null;
  cpu_percent: number | null;
  ram: RamStats | null;
  net: NetStats | null;
  owner?: string;
  template?: string;
}

interface UsageData {
  generated_at: number;
  environment: EnvInfo;
  environments: EnvInfo[];
  platform: UsageRow[];
  sidecars: UsageRow[];
}

interface Rates {
  rx: number | null;
  tx: number | null;
}

// Config-level prompts (rendered instead of the tables): the data source is
// now configured in System Settings, not on this page.
type Prompt =
  | { kind: 'not_configured' }
  | { kind: 'multiple'; envs: { id: string | number; name: string | null }[] };

const POLL_MS = 10_000;

function fmtBytes(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

function fmtRate(r: number | null): string {
  if (r === null || !Number.isFinite(r)) return '—';
  if (r < 1024) return `${Math.round(r)} B/s`;
  if (r < 1024 ** 2) return `${(r / 1024).toFixed(1)} KB/s`;
  return `${(r / 1024 ** 2).toFixed(2)} MB/s`;
}

function fmtUptime(created: number | null): string {
  if (!created) return '—';
  const secs = Math.max(0, Math.floor(Date.now() / 1000 - created));
  const d = Math.floor(secs / 86400);
  const h = Math.floor((secs % 86400) / 3600);
  const m = Math.floor((secs % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function rowKey(row: UsageRow): string {
  return row.id ?? row.name;
}

function statePill(row: UsageRow) {
  const s = (row.state || '').toLowerCase();
  const cls =
    s === 'running'
      ? 'text-eepy-sage border-eepy-sage/50'
      : s === 'gone'
        ? 'text-ink-faint border-night-border'
        : 'text-eepy-ember border-eepy-ember/50';
  return (
    <span className={`inline-block px-2 py-0.5 border-2 font-pixel text-[10px] uppercase tracking-wide ${cls}`}>
      {s || 'unknown'}
    </span>
  );
}

export default function SystemUsagePage() {
  const { user } = useAuth();
  const isSuper = user?.role === 'superuser';

  const [data, setData] = useState<UsageData | null>(null);
  const [rates, setRates] = useState<Map<string, Rates>>(new Map());
  const [prompt, setPrompt] = useState<Prompt | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const inFlight = useRef(false);
  const prevRef = useRef<Map<string, { rx: number; tx: number; t: number }>>(new Map());

  const load = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    try {
      const res = await fetch(`${getApiUrl()}/superuser/system-usage`, {
        headers: { Authorization: `Bearer ${localStorage.getItem('eepy_token')}` },
      });

      if (res.status === 409) {
        // More than one environment visible to the token: the environment is
        // pinned in System Settings now, so prompt there (with the list).
        const body = await res.json().catch(() => null);
        const detail = body?.detail;
        if (detail?.error === 'multiple_environments') {
          const list = Array.isArray(detail.environments) ? detail.environments : [];
          setPrompt({ kind: 'multiple', envs: list });
          return;
        }
        throw new Error(
          typeof detail === 'string' ? detail : `System usage request failed (HTTP ${res.status})`,
        );
      }

      if (!res.ok) {
        const body = await res.json().catch(() => null);
        const detail = body?.detail;
        if (
          res.status === 400 &&
          detail &&
          typeof detail === 'object' &&
          detail.error === 'not_configured'
        ) {
          setPrompt({ kind: 'not_configured' });
          return;
        }
        throw new Error(
          typeof detail === 'string' ? detail : `System usage request failed (HTTP ${res.status})`,
        );
      }

      const json: UsageData = await res.json();
      setPrompt(null);

      // Bandwidth = the delta between polls; first paint = average since the
      // container started (created epoch).
      const now = Date.now();
      const prev = prevRef.current;
      const next = new Map<string, { rx: number; tx: number; t: number }>();
      const newRates = new Map<string, Rates>();
      for (const row of [...json.platform, ...json.sidecars]) {
        if (!row.net) continue;
        const key = rowKey(row);
        const p = prev.get(key);
        let rx: number | null = null;
        let tx: number | null = null;
        if (p) {
          const dt = (now - p.t) / 1000;
          if (dt > 0 && row.net.rx_bytes >= p.rx && row.net.tx_bytes >= p.tx) {
            rx = (row.net.rx_bytes - p.rx) / dt;
            tx = (row.net.tx_bytes - p.tx) / dt;
          }
        } else if (row.created) {
          const dt = (now - row.created * 1000) / 1000;
          if (dt > 0) {
            rx = row.net.rx_bytes / dt;
            tx = row.net.tx_bytes / dt;
          }
        }
        newRates.set(key, { rx, tx });
        next.set(key, { rx: row.net.rx_bytes, tx: row.net.tx_bytes, t: now });
      }
      prevRef.current = next;
      setRates(newRates);
      setData(json);
      setError(null);
    } catch (err) {
      // Keep the last good data visible; the interval retries.
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }, []);

  // 10s poll while a superuser is viewing.
  useEffect(() => {
    if (!isSuper) return;
    void load();
    const id = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(id);
  }, [isSuper, load]);

  if (!user) {
    return (
      <div className="min-h-[50vh] flex items-center justify-center">
        <p className="font-pixel font-bold text-ink-faint text-px-sm">Loading cozy space...</p>
      </div>
    );
  }

  if (!isSuper) {
    return (
      <div className="max-w-xl mx-auto mt-16">
        <div className="panel pixel-caps p-8 text-center space-y-4">
          <Lock size={28} className="text-eepy-ember mx-auto" />
          <h2 className="font-pixel font-bold text-xl text-ink">Superuser access required</h2>
          <p className="text-ink-dim font-body text-sm">
            The system usage console is only visible to organization superusers.
          </p>
        </div>
      </div>
    );
  }

  const rateFor = (row: UsageRow): Rates => rates.get(rowKey(row)) ?? { rx: null, tx: null };

  const renderRow = (row: UsageRow, showMeta: boolean) => {
    const r = rateFor(row);
    return (
      <tr key={rowKey(row)} className="hover:bg-eepy-blush/5 transition-colors">
        <td className="px-4 py-3 font-pixel text-[13px] tracking-wide text-ink break-all">{row.name}</td>
        {showMeta && (
          <>
            <td className="px-4 py-3 text-ink-soft font-body text-sm">{row.owner ?? '—'}</td>
            <td className="px-4 py-3 text-ink-soft font-body text-sm">{row.template ?? '—'}</td>
          </>
        )}
        <td className="px-4 py-3">{statePill(row)}</td>
        <td className="px-4 py-3 text-right font-console text-[15px] text-eepy-sage">
          {row.cpu_percent === null ? '—' : `${row.cpu_percent.toFixed(1)}%`}
        </td>
        <td className="px-4 py-3 text-right font-console text-[14px] text-ink-soft whitespace-nowrap">
          {row.ram ? (
            <>
              {fmtBytes(row.ram.working_set_bytes)}
              {row.ram.limit_bytes > 0 ? (
                <span className="text-ink-faint"> / {fmtBytes(row.ram.limit_bytes)}</span>
              ) : null}
            </>
          ) : (
            '—'
          )}
        </td>
        <td className="px-4 py-3 text-right font-console text-[14px] text-ink-soft whitespace-nowrap">
          {fmtRate(r.rx)}
        </td>
        <td className="px-4 py-3 text-right font-console text-[14px] text-ink-soft whitespace-nowrap">
          {fmtRate(r.tx)}
        </td>
        <td className="px-4 py-3 text-right font-console text-[14px] text-ink-faint whitespace-nowrap">
          {fmtUptime(row.created)}
        </td>
      </tr>
    );
  };

  const table = (rows: UsageRow[], showMeta: boolean, empty: string) => (
    <div className="overflow-x-auto">
      <table className="w-full text-left font-body text-sm">
        <thead className="bg-night-deep/40 text-ink-dim uppercase text-[11px] font-pixel tracking-widest">
          <tr>
            <th className="px-4 py-3 font-bold">Container</th>
            {showMeta && (
              <>
                <th className="px-4 py-3 font-bold">Owner</th>
                <th className="px-4 py-3 font-bold">Template</th>
              </>
            )}
            <th className="px-4 py-3 font-bold">State</th>
            <th className="px-4 py-3 font-bold text-right">CPU</th>
            <th className="px-4 py-3 font-bold text-right">RAM (working / limit)</th>
            <th className="px-4 py-3 font-bold text-right">RX</th>
            <th className="px-4 py-3 font-bold text-right">TX</th>
            <th className="px-4 py-3 font-bold text-right">Uptime</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-night-line">
          {rows.length === 0 ? (
            <tr>
              <td colSpan={showMeta ? 9 : 7} className="px-4 py-8 text-center text-ink-dim font-body text-sm italic">
                {empty}
              </td>
            </tr>
          ) : (
            rows.map((row) => renderRow(row, showMeta))
          )}
        </tbody>
      </table>
    </div>
  );

  return (
    <div className="space-y-8 max-w-6xl mx-auto">
      <header className="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4">
        <div>
          <h2 className="font-pixel font-bold text-2xl sm:text-3xl text-ink text-px-sm">System Usage</h2>
          <p className="text-ink-dim font-body text-sm mt-1">
            {data?.environment?.name ? `Environment: ${data.environment.name} · ` : ''}
            CPU / RAM / bandwidth from your system data source.
          </p>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <span className="chip chip-lilac">
            <Activity size={14} className="animate-led shrink-0" />
            10s poll
          </span>
          <button onClick={() => void load()} disabled={busy} className="btn-icon" title="Refresh now">
            {busy ? <RefreshCw size={18} className="animate-spin" /> : <RefreshCw size={18} />}
          </button>
        </div>
      </header>

      {prompt &&
        (prompt.kind === 'not_configured' ? (
          <div className="panel pixel-caps p-8 text-center space-y-4 [--cap:theme('colors.eepy.ember')]">
            <AlertTriangle size={28} className="text-eepy-ember mx-auto" />
            <h3 className="font-pixel font-bold text-lg text-ink">No system data source configured</h3>
            <p className="text-ink-dim font-body text-sm max-w-xl mx-auto">
              System Usage reads from the connection in System Settings — connect Portainer or
              Arcane (URL + API key) and pick the environment there.
            </p>
            <Link href="/dashboard/settings" className="btn btn-blush">
              Open System Settings
            </Link>
          </div>
        ) : (
          <div className="panel pixel-caps p-8 space-y-4 [--cap:theme('colors.eepy.ember')]">
            <div className="flex items-center gap-3">
              <AlertTriangle size={24} className="text-eepy-ember shrink-0" />
              <h3 className="font-pixel font-bold text-lg text-ink">Multiple environments visible</h3>
            </div>
            <p className="text-ink-dim font-body text-sm">
              Pick which environment to monitor in System Settings.
            </p>
            <ul className="space-y-1.5">
              {prompt.envs.map((e) => (
                <li
                  key={String(e.id)}
                  className="card px-3 py-2 font-console text-[14px] text-ink-soft"
                >
                  {e.name || `environment ${e.id}`}
                  <span className="text-ink-faint"> (id {e.id})</span>
                </li>
              ))}
            </ul>
            <div>
              <Link href="/dashboard/settings" className="btn btn-blush">
                Open System Settings
              </Link>
            </div>
          </div>
        ))}

      {!prompt && error && (
        <div className="panel pixel-caps p-4 border-eepy-ember/50">
          <p className="text-eepy-ember font-body text-sm flex items-center gap-2">
            <AlertTriangle size={15} className="shrink-0" />
            <span>
              {error}
              {data ? ' — showing the last good data, retrying every 10s.' : ''}
            </span>
            {!data && (
              <button onClick={() => void load()} className="btn btn-ghost px-3 py-1 text-[11px] ml-2">
                Try Again
              </button>
            )}
          </p>
        </div>
      )}

      {!prompt && !data && !error ? (
        <div className="p-12 text-center flex flex-col items-center gap-4">
          <RefreshCw size={32} className="text-eepy-lilac animate-spin" />
          <p className="text-ink-faint font-body text-sm italic">Sampling the environment...</p>
        </div>
      ) : (
        !prompt && data && (
          <>
            <div className="panel overflow-hidden">
              <div className="p-4 sm:p-5 border-b-2 border-night-line bg-night-deep/40">
                <h3 className="font-pixel font-bold text-lg flex items-center gap-2 text-ink">
                  <Server size={18} className="text-eepy-lilac" /> Platform Containers
                </h3>
                <p className="text-ink-dim font-body text-xs mt-1">The always-running eepy-* stack.</p>
              </div>
              {table(data.platform, false, 'No platform containers found (nothing with the eepy- prefix in this environment).')}
            </div>

            <div className="panel overflow-hidden">
              <div className="p-4 sm:p-5 border-b-2 border-night-line bg-night-deep/40">
                <h3 className="font-pixel font-bold text-lg flex items-center gap-2 text-ink">
                  <Users size={18} className="text-eepy-sage" /> Sidecars (all users)
                </h3>
                <p className="text-ink-dim font-body text-xs mt-1">
                  Every spawned MCP sidecar, from the spawn ledger. Rows without a live container show as gone.
                </p>
              </div>
              {table(data.sidecars, true, 'No sidecars in the spawn ledger yet.')}
            </div>

            <p className="text-ink-faint font-body text-xs">
              Bandwidth is the delta between the 10s polls; the first paint shows the average since the
              container started. A &ldquo;gone&rdquo; sidecar row means the ledger has it but the container
              is no longer in the environment.
            </p>
          </>
        )
      )}
    </div>
  );
}

