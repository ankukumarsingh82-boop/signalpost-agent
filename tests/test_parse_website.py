from signalpost.parse_website import extract_page, organisation_number_pattern, robots_blocks_homepage


ORG = "923609016"


def test_spaced_organisation_number_verifies_page_and_keeps_social_links():
    html = """
    <html><head>
      <title>Equinor</title>
      <meta name="description" content="Equinor develops oil, gas, wind and solar projects from Stavanger.">
      <script type="application/ld+json">{"@type":"Organization","sameAs":["https://www.linkedin.com/company/equinor"]}</script>
    </head>
    <body>
      <p>Organisasjonsnummer 923 609 016</p>
      <a href="/karriere">Karriere</a>
      <a href="https://news.example.com/equinor">News</a>
      <a href="/nyheter">Nyheter</a>
    </body></html>
    """
    extracted = extract_page(html, ORG, "https://www.equinor.com/")
    assert extracted["verified"] is True
    assert extracted["description"].startswith("Equinor develops")
    assert extracted["social_links"] == [{"platform": "linkedin", "url": "https://www.linkedin.com/company/equinor"}]
    assert extracted["hiring_pages"] == ["https://www.equinor.com/karriere"]
    assert extracted["news_pages"] == ["https://www.equinor.com/nyheter"]
    assert "923 609 016" in extracted["claim_span"] or "923609016" in extracted["claim_span"]


def test_different_organisation_number_is_not_publishable():
    html = "<html><body><p>Org 111111111</p><a href='https://linkedin.com/company/other'>LinkedIn</a></body></html>"
    extracted = extract_page(html, ORG, "https://example.no/")
    assert extracted["verified"] is False
    assert extracted["description"] is None
    assert extracted["social_links"] == []
    assert extracted["hiring_pages"] == []
    assert extracted["rejected_social_links"]


def test_pattern_does_not_match_a_longer_number():
    assert organisation_number_pattern(ORG).search("x9236090169") is None
    assert organisation_number_pattern(ORG).search("NO923609016MVA")


def test_robots_disallow_root_blocks_homepage_only():
    assert robots_blocks_homepage("User-agent: *\nDisallow: /\n") is True
    assert robots_blocks_homepage("User-agent: *\nDisallow: /admin\n") is False
    assert robots_blocks_homepage("User-agent: *\nDisallow: /\nAllow: /\n") is False
