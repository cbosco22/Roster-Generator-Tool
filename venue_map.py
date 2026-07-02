"""
venue_map.py — a real map for the venue page: numbered pins for each venue
plus a star for the event hub, rendered from OpenStreetMap tiles.

Chris 2026-07-02: the drive-time table says "how far", but coaches hop
venue-to-venue — the map shows "which ones are near each OTHER". Pin
numbers match the table rows on the same page.

No API key: geocoding via Nominatim (1 req/sec, cached to disk so each
address is ever looked up once) and raster tiles from
tile.openstreetmap.org (proper User-Agent, attribution drawn on the image,
per OSM tile policy — an event needs ~12 tiles, well within usage limits).
"""
import io
import json
import math
import os
import time

import requests

_UA = {"User-Agent": "navy-baseball-roster-tool/1.0 (bosco.chris01@gmail.com)"}
_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "data", "geocode_cache.json")


def geocode(address):
    """address -> (lat, lon) or None. Disk-cached; 1 req/sec when live."""
    cache = {}
    if os.path.exists(_CACHE):
        with open(_CACHE) as f:
            cache = json.load(f)
    key = address.strip().lower()
    if key in cache:
        return tuple(cache[key]) if cache[key] else None
    time.sleep(1.1)  # Nominatim usage policy
    try:
        r = requests.get("https://nominatim.openstreetmap.org/search",
                         params={"q": address, "format": "json", "limit": 1},
                         headers=_UA, timeout=20)
        r.raise_for_status()
        hits = r.json()
        val = [float(hits[0]["lat"]), float(hits[0]["lon"])] if hits else None
    except Exception:
        return None  # transient failure: don't cache, don't crash the build
    os.makedirs(os.path.dirname(_CACHE), exist_ok=True)
    cache[key] = val
    with open(_CACHE, "w") as f:
        json.dump(cache, f)
    return tuple(val) if val else None


def _lonlat_to_xy(lon, lat, zoom):
    n = 2.0 ** zoom
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


def build_map_image(points, width_px=1200, height_px=720):
    """points: [{'lat','lon','label' (pin number, '' = hub star)}] ->
    PIL Image with OSM basemap + pins. Returns None if points is empty."""
    from PIL import Image, ImageDraw, ImageFont
    pts = [p for p in points if p.get("lat") is not None]
    if not pts:
        return None

    # pick the deepest zoom where all points fit with padding
    for zoom in range(13, 5, -1):
        xs, ys = zip(*[_lonlat_to_xy(p["lon"], p["lat"], zoom) for p in pts])
        w_tiles = (max(xs) - min(xs))
        h_tiles = (max(ys) - min(ys))
        if w_tiles * 256 <= width_px * 0.80 and h_tiles * 256 <= height_px * 0.72:
            break

    xs, ys = zip(*[_lonlat_to_xy(p["lon"], p["lat"], zoom) for p in pts])
    cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    # top-left of the crop window, in tile units
    x0 = cx - width_px / 2.0 / 256.0
    y0 = cy - height_px / 2.0 / 256.0

    img = Image.new("RGB", (width_px, height_px), "#DDE4EA")
    tx0, ty0 = int(math.floor(x0)), int(math.floor(y0))
    tx1 = int(math.floor(x0 + width_px / 256.0)) + 1
    ty1 = int(math.floor(y0 + height_px / 256.0)) + 1
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            if tx < 0 or ty < 0 or tx >= 2 ** zoom or ty >= 2 ** zoom:
                continue
            try:
                r = requests.get(
                    f"https://tile.openstreetmap.org/{zoom}/{tx}/{ty}.png",
                    headers=_UA, timeout=20)
                r.raise_for_status()
                tile = Image.open(io.BytesIO(r.content)).convert("RGB")
                img.paste(tile, (int((tx - x0) * 256), int((ty - y0) * 256)))
            except Exception:
                pass  # a missing tile leaves a gray square, not a dead build

    draw = ImageDraw.Draw(img)
    font = None
    for fp in ("/System/Library/Fonts/Helvetica.ttc",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(fp, 22)
            break
        except Exception:
            continue
    font = font or ImageFont.load_default()

    for p in pts:
        px, py = _lonlat_to_xy(p["lon"], p["lat"], zoom)
        X, Y = (px - x0) * 256, (py - y0) * 256
        if p.get("label"):
            r_ = 16
            draw.ellipse([X - r_, Y - r_, X + r_, Y + r_],
                         fill="#14233B", outline="white", width=3)
            t = str(p["label"])
            bb = draw.textbbox((0, 0), t, font=font)
            draw.text((X - (bb[2] - bb[0]) / 2, Y - (bb[3] - bb[1]) / 2 - bb[1]),
                      t, fill="white", font=font)
        else:  # hub star
            s, s2 = 22, 9
            star = []
            for i in range(10):
                ang = -math.pi / 2 + i * math.pi / 5
                rr = s if i % 2 == 0 else s2
                star.append((X + rr * math.cos(ang), Y + rr * math.sin(ang)))
            draw.polygon(star, fill="#C9A227", outline="white")

    # OSM attribution (required by tile usage policy)
    tag = "© OpenStreetMap"
    bb = draw.textbbox((0, 0), tag, font=font)
    draw.rectangle([width_px - (bb[2] - bb[0]) - 14, height_px - (bb[3] - bb[1]) - 10,
                    width_px, height_px], fill="white")
    draw.text((width_px - (bb[2] - bb[0]) - 7, height_px - (bb[3] - bb[1]) - 7),
              tag, fill="#555555", font=font)
    return img


def venue_map_for(hub, venues, width_px=1480, height_px=620):
    """Geocode hub + venues (addresses -> pins numbered by drive-time order,
    matching the venue table) and return a PIL map image, or None.
    Default pixel dims match the venue page's 7.4in x 3.1in map box so the
    tiles aren't stretched."""
    pts = []
    hub_addr = hub.get("address") or hub.get("name", "")
    ll = geocode(hub_addr)
    if ll:
        pts.append({"lat": ll[0], "lon": ll[1], "label": ""})
    ordered = sorted(venues, key=lambda v: v.get("drive_min", 999))
    for i, v in enumerate(ordered):
        # street address first; when Nominatim can't resolve it (3 of 11 real
        # GA school addresses missed), fall back to the venue NAME + city —
        # schools/parks are OSM POIs and resolve by name reliably
        ll = None
        for q in (", ".join(x for x in (v.get("address", ""), v.get("city", "")) if x),
                  ", ".join(x for x in (v.get("venue", ""), v.get("city", "")) if x),
                  # last resort: pin the CITY. Approximate, but for "which
                  # venues are near each other" a city-center pin beats a
                  # missing one (2 of 11 real venues resolved no other way).
                  v.get("city", "")):
            if q:
                ll = geocode(q)
                if ll:
                    break
        if ll:
            pts.append({"lat": ll[0], "lon": ll[1], "label": str(i + 1)})
    return build_map_image(pts, width_px=width_px, height_px=height_px)
