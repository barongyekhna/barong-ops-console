"""Read a search result page as terrain: who holds it, and can we take it.

The point of monitoring is not a vanity rank. It is deciding **where to write
next**. A question whose first page is owned by established review sites is
expensive to attack; one held by marketplace listings and forum threads is soft —
a grounded, well-structured guide can outrank a Reddit comment, and that matters
because AI Overviews and answer engines pull from exactly these organic results.

Live evidence (2026-07-29 probe, "how long does a portable camping shower battery
last"): Amazon, a Facebook group, Reddit, YouTube, eBay — not one authority
listicle. That question is soft, and this module is what makes that visible for
every question instead of one at a time.
"""

from __future__ import annotations

from urllib.parse import urlparse

# Established buying-guide publishers. Beating these takes real authority, so a
# page they own is expensive terrain.
AUTHORITY_DOMAINS = {
    "outdoorgearlab.com",
    "fieldmag.com",
    "treelinereview.com",
    "nytimes.com",  # Wirecutter
    "wirecutter.com",
    "rei.com",
    "switchbacktravel.com",
    "cleverhiker.com",
    "gearjunkie.com",
    "backpacker.com",
    "popularmechanics.com",
    "goodhousekeeping.com",
    "cnet.com",
    "forbes.com",
    "businessinsider.com",
    "travelandleisure.com",
    "thespruce.com",
    "bobvila.com",
}

# Listings, not answers. They rank on commercial intent, not on explaining
# anything — which is precisely why a real answer can displace them.
MARKETPLACE_DOMAINS = {
    "amazon.com",
    "ebay.com",
    "walmart.com",
    "aliexpress.com",
    "alibaba.com",
    "etsy.com",
    "target.com",
    "homedepot.com",
    "lowes.com",
    "wayfair.com",
    "temu.com",
    "costco.com",
    "bestbuy.com",
}

# User-generated. Often the honest answer, rarely a well-structured one.
COMMUNITY_DOMAINS = {
    "reddit.com",
    "quora.com",
    "facebook.com",
    "youtube.com",
    "tiktok.com",
    "pinterest.com",
    "instagram.com",
    "x.com",
    "twitter.com",
    "stackexchange.com",
}

OUR_DOMAINS = {"barongyekhna.com"}

SURFACE_AUTHORITY = "authority"
SURFACE_MARKETPLACE = "marketplace"
SURFACE_COMMUNITY = "community"
SURFACE_BRAND = "brand"
SURFACE_OURS = "ours"

# How hard each kind of holder is to displace, per slot. Higher = harder.
_WEIGHT = {
    SURFACE_AUTHORITY: 1.0,
    SURFACE_BRAND: 0.55,
    SURFACE_MARKETPLACE: 0.3,
    SURFACE_COMMUNITY: 0.2,
    SURFACE_OURS: 0.0,
}


def registrable_domain(url: str) -> str:
    """Host without ``www`` and without the country/second-level noise we don't need."""
    try:
        host = (urlparse(str(url or "").strip()).hostname or "").lower()
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    # amazon.co.uk / gov.uk style: keep the last three when the middle is a known
    # second level; otherwise the last two is right for everything we care about.
    if len(parts) >= 3 and parts[-2] in {"co", "com", "org", "net", "gov", "ac"}:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def classify_domain(url: str) -> str:
    """Which kind of holder occupies this slot."""
    domain = registrable_domain(url)
    if not domain:
        return SURFACE_BRAND
    if domain in OUR_DOMAINS:
        return SURFACE_OURS
    if domain in AUTHORITY_DOMAINS:
        return SURFACE_AUTHORITY
    if domain in MARKETPLACE_DOMAINS:
        return SURFACE_MARKETPLACE
    if domain in COMMUNITY_DOMAINS:
        return SURFACE_COMMUNITY
    return SURFACE_BRAND


def attackability(results: list[dict]) -> int:
    """0–100. High = the page is soft and worth writing for.

    Weighted by slot, because rank 1 matters far more than rank 10: displacing a
    Reddit thread at #1 is worth more than anything at #9.
    """
    if not results:
        # No competitors visible at all — treat as wide open rather than unknown.
        return 100
    total = 0.0
    held = 0.0
    for index, row in enumerate(results[:10]):
        slot_weight = 1.0 / (index + 1)  # 1, 1/2, 1/3 …
        total += slot_weight
        held += slot_weight * _WEIGHT.get(
            classify_domain(str(row.get("url") or "")), 0.55
        )
    if total <= 0:
        return 100
    return max(0, min(100, round(100 * (1 - held / total))))


def terrain_label(score: int) -> str:
    """A one-word verdict an operator can act on without reading the table."""
    if score >= 70:
        return "soft"
    if score >= 40:
        return "mixed"
    return "hard"


def summarize(results: list[dict]) -> dict:
    """Everything the console needs about one question's first page."""
    counts: dict[str, int] = {}
    for row in results[:10]:
        kind = classify_domain(str(row.get("url") or ""))
        counts[kind] = counts.get(kind, 0) + 1
    our_position = None
    for row in results:
        if classify_domain(str(row.get("url") or "")) == SURFACE_OURS:
            our_position = int(row.get("position") or 0) or None
            break
    score = attackability(results)
    return {
        "our_position": our_position,
        "attackability": score,
        "terrain": terrain_label(score),
        "holder_counts": counts,
        "top_domains": [
            registrable_domain(str(r.get("url") or "")) for r in results[:10]
        ],
    }


__all__ = [
    "AUTHORITY_DOMAINS",
    "COMMUNITY_DOMAINS",
    "MARKETPLACE_DOMAINS",
    "OUR_DOMAINS",
    "attackability",
    "classify_domain",
    "registrable_domain",
    "summarize",
    "terrain_label",
]
