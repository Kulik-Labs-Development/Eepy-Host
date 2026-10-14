"use client";

import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { Settings, Lock, PlugZap, Save } from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { getApiUrl } from '@/lib/api';

type Backend = 'portainer' | 'arcane';

interface EnvOption {
  id: string;
  name: string | null;
}

type Status = { kind: 'ok' | 'err'; text: string } | null;

export default function SettingsPage() {
  const { user } = useAuth();
  const isSuper = user?.role === 'superuser';

  const [loaded, setLoaded] = useState(false);
  const [backend, setBackend] = useState<Backend>('portainer');
  const [portainerUrl, setPortainerUrl] = useState('');
  const [portainerKey, setPortainerKey] = useState('');
  const [arcaneUrl, setArcaneUrl] = useState('');
  const [arcaneKey, setArcaneKey] = useState('');
  const [tlsVerify, setTlsVerify] = useState(true);
  const [environmentId, setEnvironmentId] = useState('');
  const [envOptions, setEnvOptions] = useState<EnvOption[]>([]);
  const [keySet, setKeySet] = useState({ portainer: false, arcane: false });
  const [status, setStatus] = useState<Status>(null);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${getApiUrl()}/superuser/system-settings`, {
        headers: { Authorization: `Bearer ${localStorage.getItem('eepy_token')}` },
      });
      if (!res.ok) {
        throw new Error(`Settings request failed (HTTP ${res.status})`);
      }
      const json = await res.json();
      // The password fields start EMPTY (they are never returned); the
      // placeholder below says whether a key is already stored.
      setBackend(json.backend ?? 'portainer');
      setPortainerUrl(json.portainer_url ?? '');
      setPortainerKey('');
      setArcaneUrl(json.arcane_url ?? '');
      setArcaneKey('');
      setTlsVerify(json.portainer_tls_verify !== false);
      setEnvironmentId(json.environment_id ?? '');
      setKeySet({
        portainer: Boolean(json.portainer_api_key_set),
        arcane: Boolean(json.arcane_api_key_set),
      });
    } catch (err) {
      setStatus({ kind: 'err', text: err instanceof Error ? err.message : String(err) });
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    if (!isSuper) return;
    void load();
  }, [isSuper, load]);

  const runTest = useCallback(async () => {
    setTesting(true);
    try {
      const res = await fetch(`${getApiUrl()}/superuser/system-settings/test`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('eepy_token')}`,
        },
        // Current form values as-typed (environment_id is irrelevant here:
        // this call both tests the connection and lists the environments).
        body: JSON.stringify({
          backend,
          portainer_url: portainerUrl,
          portainer_api_key: portainerKey,
          portainer_tls_verify: tlsVerify,
          arcane_url: arcaneUrl,
          arcane_api_key: arcaneKey,
        }),
      });
      const body = await res.json().catch(() => null);
      if (body?.ok) {
        const list: EnvOption[] = Array.isArray(body.environments)
          ? body.environments.map((e: { id: string | number; name: string | null }) => ({
              id: String(e.id),
              name: e.name,
            }))
          : [];
        setEnvOptions(list);
        setStatus({ kind: 'ok', text: `Connection OK — ${list.length} environments` });
      } else {
        setStatus({
          kind: 'err',
          text: typeof body?.detail === 'string' ? body.detail : `Test failed (HTTP ${res.status})`,
        });
      }
    } catch (err) {
      setStatus({ kind: 'err', text: err instanceof Error ? err.message : String(err) });
    } finally {
      setTesting(false);
    }
  }, [backend, portainerUrl, portainerKey, tlsVerify, arcaneUrl, arcaneKey]);

  const save = useCallback(async () => {
    setSaving(true);
    try {
      const res = await fetch(`${getApiUrl()}/superuser/system-settings`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('eepy_token')}`,
        },
        body: JSON.stringify({
          backend,
          portainer_url: portainerUrl,
          portainer_api_key: portainerKey,
          portainer_tls_verify: tlsVerify,
          arcane_url: arcaneUrl,
          arcane_api_key: arcaneKey,
          environment_id: environmentId || null,
        }),
      });
      const body = await res.json().catch(() => null);
      if (res.status === 200) {
        setStatus({ kind: 'ok', text: 'Saved.' });
        // The keys are now the stored values: clear the typed copies and
        // re-GET to refresh the *_set placeholders.
        setPortainerKey('');
        setArcaneKey('');
        await load();
      } else {
        setStatus({
          kind: 'err',
          text: typeof body?.detail === 'string' ? body.detail : `Save failed (HTTP ${res.status})`,
        });
      }
    } catch (err) {
      setStatus({ kind: 'err', text: err instanceof Error ? err.message : String(err) });
    } finally {
      setSaving(false);
    }
  }, [backend, portainerUrl, portainerKey, tlsVerify, arcaneUrl, arcaneKey, environmentId, load]);

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
            The system settings console is only visible to organization superusers.
          </p>
        </div>
      </div>
    );
  }

  const isPortainer = backend === 'portainer';

  return (
    <div className="space-y-8 max-w-3xl mx-auto">
      <header className="mb-8">
        <h2 className="font-pixel font-bold text-3xl text-ink text-px-sm">System Settings</h2>
        <p className="text-ink-dim font-body text-sm mt-1">Fine-tune your cozy infrastructure.</p>
      </header>

      <div className="panel pixel-caps p-4 sm:p-6 md:p-8 space-y-6 [--cap:theme('colors.eepy.lilac')]">
        <div className="flex items-center gap-3 mb-2">
          <Settings size={20} className="text-eepy-lilac" />
          <h3 className="font-pixel font-bold text-lg text-ink">System data source</h3>
        </div>
        <p className="text-xs font-body text-ink-dim">
          System Usage reads its container stats from the connection configured here. Portainer is
          the current default; Arcane is supported for the planned move.
        </p>

        {/* Backend picker: Portainer / Arcane (pixel toggles). */}
        <div className="space-y-2">
          <span className="label-pixel">Backend</span>
          <div className="flex gap-2">
            {(['portainer', 'arcane'] as const).map((b) => (
              <button
                key={b}
                type="button"
                onClick={() => setBackend(b)}
                className={`px-4 py-2 border-2 font-pixel text-xs uppercase tracking-wide transition-colors ${
                  backend === b
                    ? 'bg-eepy-blush border-eepy-pink text-night-deep shadow-pixel-sm'
                    : 'border-night-border text-ink-soft hover:text-ink hover:bg-night-raise'
                }`}
              >
                {b}
              </button>
            ))}
          </div>
        </div>

        {isPortainer ? (
          <div className="space-y-4">
            <div className="space-y-1.5">
              <label className="label-pixel" htmlFor="portainer-url">Portainer URL</label>
              <input
                id="portainer-url"
                type="text"
                value={portainerUrl}
                onChange={(e) => setPortainerUrl(e.target.value)}
                placeholder="https://portainer.example.com"
                className="input-pixel"
              />
            </div>
            <div className="space-y-1.5">
              <label className="label-pixel" htmlFor="portainer-key">Portainer API key</label>
              <input
                id="portainer-key"
                type="password"
                value={portainerKey}
                onChange={(e) => setPortainerKey(e.target.value)}
                placeholder={keySet.portainer ? '••••' : 'not set'}
                className="input-pixel"
                autoComplete="new-password"
              />
              <p className="text-[11px] font-body text-ink-faint">blank = keep current</p>
            </div>
            <label className="flex items-center gap-2 text-sm font-body text-ink-soft cursor-pointer">
              <input
                type="checkbox"
                checked={tlsVerify}
                onChange={(e) => setTlsVerify(e.target.checked)}
                className="h-4 w-4 accent-eepy-blush"
              />
              Verify TLS certificates
            </label>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="space-y-1.5">
              <label className="label-pixel" htmlFor="arcane-url">Arcane URL</label>
              <input
                id="arcane-url"
                type="text"
                value={arcaneUrl}
                onChange={(e) => setArcaneUrl(e.target.value)}
                placeholder="https://arcane.example.com"
                className="input-pixel"
              />
            </div>
            <div className="space-y-1.5">
              <label className="label-pixel" htmlFor="arcane-key">Arcane API key</label>
              <input
                id="arcane-key"
                type="password"
                value={arcaneKey}
                onChange={(e) => setArcaneKey(e.target.value)}
                placeholder={keySet.arcane ? '••••' : 'not set'}
                className="input-pixel"
                autoComplete="new-password"
              />
              <p className="text-[11px] font-body text-ink-faint">blank = keep current</p>
            </div>
          </div>
        )}

        {/* Environment selector + its description, side by side. */}
        <div className="space-y-1.5">
          <span className="label-pixel">Environment</span>
          <div className="flex flex-col sm:flex-row gap-3 items-start">
            <select
              value={environmentId}
              onChange={(e) => setEnvironmentId(e.target.value)}
              className="input-pixel sm:w-64 shrink-0"
            >
              <option value="">Auto (single environment)</option>
              {envOptions.map((e) => (
                <option key={e.id} value={e.id}>
                  {`${e.name || e.id} (id ${e.id})`}
                </option>
              ))}
            </select>
            <p className="text-xs font-body text-ink-dim">
              Environment — which environment&apos;s containers appear on the System Usage page.
              Pick the one that runs eepy-backend (on Arcane the local environment is usually id 0).
            </p>
          </div>
          {envOptions.length === 0 && (
            <p className="text-[11px] font-body text-ink-faint">
              No environments listed yet — run &ldquo;Test connection&rdquo; to fill the options.
            </p>
          )}
        </div>

        {/* Status line (test result / save result / error). */}
        {status && (
          <div
            className={`card px-3 py-2 text-sm font-body ${
              status.kind === 'ok' ? 'text-eepy-sage' : 'text-eepy-ember border-eepy-ember/50'
            }`}
          >
            {status.text}
          </div>
        )}

        <div className="flex flex-wrap gap-3 pt-2">
          <button
            type="button"
            onClick={() => void runTest()}
            disabled={testing || !loaded}
            className="btn btn-ghost"
          >
            <PlugZap size={15} /> {testing ? 'Testing…' : 'Test connection'}
          </button>
          <button
            type="button"
            onClick={() => void save()}
            disabled={saving || !loaded}
            className="btn btn-blush"
          >
            <Save size={15} /> {saving ? 'Saving…' : 'Save'}
          </button>
        </div>

        <p className="text-[11px] font-body text-ink-faint">
          API keys are stored encrypted and never returned by the API — a blank key field keeps the
          current one. <Link href="/dashboard/system-usage" className="underline hover:text-ink-soft">
            See the System Usage page
          </Link>.
        </p>
      </div>
    </div>
  );
}
