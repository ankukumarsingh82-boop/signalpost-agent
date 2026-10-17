import ipaddress

from signalpost.domains import registrable_domain, same_registrable_domain, unpublishable_reason
from signalpost.http_client import _is_blocked_ip, assert_public_http_url
from signalpost.news import exact_legal_name_match, news_match, select_news_items


def test_benchmark_net_is_allowed_unless_configured(monkeypatch):
    ip = ipaddress.ip_address("198.18.0.1")
    monkeypatch.delenv("SIGNALPOST_BLOCK_BENCHMARK_NETS", raising=False)
    assert _is_blocked_ip(ip) is False
    assert_public_http_url("https://198.18.0.1/health")
    monkeypatch.setenv("SIGNALPOST_BLOCK_BENCHMARK_NETS", "1")
    assert _is_blocked_ip(ip) is True
    assert _is_blocked_ip(ipaddress.ip_address("10.1.2.3")) is True
    assert _is_blocked_ip(ipaddress.ip_address("127.0.0.1")) is True


def test_shared_and_directory_hosts_are_unpublishable():
    assert registrable_domain("www.shop.obos.no") == "obos.no"
    assert unpublishable_reason("https://www.obos.no/sameie") == "shared_domain"
    assert unpublishable_reason("https://www.proff.no/selskap/x") == "directory_host"
    assert unpublishable_reason("https://www.equinor.com") is None
    assert same_registrable_domain("https://www.equinor.com", "https://cdn.equinor.com/about") is True
    assert same_registrable_domain("https://example.no", "https://www.proff.no/x") is False


def test_news_requires_org_number_or_name_plus_municipality():
    name = "SANDNES ELEKTRISKE AS"
    assert news_match("810034882", name, "SANDNES", f"{name} vant kontrakt", "Arbeidet skjer i Sandnes.") == "name_and_municipality"
    assert news_match("810034882", name, "SANDNES", f"{name} vant kontrakt", "Ingen sted nevnt.") is None
    assert news_match("810034882", name, "SANDNES", "Elektrikere vant kontrakt", "Sandnes") is None
    assert news_match("810034882", name, None, "Org 810034882", "") == "organisation_number"
    assert exact_legal_name_match(name, f"fra {name} i går") is True
    rss = f"""<?xml version="1.0"?><rss><channel><item>
      <title>{name} vant kontrakt - VG</title>
      <link>https://news.google.com/rss/articles/abc</link>
      <pubDate>Fri, 16 Oct 2026 12:00:00 GMT</pubDate>
      <description>Selskapet i Sandnes utvider.</description>
      <source>VG</source>
    </item></channel></rss>"""
    items = select_news_items(rss, org="810034882", legal_name=name, municipality="SANDNES")
    assert len(items) == 1
    assert items[0]["published_at"].startswith("2026-10-16")
    assert select_news_items(rss, org="810034882", legal_name=name, municipality="OSLO") == []
