"""
products.py
-----------
Generates the 500-product electronics catalogue spread across 20 categories.

Product images are REAL PRODUCT PHOTOGRAPHS. At startup, for each of the 20
categories, this module queries the Openverse API (https://openverse.org) -
a free, no-key-required search engine over openly-licensed photographs
aggregated from Wikimedia Commons, Flickr, museums, and other sources. Unlike
a random tag-lottery placeholder service, Openverse runs a real relevance
search (title/tag matched), so a query like "refrigerator" reliably returns
photos of refrigerators rather than unrelated images.

Results are cached to assets/image_cache.json so the app only needs to hit
the network once (the first time it's run, or whenever the cache is deleted).
If the network is unavailable, each category falls back to an offline
Pillow-rendered illustration so the storefront still works without internet.

Pillow is also used to render the small "Elmart" logo mark shown in the store
header - fully offline, no downloads.
"""
from __future__ import annotations

import json
import random
import urllib.request
from pathlib import Path
from urllib.parse import quote

import numpy as np
import polars as pl
from faker import Faker
from PIL import Image, ImageDraw, ImageFilter, ImageFont

fake = Faker()
Faker.seed(42)
random.seed(42)
np.random.seed(42)

ASSETS_DIR = Path(__file__).parent / "assets"
IMAGE_CACHE_PATH = ASSETS_DIR / "image_cache.json"
FALLBACK_DIR = ASSETS_DIR / "category_fallback"

OPENVERSE_ENDPOINT = "https://api.openverse.org/v1/images/"
IMAGES_PER_CATEGORY = 8          # how many distinct real photos to pull per category
REQUEST_TIMEOUT_SECONDS = 6

# ----------------------------------------------------------------------------
# 20 Electronics categories with brand pools + realistic price bands (INR)
# + a natural-language search query used to find REAL product photographs
# ----------------------------------------------------------------------------
CATEGORIES: dict[str, dict] = {
    "Smartphones": {
        "brands": ["Samsung", "Apple", "OnePlus", "Xiaomi", "Realme", "Vivo"],
        "cost_range": (8000, 60000), "markup": (1.15, 1.35), "query": "smartphone",
    },
    "Laptops": {
        "brands": ["Dell", "HP", "Lenovo", "Apple", "Asus", "Acer"],
        "cost_range": (25000, 120000), "markup": (1.12, 1.30), "query": "laptop computer",
    },
    "Tablets": {
        "brands": ["Apple", "Samsung", "Lenovo", "Xiaomi", "Realme"],
        "cost_range": (9000, 55000), "markup": (1.15, 1.35), "query": "tablet computer",
    },
    "Smartwatches": {
        "brands": ["Apple", "Samsung", "Noise", "boAt", "Fitbit", "Garmin"],
        "cost_range": (1500, 25000), "markup": (1.20, 1.50), "query": "smartwatch wristwatch",
    },
    "Headphones": {
        "brands": ["Sony", "boAt", "JBL", "Sennheiser", "Bose", "Apple"],
        "cost_range": (800, 22000), "markup": (1.25, 1.60), "query": "headphones",
    },
    "Speakers": {
        "brands": ["JBL", "Bose", "Sony", "boAt", "Marshall"],
        "cost_range": (1200, 30000), "markup": (1.20, 1.55), "query": "bluetooth speaker",
    },
    "Televisions": {
        "brands": ["Samsung", "LG", "Sony", "Mi", "TCL", "OnePlus"],
        "cost_range": (12000, 150000), "markup": (1.10, 1.30), "query": "flat screen television",
    },
    "Cameras": {
        "brands": ["Canon", "Nikon", "Sony", "Fujifilm", "GoPro"],
        "cost_range": (8000, 180000), "markup": (1.15, 1.35), "query": "dslr camera",
    },
    "Gaming Consoles": {
        "brands": ["Sony", "Microsoft", "Nintendo"],
        "cost_range": (15000, 60000), "markup": (1.10, 1.25), "query": "video game console",
    },
    "Gaming Accessories": {
        "brands": ["Logitech", "Razer", "SteelSeries", "HyperX", "Redgear"],
        "cost_range": (500, 18000), "markup": (1.25, 1.60), "query": "game controller gamepad",
    },
    "Home Theater": {
        "brands": ["Sony", "Bose", "JBL", "Philips", "Samsung"],
        "cost_range": (5000, 80000), "markup": (1.15, 1.40), "query": "home theater soundbar",
    },
    "Refrigerators": {
        "brands": ["LG", "Samsung", "Whirlpool", "Haier", "Godrej"],
        "cost_range": (15000, 90000), "markup": (1.10, 1.25), "query": "refrigerator",
    },
    "Washing Machines": {
        "brands": ["LG", "Samsung", "Bosch", "IFB", "Whirlpool"],
        "cost_range": (12000, 70000), "markup": (1.10, 1.25), "query": "washing machine",
    },
    "Air Conditioners": {
        "brands": ["Daikin", "LG", "Voltas", "Samsung", "Blue Star"],
        "cost_range": (22000, 75000), "markup": (1.12, 1.28), "query": "air conditioner unit",
    },
    "Microwave Ovens": {
        "brands": ["LG", "Samsung", "IFB", "Bajaj", "Panasonic"],
        "cost_range": (4000, 25000), "markup": (1.20, 1.45), "query": "microwave oven",
    },
    "Kitchen Appliances": {
        "brands": ["Philips", "Prestige", "Bajaj", "Kent", "Havells"],
        "cost_range": (1000, 20000), "markup": (1.25, 1.60), "query": "kitchen blender appliance",
    },
    "Printers": {
        "brands": ["HP", "Canon", "Epson", "Brother"],
        "cost_range": (3500, 35000), "markup": (1.15, 1.35), "query": "printer machine office",
    },
    "Networking Devices": {
        "brands": ["TP-Link", "Netgear", "D-Link", "Asus", "Tenda"],
        "cost_range": (800, 20000), "markup": (1.25, 1.55), "query": "wifi router",
    },
    "Power Banks": {
        "brands": ["Mi", "boAt", "Anker", "Ambrane", "Realme"],
        "cost_range": (500, 4000), "markup": (1.30, 1.70), "query": "power bank charger",
    },
    "Wearable Fitness Devices": {
        "brands": ["Fitbit", "Garmin", "boAt", "Noise", "Xiaomi"],
        "cost_range": (1200, 18000), "markup": (1.25, 1.55), "query": "fitness tracker band",
    },
}

