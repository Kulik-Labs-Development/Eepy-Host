'use client';

// MCP Library template info page: app icon, title, full description, the
// upstream GitHub repo (author credit — anyone can audit the exact MCP
// server code Eepy runs), and the Connect action. Reached from each
// library card (icon, name, or the info button).

import { use, useEffect, useState } from 'react';
import Image from 'next/image';
import Link from 'next/link';
import {
  ArrowLeft,
  Check,
  ExternalLink,
  Loader2,
  PlugZap,
  ShieldCheck,
} from 'lucide-react';
import { getApiUrl } from '@/lib/api';
import { Template, authHeaders, repoLabel, templateIcon } from '@/lib/mcp';
import MCPConnectionWizard from '@/src/components/MCPConnectionWizard';

interface Props {
  params: Promise<{ templateId: string }>;
}

export default function MCPTemplateInfoPage({ params }: Props) {
  const { templateId } = use(params);

  const [template, setTemplate] = useState<Template | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [connected, setConnected] = useState(false);
  const [wizardOpen, setWizardOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [tplRes, cfgRes] = await Promise.all([
          fetch(`${getApiUrl()}/api/mcp/templates/list`, { headers: authHeaders(), cache: 'no-store' }),
          fetch(`${getApiUrl()}/api/mcp/config/list`, { headers: authHeaders(), cache: 'no-store' }),
        ]);
        if (cancelled) return;
        if (tplRes.status === 401) {
          setError('Session expired. Please sign in again.');
          return;
        }
        if (!tplRes.ok) throw new Error(`Library backend returned ${tplRes.status}`);
        const tplData = await tplRes.json();
        const list: Template[] = Array.isArray(tplData) ? tplData : tplData.templates || [];
        const found = list.find((t) => t.id === templateId);
        if (!found) {
          setError('This integration is not in the library (it may have been disabled or removed).');
          return;
        }
        setTemplate(found);
        if (cfgRes.ok) {
          const cfgData = await cfgRes.json();
          const configs: { template_name: string; is_active: boolean }[] = Array.isArray(cfgData)
            ? cfgData
            : cfgData.configs || [];
          setConnected(configs.some((c) => c.template_name === templateId && c.is_active));
        }
      } catch {
        if (!cancelled) setError('Could not reach the MCP backend. Is the API service running?');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [templateId]);

  const icon = template ? templateIcon(template.id) : null;
  const repoUrl = template?.repo_url || null;
  const repo = repoLabel(repoUrl);

  return (
    <div className="space-y-6 max-w-3xl mx-auto">
      <Link href="/dashboard/servers/library" className="btn btn-ghost px-4 py-2 text-sm">
        <ArrowLeft size={16} /> Back to MCP Library
      </Link>

      {loading ? (
        <div className="flex items-center justify-center py-24 text-ink-faint">
          <Loader2 className="animate-spin mr-3" size={20} />
          <span className="font-pixel font-bold">Loading integration...</span>
        </div>
      ) : error ? (
        <div className="panel p-6 text-ink-dim font-body text-sm">{error}</div>
      ) : (
        template && (
          <section className="panel pixel-caps p-4 sm:p-6 md:p-8 [--cap:theme('colors.eepy.blush')]">
            <div className="flex flex-col sm:flex-row gap-5 sm:items-start mb-6">
              <div className="well relative w-20 h-20 shrink-0 p-1.5">
                {icon ? (
                  <Image src={icon} alt={template.name} fill sizes="80px" className="object-contain" />
                ) : (
                  <span className="absolute inset-0 flex items-center justify-center text-ink-faint">
                    <PlugZap size={32} />
                  </span>
                )}
              </div>
              <div className="min-w-0">
                <h2 className="font-pixel font-bold text-2xl text-ink text-px-sm">{template.name}</h2>
                {template.config_schema?.category && (
                  <div className="mt-2">
                    <span className="chip">{template.config_schema.category}</span>
                  </div>
                )}
                {repo && repoUrl && (
                  <p className="mt-3 text-sm font-body text-ink-dim leading-relaxed">
                    MCP server by{' '}
                    <a
                      href={repoUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-eepy-sage underline hover:text-eepy-pink"
                    >
                      {repo}
                    </a>{' '}
                    <ExternalLink size={12} className="inline text-ink-faint" />
                    <span className="text-ink-faint">
                      {' '}
                      &mdash; open source; audit the exact code Eepy runs.
                    </span>
                  </p>
                )}
              </div>
            </div>

            <p className="text-ink-soft font-body text-sm sm:text-base leading-relaxed mb-6">{template.description}</p>

            <div className="flex flex-col sm:flex-row sm:items-center items-stretch gap-3">
              {connected ? (
                <>
                  <span className="chip chip-sage justify-center py-2">
                    <Check size={14} /> Connected
                  </span>
                  <Link href="/dashboard/servers" className="btn btn-ghost px-4 py-2 text-sm">
                    Manage in My MCP Servers
                  </Link>
                </>
              ) : (
                <button onClick={() => setWizardOpen(true)} className="btn btn-blush px-6 py-2.5 text-sm">
                  <PlugZap size={16} /> Connect
                </button>
              )}
              <p className="text-xs font-body text-ink-dim flex items-center gap-1.5">
                <ShieldCheck size={13} className="text-eepy-sage shrink-0" />
                Credentials are encrypted at rest and only ever sent to the service itself.
              </p>
            </div>
          </section>
        )
      )}

      {template && wizardOpen && (
        <MCPConnectionWizard
          templateId={template.id}
          templateName={template.name}
          schema={template.config_schema}
          onSuccess={() => {
            setWizardOpen(false);
            setConnected(true);
          }}
          onClose={() => setWizardOpen(false)}
        />
      )}
    </div>
  );
}
