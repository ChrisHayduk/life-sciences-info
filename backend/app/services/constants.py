CORE_LIFE_SCIENCES_SIC = {
    "2833": "MEDICINAL CHEMICALS & BOTANICAL PRODUCTS",
    "2834": "PHARMACEUTICAL PREPARATIONS",
    "2835": "IN VITRO & IN VIVO DIAGNOSTIC SUBSTANCES",
    "2836": "BIOLOGICAL PRODUCTS, (NO DIAGNOSTIC SUBSTANCES)",
    "3841": "SURGICAL & MEDICAL INSTRUMENTS & APPARATUS",
    "3842": "ORTHOPEDIC, PROSTHETIC & SURGICAL APPLIANCES",
    "3844": "X-RAY APPARATUS & TUBES & RELATED IRRADIATION APPARATUS",
    "3845": "ELECTROMEDICAL & ELECTROTHERAPEUTIC APPARATUS",
}

TARGET_FORMS = {
    "10-K",
    "10-K/A",
    "10-Q",
    "10-Q/A",
    "20-F",
    "20-F/A",
    "40-F",
    "40-F/A",
    "6-K",
    "6-K/A",
    "8-K",
    "8-K/A",
}

ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
INTERIM_FORMS = {"10-Q", "10-Q/A", "6-K", "6-K/A"}
# Automated SEC backfills and polling currently target periodic-equivalent
# filings only. Event filings remain supported downstream when created by
# another ingestion path.
EVENT_FORMS = {"8-K", "8-K/A"}

# 8-K item numbers mapped to human-readable event categories
EIGHT_K_ITEM_TOPICS: dict[str, str] = {
    "1.01": "material-agreement",
    "1.02": "bankruptcy",
    "1.03": "mine-safety",
    "2.01": "acquisition-disposition",
    "2.02": "results-of-operations",
    "2.03": "creation-of-obligation",
    "2.04": "triggering-events",
    "2.05": "costs-exit-activities",
    "2.06": "material-impairments",
    "3.01": "delisting",
    "3.02": "unregistered-sales",
    "3.03": "material-modification-of-rights",
    "4.01": "auditor-change",
    "4.02": "non-reliance-on-financials",
    "5.01": "change-of-control",
    "5.02": "leadership-change",
    "5.03": "amendments-to-articles",
    "5.07": "shareholder-vote",
    "7.01": "regulation-fd",
    "8.01": "other-events",
    "9.01": "financial-statements-exhibits",
}

MATERIAL_EIGHT_K_ITEMS = {
    "1.01",
    "2.01",
    "2.02",
    "2.03",
    "3.02",
    "4.02",
    "5.02",
    "8.01",
}

FILING_SECTION_PATTERNS = {
    "business": ["business", "our business", "overview"],
    "risk_factors": ["risk factors", "principal risks"],
    "md&a": ["management's discussion", "management discussion", "operating and financial review"],
    "financial_statements": ["financial statements", "consolidated statements", "balance sheets"],
    "legal_proceedings": ["legal proceedings", "litigation"],
    "liquidity": ["liquidity and capital resources", "capital resources"],
    "subsequent_events": ["subsequent events", "recent developments"],
}

NEWS_FEEDS = [
    {
        "name": "Fierce Pharma",
        "feed_url": "https://www.fiercepharma.com/rss/xml",
        "source_weight": 0.95,
        "topic_tags": ["pharma"],
    },
    {
        "name": "Fierce Biotech",
        "feed_url": "https://www.fiercebiotech.com/rss/xml",
        "source_weight": 0.95,
        "topic_tags": ["biotech", "medtech"],
    },
    {
        "name": "FDA Press Releases",
        "feed_url": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml",
        "source_weight": 0.9,
        "topic_tags": ["regulatory"],
    },
    {
        "name": "STAT News",
        "feed_url": "https://www.statnews.com/feed/",
        "source_weight": 0.95,
        "topic_tags": ["pharma", "biotech", "policy"],
    },
    {
        "name": "Endpoints News",
        "feed_url": "https://endpts.com/feed/",
        "source_weight": 0.92,
        "topic_tags": ["biotech", "clinical-trials"],
    },
    {
        "name": "BioPharma Dive",
        "feed_url": "https://www.biopharmadive.com/feeds/news/",
        "source_weight": 0.90,
        "topic_tags": ["pharma", "biotech"],
    },
    {
        "name": "GEN News",
        "feed_url": "https://www.genengnews.com/feed/",
        "source_weight": 0.85,
        "topic_tags": ["biotech", "genomics"],
    },
    {
        "name": "FDA Drug Approvals",
        "feed_url": "https://www.fda.gov/drugs/drug-approvals-and-databases/rss.xml",
        "source_weight": 0.90,
        "topic_tags": ["regulatory", "approvals"],
    },
]

# Default official investor-relations / press release sources for a starter
# subset of large-cap companies. The ingestion pipeline supports both RSS
# feeds and HTML IR/news pages, plus company-specific overrides via
# Company.extra_metadata["ir_feed_url"], ["ir_news_page_url"], or ["ir_sources"].
COMPANY_IR_SOURCES: dict[str, list[dict[str, object]]] = {
    "LLY": [
        {
            "kind": "rss",
            "url": "https://investor.lilly.com/rss/news-releases.xml",
        }
    ],
    "ABBV": [
        {
            "kind": "rss",
            "url": "https://investors.abbvie.com/rss/news-releases.xml",
        }
    ],
    "GILD": [
        {
            "kind": "html_page",
            "url": "https://investors.gilead.com/overview/default.aspx",
            "entry_selectors": ["a[href*='/news/news-details/']"],
        }
    ],
    "AMGN": [
        {
            "kind": "html_page",
            "url": "https://investors.amgen.com/",
            "entry_selectors": ["a[href*='/news-releases/news-release-details/']"],
        }
    ],
    "PFE": [
        {
            "kind": "html_page",
            "url": "https://investors.pfizer.com/Investors/News/default.aspx",
            "entry_selectors": ["a[href*='/Investors/News/press-release-details/']"],
        }
    ],
    "MRNA": [
        {
            "kind": "html_page",
            "url": "https://investors.modernatx.com/",
            "entry_selectors": ["a[href*='/news/news-details/']"],
        }
    ],
}

# Backward-compatible alias for older code/tests that expect a simple ticker->RSS map.
COMPANY_IR_FEEDS: dict[str, str] = {
    ticker: sources[0]["url"]
    for ticker, sources in COMPANY_IR_SOURCES.items()
    if sources and sources[0].get("kind") == "rss"
}

# Per-site article body CSS selectors for scraping full article text.
# Falls back to generic <article> / <p> extraction if domain not listed.
SITE_ARTICLE_SELECTORS: dict[str, str] = {
    "statnews.com": "article .entry-content",
    "endpts.com": "article .entry-content",
    "biopharmadive.com": "article .article-body",
    "genengnews.com": "article .entry-content",
}
