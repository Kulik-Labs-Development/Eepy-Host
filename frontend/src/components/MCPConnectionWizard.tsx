'use client';

// MCP Connection Wizard - renders a dynamic form from the template's config_schema,
// submits credentials to the backend (where they are Fernet-encrypted), and reports
// success with the unified proxy URL. Credentials never leave this component except
// in the single encrypted-at-rest register call.

import { useState } from 'react';
import { X, KeyRound, Eye, EyeOff, Loader2, CheckCircle2, ShieldCheck } from 'lucide-react';
import { getApiUrl } from '@/lib/api';

export interface SchemaProperty {
  type?: string;
  label?: string;
  placeholder?: string;
  help?: string;
  required?: boolean;
}

export interface TemplateSchema {
  properties?: Record<string, SchemaProperty>;
  required?: string[];
}

interface Props {
  templateId: string;
  templateName: string;
  schema: TemplateSchema | undefined;
  onSuccess: (result: { configId: number; proxyUrl: string }) => void;
  onClose: () => void;
}

export default function MCPConnectionWizard({ templateId, templateName, schema, onSuccess, onClose }: Props) {
  const [formData, setFormData] = useState<Record<string, string>>({});
  const [showPasswords, setShowPasswords] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const properties = schema?.properties || {};
  const required = new Set(schema?.required || Object.keys(properties).filter((k) => properties[k].required));

  const isPassword = (key: string) => properties[key]?.type === 'password';

  const setField = (field: string, value: string) =>
    setFormData((prev) => ({ ...prev, [field]: value }));

  const toggleVisibility = (field: string) =>
    setShowPasswords((prev) => ({ ...prev, [field]: !prev[field] }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    // Client-side preflight: required fields populated.
    const missing = Array.from(required).filter((f) => !formData[f]?.trim());
    if (missing.length > 0) {
      setError(`Missing required fields: ${missing.join(', ')}`);
      setLoading(false);
      return;
    }

    try {
      const token = typeof window !== 'undefined' ? localStorage.getItem('eepy_token') : null;
      const res = await fetch(`${getApiUrl()}/api/mcp/config/register`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          template_id: templateId,
          display_name: `${templateName} connection`,
          credentials_json: formData,
        }),
      });

      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || `Backend returned ${res.status}`);
      }

      onSuccess({ configId: data.id, proxyUrl: data.proxy_url || `/api/mcp/proxy/${templateId}` });
    } catch (err) {
      // Error strings from the backend are safe (no secrets in them by design).
      setError(err instanceof Error ? err.message : String(err));
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-night-deep/80 flex items-end sm:items-center justify-center sm:p-4 z-[999] backdrop-blur-sm">
      <div className="panel pixel-caps border-eepy-blush/70 p-4 sm:p-6 max-w-md w-full relative shadow-pixel-lg max-h-[92vh] overflow-y-auto [--cap:theme('colors.eepy.pink')]">
        <header className="flex items-center justify-between mb-6 pb-4 border-b-2 border-night-line gap-3">
          <div className="min-w-0">
            <h2 className="font-pixel font-bold text-base sm:text-lg flex items-center gap-2 text-ink">
              <ShieldCheck className="text-eepy-sage" size={18} shrink-0 />
              <span className="truncate">Connect: {templateName}</span>
            </h2>
            <p className="text-xs text-ink-dim mt-1.5 font-body">Credentials are encrypted at rest (Fernet) on the server.</p>
          </div>
          <button onClick={onClose} className="btn-icon shrink-0" aria-label="Close">
            <X size={16} />
          </button>
        </header>

        <form onSubmit={handleSubmit}>
          <div className="space-y-4 mb-6">
            {Object.entries(properties).map(([key, prop]) => (
              <div key={key}>
                <label className="label-pixel flex items-center gap-2">
                  {prop.label || key}
                  {required.has(key) && <span className="w-2 h-2 bg-eepy-ember inline-block" title="Required" />}
                </label>
                <div className="relative">
                  <KeyRound size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-dim" />
                  <input
                    type={isPassword(key) && !showPasswords[key] ? 'password' : 'text'}
                    required={required.has(key)}
                    placeholder={prop.placeholder || key}
                    value={formData[key] || ''}
                    onChange={(e) => setField(key, e.target.value)}
                    className="input-pixel pl-9 pr-10"
                  />
                  {isPassword(key) && (
                    <button
                      type="button"
                      onClick={() => toggleVisibility(key)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-dim hover:text-eepy-blush transition-colors"
                      aria-label={showPasswords[key] ? 'Hide value' : 'Show value'}
                    >
                      {showPasswords[key] ? <EyeOff size={15} /> : <Eye size={15} />}
                    </button>
                  )}
                </div>
                {prop.help && <p className="text-xs text-ink-dim mt-1.5 font-body">{prop.help}</p>}
              </div>
            ))}
          </div>

          {error && (
            <p className="text-sm text-eepy-ember mb-4 bg-eepy-ember/10 border-l-4 border-eepy-ember p-3 font-body">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="btn btn-blush w-full py-3"
          >
            {loading ? (
              <>
                <Loader2 size={16} className="animate-spin" /> Encrypting &amp; saving...
              </>
            ) : error ? (
              'Retry Connection'
            ) : (
              <>
                <CheckCircle2 size={16} /> Connect &amp; Encrypt Credentials
              </>
            )}
          </button>
        </form>
      </div>
    </div>
  );
}