CATEGORY_LIST = list(CATEGORIES.keys())

_ADJECTIVES = ["Pro", "Max", "Ultra", "Lite", "Plus", "Air", "Neo", "Prime",
               "Edge", "Fusion", "Turbo", "X", "Studio", "Elite", "Go"]

_NOUN_MAP = {
    "Smartphones": "Phone", "Laptops": "Book", "Tablets": "Tab",
    "Smartwatches": "Watch", "Headphones": "Buds", "Speakers": "Sound",
    "Televisions": "Vision TV", "Cameras": "Cam", "Gaming Consoles": "Console",
    "Gaming Accessories": "Gear", "Home Theater": "Theater",
    "Refrigerators": "Cool", "Washing Machines": "Wash",
    "Air Conditioners": "Cool Air", "Microwave Ovens": "Chef Oven",
    "Kitchen Appliances": "Kitchen", "Printers": "Print",
    "Networking Devices": "Net", "Power Banks": "Charge",
    "Wearable Fitness Devices": "Fit",
}


# ----------------------------------------------------------------------------
# Real product photos via the Openverse API, with local caching + fallback
# ----------------------------------------------------------------------------
def _query_openverse(query: str, count: int) -> list[str]:
    """Query Openverse for real, openly-licensed photographs matching `query`.
    Returns a list of direct, hotlinkable image URLs (thumbnails, for fast
    loading in the product grid). Returns an empty list on any failure
    (no internet, rate limit, etc.) so callers can fall back gracefully."""
    url = (
        f"{OPENVERSE_ENDPOINT}?q={quote(query)}"
        f"&category=photograph&license_type=commercial,modification"
        f"&page_size={count}"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Elmart-Demo-App/1.0"})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        results = data.get("results", [])
        urls = []
        for item in results:
            img_url = item.get("thumbnail") or item.get("url")
            if img_url:
                urls.append(img_url)
        return urls[:count]
    except Exception:
        return []


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _fallback_image_path(category: str) -> str:
    """Render (or reuse) a simple offline illustration for a category, used
    only if Openverse can't be reached (e.g. no internet connection)."""
    FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
    slug = category.lower().replace(" ", "_")
    file_path = FALLBACK_DIR / f"{slug}.png"
    rel_path = f"/assets/category_fallback/{slug}.png"
    if file_path.exists():
        return rel_path

    size = 400
    img = Image.new("RGB", (size, size), (22, 17, 26))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((20, 20, size - 20, size - 20), radius=24,
                            outline=(248, 187, 208, 255), width=6)
    draw.ellipse((size / 2 - 70, size / 2 - 90, size / 2 + 70, size / 2 + 50),
                 outline=(236, 64, 122, 255), width=8)
    font = _load_font(22)
    words = category.split()
    mid = max(1, len(words) // 2) if len(" ".join(words)) > 14 else len(words)
    line1, line2 = " ".join(words[:mid]), " ".join(words[mid:])
    for j, line in enumerate([line1, line2]):
        if not line:
            continue
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        draw.text((size / 2 - w / 2, size / 2 + 70 + j * 28), line, font=font,
                   fill=(251, 228, 236, 255))
    img.save(file_path, "PNG")
    return rel_path


def _load_cache() -> dict:
    if IMAGE_CACHE_PATH.exists():
        try:
            return json.loads(IMAGE_CACHE_PATH.read_text())
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        IMAGE_CACHE_PATH.write_text(json.dumps(cache, indent=2))
    except Exception:
        pass


def build_category_image_pools(force_refresh: bool = False) -> dict[str, list[str]]:
    """Return {category: [image_urls]} - real photos fetched from Openverse
    (cached locally), falling back to an offline illustration per category
    if the network request fails."""
    cache = {} if force_refresh else _load_cache()
    pools: dict[str, list[str]] = {}
    updated = False

    for category in CATEGORY_LIST:
        cached_urls = cache.get(category)
        if cached_urls:
            pools[category] = cached_urls
            continue

        query = CATEGORIES[category]["query"]
        urls = _query_openverse(query, IMAGES_PER_CATEGORY)
        if urls:
            pools[category] = urls
            cache[category] = urls
            updated = True
        else:
            pools[category] = [_fallback_image_path(category)]

    if updated:
        _save_cache(cache)

    return pools


BULK_DISCOUNT_TIERS: list[tuple[int, float]] = [
    (20, 15.0),   # 20+ units -> extra 15% off
    (10, 10.0),   # 10-19 units -> extra 10% off
    (5, 5.0),     # 5-9 units -> extra 5% off
]


def get_bulk_discount(quantity: int) -> float:
    """Return the extra bulk-order discount percentage that applies for the
    given quantity (0 if the quantity doesn't reach any tier). This discount
    is separate from, and stacks on top of, each product's own discount."""
    for threshold, pct in BULK_DISCOUNT_TIERS:
        if quantity >= threshold:
            return pct
    return 0.0


def next_bulk_tier(quantity: int):
    """Return the (threshold, pct) of the next bulk tier not yet reached."""
    for threshold, pct in sorted(BULK_DISCOUNT_TIERS, key=lambda t: t[0]):
        if quantity < threshold:
            return threshold, pct
    return None


def bulk_discount_tiers_label() -> str:
    """Human-readable summary of all bulk tiers, smallest threshold first."""
    tiers = sorted(BULK_DISCOUNT_TIERS, key=lambda t: t[0])
    return "  ·  ".join(f"{th}+ units: extra -{pct:.0f}%" for th, pct in tiers)


def _make_product_name(category: str, brand: str, rng: random.Random) -> str:
    adjective = rng.choice(_ADJECTIVES)
    series = rng.choice(["S", "X", "Z", "A", "M", "G", "R"]) + str(rng.randint(1, 9))
    noun = _NOUN_MAP.get(category, "Device")
    return f"{brand} {noun} {series} {adjective}"


def generate_products(n: int = 500) -> pl.DataFrame:
    """Generate `n` synthetic electronics products spread across 20 categories,
    each linked to a real product photograph pulled from its category's
    Openverse image pool."""
    rng = random.Random(7)
    np_rng = np.random.default_rng(7)
    image_pools = build_category_image_pools()

    rows = []
    per_category = n // len(CATEGORY_LIST)
    remainder = n - per_category * len(CATEGORY_LIST)

    pid = 1
    for ci, category in enumerate(CATEGORY_LIST):
        info = CATEGORIES[category]
        pool = image_pools.get(category) or [_fallback_image_path(category)]
        count = per_category + (1 if ci < remainder else 0)
        for i in range(count):
            brand = rng.choice(info["brands"])
            cost = float(np_rng.uniform(*info["cost_range"]))
            cost = round(cost, -1)  # round to nearest 10
            markup = np_rng.uniform(*info["markup"])
            selling = round(cost * markup, -1)
            discount = float(np_rng.choice(
                [0, 0, 5, 10, 10, 15, 20, 25, 30], p=[0.25, 0.1, 0.12, 0.13,
                                                       0.1, 0.1, 0.1, 0.06, 0.04]))
            quantity = int(np_rng.integers(0, 400))
            rating = round(float(np_rng.uniform(3.0, 5.0)), 1)
            flash_sale = bool(np_rng.random() < 0.06)
            trending = bool(np_rng.random() < 0.10)
            product_id = f"P{pid:04d}"
            name = _make_product_name(category, brand, rng)
            image_url = pool[i % len(pool)]

            rows.append({
                "id": product_id,
                "name": name,
                "brand": brand,
                "category": category,
                "cost_price": cost,
                "selling_price": selling,
                "discount": discount,
                "quantity": quantity,
                "rating": rating,
                "image": image_url,
                "flash_sale": flash_sale,
                "trending": trending,
            })
            pid += 1

    df = pl.DataFrame(rows)
    return df


# ----------------------------------------------------------------------------
# Elmart logo (Pillow) - pink monogram on a black circle, fully offline
# ----------------------------------------------------------------------------
def generate_logo(force: bool = False) -> str:
    """Render the Elmart logo mark to assets/logo.png and return its path
    (served as /assets/logo.png)."""
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    file_path = ASSETS_DIR / "logo.png"
    rel_path = "/assets/logo.png"
    if file_path.exists() and not force:
        return rel_path

    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # soft pink glow ring on black circle
    pad = 6
    draw.ellipse((pad, pad, size - pad, size - pad), fill=(10, 7, 9, 255))
    draw.ellipse((pad, pad, size - pad, size - pad), outline=(248, 187, 208, 255), width=6)

    # inner gradient disc
    inner_pad = 22
    for i in range(size - 2 * inner_pad):
        t = i / (size - 2 * inner_pad)
        r = int(236 * (1 - t) + 194 * t)
        g = int(64 * (1 - t) + 24 * t)
        b = int(122 * (1 - t) + 91 * t)
        y = inner_pad + i
        draw.line([(inner_pad, y), (size - inner_pad, y)], fill=(r, g, b, 60))

    # shopping-bag glyph
    bag_w, bag_h = 96, 84
    cx, cy = size // 2, size // 2 + 6
    left, top = cx - bag_w // 2, cy - bag_h // 2
    right, bottom = cx + bag_w // 2, cy + bag_h // 2
    draw.rounded_rectangle((left, top, right, bottom), radius=12,
                            outline=(248, 187, 208, 255), width=7)
    handle_top = top - 26
    draw.arc((cx - 26, handle_top, cx + 26, top + 20), start=180, end=360,
              fill=(248, 187, 208, 255), width=7)
    draw.line((cx, top + 30, cx, top + 46), fill=(236, 64, 122, 255), width=6)

    font = _load_font(30)
    text = "E"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((cx - tw / 2, bottom + 6), text, font=font, fill=(248, 187, 208, 255))

    img = img.filter(ImageFilter.SMOOTH)
    img.save(file_path, "PNG")
    return rel_path


if __name__ == "__main__":
    generate_logo(force=True)
    df = generate_products(500)
    print(df.shape)
    print(df.select(["category", "image"]).unique(subset=["category"]))
