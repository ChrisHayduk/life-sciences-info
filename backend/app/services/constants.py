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
}

ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
INTERIM_FORMS = {"10-Q", "10-Q/A", "6-K", "6-K/A"}

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
]

