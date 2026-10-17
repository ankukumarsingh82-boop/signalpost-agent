"""Website host rules. Shared and directory hosts are not a company's site."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

# Public suffixes where the registrable name is three labels.
_MULTI_PART_SUFFIXES = {
    "co.uk",
    "org.uk",
    "ac.uk",
    "com.au",
    "net.au",
    "co.nz",
    "com.br",
    "co.jp",
}

# Hosts that list many companies. Reject even when the shared-domain file is absent.
DIRECTORY_HOSTS = {
    "1881.no",
    "brreg.no",
    "bronnoysundregistrene.no",
    "facebook.com",
    "finn.no",
    "forvalt.no",
    "github.com",
    "google.com",
    "google.no",
    "gulesider.no",
    "instagram.com",
    "linkedin.com",
    "proff.no",
    "purehelp.no",
    "regnskapstall.no",
    "snapchat.com",
    "tiktok.com",
    "trustpilot.com",
    "twitter.com",
    "wikipedia.org",
    "x.com",
    "youtube.com",
    "youtu.be",
}


def registrable_domain(hostname: str | None) -> str:
    host = (hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    labels = [part for part in host.split(".") if part]
    if len(labels) <= 2:
        return ".".join(labels)
    last_two = ".".join(labels[-2:])
    if last_two in _MULTI_PART_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return last_two


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().rstrip(".")


def same_registrable_domain(left: str, right: str) -> bool:
    return bool(registrable_domain(host_of(left))) and registrable_domain(host_of(left)) == registrable_domain(host_of(right))


def is_directory_host(hostname: str | None) -> bool:
    domain = registrable_domain(hostname)
    if not domain:
        return False
    if domain in DIRECTORY_HOSTS or domain.endswith(".brreg.no") or domain == "brreg.no":
        return True
    return False


@lru_cache(maxsize=1)
def shared_domains() -> frozenset[str]:
    path = Path(__file__).resolve().parents[2] / "data" / "shared-website-domains.txt"
    if not path.exists():
        return frozenset()
    found: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        domain = line.split("#", 1)[0].strip().lower()
        if domain:
            found.add(domain)
    return frozenset(found)


def unpublishable_reason(url: str | None) -> str | None:
    """Return why a URL must not be published as this company's website."""
    if not url:
        return None
    domain = registrable_domain(host_of(url))
    if not domain:
        return "invalid_host"
    if is_directory_host(domain):
        return "directory_host"
    if domain in shared_domains():
        return "shared_domain"
    return None
