'use client';

// MCP Template Library - shows admin-approved integrations and launches the
// connection wizard. Talks to the FastAPI backend (via getApiUrl) with the
// user's Eepy JWT. No credential values ever touch the client.
import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, Loader2, PlugZap, ShieldCheck } from 'lucide-react';
import { getApiUrl } from '@/lib/api';

interface TemplateProperty {
  type?: string;
  label?: string;
  placeholder?: string;
  help?: string;
  required?: boolean;
}

interface MCPTemplate {
  id: string;
  name: string;
  description: string;
  config_schema?: {
    category?: string;
    properties?: Record<string, TemplateProperty>;
    required?: string[];
  };
  image_tag?: string | null;
}

export default function MCPLibraryPage() {
  const [templates, setTemplates] = useState<MCPTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const token = typeof window !== 'undefined' ? localStorage.getItem('eepy_token') : null;
      const res = await fetch(`${getApiUrl()}/api/mcp/templates/list`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        cache: 'no-store',
      });
      if (res.status === 401) {
        setError('Authentication required. Please sign in again.');
        setTemplates([]);
        return;
      }
      if (!res.ok) throw new Error(`Backend returned ${res.status}`);
      const data = await res.json();
      // Backend returns a bare array (response_model=list).
      setTemplates(Array.isArray(data) ? data : data.templates || []);
    } catch (err) {
      console.error('Template fetch error:', err instanceof Error ? err.message : String(err));
      setError('Could not reach the MCP backend. Is the API service running?');
      setTemplates([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="min-h-screen bg-void text-white p-8">
      <div className="max-w-6xl mx-auto">
        <Link href="/dashboard" className="inline-flex items-center gap-2 text-gray-400 hover:text-white mb-6 text-sm">
          <ArrowLeft size={16} /> Back to dashboard
        </Link>

        <header className="flex items-center justify-between mb-8 pb-4 border-b border-void-border">
          <div>
            <h1 className="text-3xl font-bold flex items-center gap-3">
              <PlugZap className="text-eepy-lavender" size={30} />
              MCP Integration Library
            </h1>
            <p className="text-gray-500 text-sm mt-2 flex items-center gap-1">
              <ShieldCheck size={14} className="text-eepy-mint" />
              Admin-approved integrations. Credentials are encrypted at rest.
            </p>
          </div>
          <button
            onClick={load}
            className="px-3 py-2 text-sm border border-void-border rounded-lg hover:bg-void-border transition-colors text-gray-300"
          >
            Refresh
          </button>
        </header>

        {loading ? (
          <div className="flex items-center justify-center py-24 text-gray-500">
            <Loader2 className="animate-spin mr-2" size={20} /> Connecting to backend...
          </div>
        ) : error ? (
          <div className="py-20 text-center">
            <p className="text-red-400 mb-4">{error}</p>
            <button onClick={load} className="px-4 py-2 bg-eepy-lavender text-void rounded-lg text-sm font-medium">
              Try again
            </button>
          </div>
        ) : templates.length === 0 ? (
          <div className="py-20 text-center text-gray-500">
            No approved integrations yet. Check back soon.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {templates.map((template) => (
              <div
                key={template.id}
                className="p-6 bg-void-surface border border-void-border rounded-xl group hover:border-eepy-lavender transition-all flex flex-col"
              >
                <div className="flex items-center justify-between mb-3">
                  <h2 className="text-lg font-bold text-eepy-mint">{template.name}</h2>
                  {template.config_schema?.category && (
                    <span className="text-[10px] px-2 py-0.5 bg-void border border-void-border text-gray-500 rounded uppercase tracking-wide">
                      {template.config_schema.category}
                    </span>
                  )}
                </div>
                <p className="text-gray-400 text-sm mb-6 leading-relaxed flex-1">
                  {template.description}
                </p>
                <Link
                  href={`/mcp/connect?template_id=${encodeURIComponent(template.id)}`}
                  className="w-full py-2 bg-eepy-lavender text-void font-medium rounded-lg hover:bg-opacity-90 transition-all text-center"
                >
                  Connect
                </Link>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
