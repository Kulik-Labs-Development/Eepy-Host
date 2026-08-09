export function getApiUrl() {
  if (typeof window === 'undefined') return process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

  const hostname = window.location.hostname;
  
  // Production/Staging detection: if we are on any eepy.host subdomain, use the public API
  if (hostname.endsWith('eepy.host')) {
    return 'https://api.eepy.host';
  }

  // Local development fallback
  return process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
}
