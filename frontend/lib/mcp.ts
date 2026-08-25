// Shared helpers for the MCP Library UI (library panel + template info page).
import type { TemplateSchema } from '@/src/components/MCPConnectionWizard';

export interface Template {
  id: string;
  name: string;
  description: string;
  config_schema?: TemplateSchema & { category?: string };
  image_tag?: string | null;
  repo_url?: string | null;
}

export function authHeaders(): Record<string, string> {
  if (typeof window === 'undefined') return {};
  const token = localStorage.getItem('eepy_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// App icons for the known integrations (served from frontend/public).
// Unknown templates fall back to the generic plug icon in the UI.
export const APP_ICONS: Record<string, string> = {
  happyfox: '/app-icons/happyfox-logo.png',
  ebay: '/app-icons/ebay.png',
  portainer: '/app-icons/portainer-pink.png',
  warden: '/app-icons/vaultwarden.png',
  proxmox: '/app-icons/proxmox.png',
  trmm: '/app-icons/trmm.png',
  'trmm-exec': '/app-icons/trmm.png',
  clarity: '/app-icons/clarity.png',
};

export function templateIcon(templateId: string): string | null {
  return APP_ICONS[templateId] ?? null;
}

// "https://github.com/owner/repo" -> "owner/repo" (author credit + audit link).
// Non-GitHub URLs are returned trimmed (no trailing slash) as-is.
export function repoLabel(url: string | null | undefined): string | null {
  if (!url) return null;
  const m = url.match(/^https?:\/\/(?:www\.)?github\.com\/([^/\s]+)\/([^/\s#?]+)/i);
  if (m) return `${m[1]}/${m[2]}`;
  return url.replace(/\/+$/, '');
}
