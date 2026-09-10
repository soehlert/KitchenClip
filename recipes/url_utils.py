from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

TRACKING_QUERY_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "msclkid", "mc_cid", "mc_eid", "igshid", "ref",
    "_ga", "_gl", "token", "trk", "source", "feature"
}


def normalize_url(url: str) -> str:
    """Normalize recipe URL for consistent matching and duplicate detection."""
    if not url:
        return ""

    url = url.strip()
    parsed = urlparse(url)

    scheme = parsed.scheme.lower() if parsed.scheme else "https"
    if scheme == "http":
        scheme = "https"

    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    if ":" in netloc:
        host, _, port = netloc.partition(":")
        if port in ("80", "443"):
            netloc = host

    path = parsed.path or ""
    while "//" in path:
        path = path.replace("//", "/")
    path = path.rstrip("/")

    query_str = ""
    if parsed.query:
        query_dict = parse_qs(parsed.query, keep_blank_values=False)
        cleaned_dict = {
            k: v for k, v in query_dict.items()
            if k.lower() not in TRACKING_QUERY_PARAMS
        }
        if cleaned_dict:
            sorted_items = sorted(cleaned_dict.items())
            pairs = []
            for k, vals in sorted_items:
                for val in sorted(vals):
                    pairs.append((k, val))
            query_str = urlencode(pairs)

    return urlunparse((scheme, netloc, path, parsed.params, query_str, ""))


def get_url_lookup_variants(url: str) -> list[str]:
    """Generate search variants for a URL to match existing database records."""
    if not url:
        return []

    raw = url.strip()
    normalized = normalize_url(raw)
    parsed = urlparse(normalized)

    variants = {raw, normalized}
    variants.add(normalized.replace("https://", "http://", 1))
    variants.add(normalized.replace("http://", "https://", 1))

    if parsed.netloc:
        with_www = normalized.replace(f"://{parsed.netloc}", f"://www.{parsed.netloc}", 1)
        variants.add(with_www)
        variants.add(with_www.replace("https://", "http://", 1))

    current_variants = list(variants)
    for v in current_variants:
        parsed_v = urlparse(v)
        alt_path = parsed_v.path.rstrip("/") if parsed_v.path.endswith("/") else (parsed_v.path or "") + "/"
        variants.add(urlunparse((parsed_v.scheme, parsed_v.netloc, alt_path, parsed_v.params, parsed_v.query, "")))

    return list(variants)


def find_recipe_by_url(url: str, household=None, exclude_household=None):
    """Query Recipe for matches against normalized URL variants."""
    from recipes.models import Recipe

    variants = get_url_lookup_variants(url)
    qs = Recipe.objects.filter(original_url__in=variants)

    if household is not None:
        qs = qs.filter(household=household)
    if exclude_household is not None:
        qs = qs.exclude(household=exclude_household)

    return qs.select_related("household").first()
