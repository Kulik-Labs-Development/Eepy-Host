"""Shared SSRF guard for upstream URLs the backend dials itself.

Users:
- the legacy HappyFox native path in api/mcp_endpoints (the backend dials a
  user-supplied host with httpx and returns the response), and
- url templates in api/mcp_bridge (hosted remote MCP upstreams, e.g. the
  Cloudflare MCP server): the admin-registered upstream URL is range-checked
  once per instance registration.

Sync on purpose (DNS) -- call it via asyncio.to_thread from async code.
"""

import ipaddress
import socket
from urllib.parse import urlparse

from fastapi import HTTPException


def assert_public_upstream(url: str) -> None:
    """The backend dials this URL itself, so it must be a public HTTPS
    endpoint. Blocks:
      - plain http (credentials would travel in the clear),
      - loopback / private / link-local / multicast / reserved targets, which
        otherwise let any connected user read internal services or the cloud
        metadata endpoint (http://169.254.169.254) from the backend container.
    IP literals are range-checked directly; hostnames are resolved and every
    resolved address must be public. Sync on purpose (DNS) -- call it via
    asyncio.to_thread from async routes.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise HTTPException(status_code=400, detail="Upstream host must use https.")
    host = parsed.hostname or ""
    if not host:
        raise HTTPException(status_code=400, detail="Upstream host is empty.")

    try:
        candidates = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
        except socket.gaierror:
            raise HTTPException(status_code=400, detail="Upstream host does not resolve.") from None
        candidates = [ipaddress.ip_address(info[4][0]) for info in infos]
    for ip in candidates:
        # is_global (Python 3.11+) is False for loopback, RFC1918, CGNAT
        # (100.64/10), link-local (incl. the cloud metadata 169.254.169.254),
        # ULA, multicast, reserved and unspecified ranges — exactly the set of
        # hosts the backend must never dial on a user's behalf.
        if not ip.is_global:
            raise HTTPException(status_code=400, detail="Upstream host resolves to a non-public address.")


def assert_admin_upstream(url: str) -> None:
    """Variant of assert_public_upstream for the ADMIN-configured data
    source (the System Usage page's Portainer/Arcane URL, set by the
    superuser in System Settings). https is still required and loopback /
    link-local (incl. the cloud metadata 169.254.169.254) / unspecified /
    multicast / reserved targets are still blocked, but RFC1918 and ULA
    addresses are ALLOWED: the intended target is often a LAN Portainer,
    which a public-only guard would forbid. Sync on purpose (DNS) - call it
    from sync routes (they run in the threadpool).
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise HTTPException(status_code=400, detail="Data source URL must use https.")
    host = parsed.hostname or ""
    if not host:
        raise HTTPException(status_code=400, detail="Data source URL host is empty.")

    try:
        candidates = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
        except socket.gaierror:
            raise HTTPException(status_code=400, detail="Data source host does not resolve.") from None
        candidates = [ipaddress.ip_address(info[4][0]) for info in infos]
    for ip in candidates:
        # Block the ranges that make this an SSRF primitive: the backend's
        # own interfaces (loopback), the host's metadata/service ranges
        # (link-local, incl. 169.254.169.254), and the rest of the
        # non-routable namespace. RFC1918/ULA (LAN Portainer) and public
        # addresses pass.
        if (ip.is_loopback or ip.is_link_local or ip.is_unspecified
                or ip.is_multicast or ip.is_reserved):
            raise HTTPException(
                status_code=400,
                detail="Data source URL targets a loopback, link-local or "
                       "reserved address; only LAN (RFC1918/ULA) and public "
                       "hosts are allowed.",
            )
