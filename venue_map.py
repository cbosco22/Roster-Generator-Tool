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
import re
import time

import requests

_UA = {"User-Agent": "navy-baseball-roster-tool/1.0 (bosco.chris01@gmail.com)"}
_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "data", "geocode_cache.json")

# Venues at an event are drivable from the hub. Any geocode farther than
# this is a wrong match, whatever query produced it — found live 2026-07-03:
# "St. Johns HS" (Shrewsbury, MA) resolved to St. Johns, MICHIGAN because
# the street address ("314-347 Main Street…", a range Nominatim can't parse)
# failed and the fallback geocoded the bare venue name with no locality.
MAX_VENUE_KM = 250


def _dist_km(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2 +
         math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 6371 * 2 * math.asin(math.sqrt(h))


def _addr_state(addr):
    m = re.search(r',\s*([A-Z]{2})(?:\s+\d{5})?\s*$', addr or '')
    return m.group(1) if m else None


def venues_from_games(games, region):
    """Derive the venue list from schedule game locations when the source
    (Perfect Game) publishes no venue addresses. 'Field 1 @ East Cobb
    Complex' -> complex name; region ('GA', 'Marietta, GA') anchors the
    geocode query and the hub-distance guard rejects wrong-state matches.
    Venue names like 'Etowah High School - GA' / 'Mt. Zion High School -
    Jonesboro' carry their locality after ' - '."""
    counts = {}
    for g in games:
        loc = (g.get("location") or "").strip()
        if not loc:
            continue
        m = re.search(r'@\s*(.+)$', loc)
        name = (m.group(1) if m else loc).strip()
        counts[name] = counts.get(name, 0) + 1
    venues = []
    for name, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        loc_hint = region
        base = name
        if ' - ' in name:
            base, tail = [x.strip() for x in name.rsplit(' - ', 1)]
            if re.fullmatch(r'[A-Z]{2}', tail):
                loc_hint = tail
            elif tail:
                loc_hint = f"{tail}, {region}"
        venues.append({"venue": name, "address": f"{base}, {loc_hint}",
                       "games": n})
    return venues


def venue_geocode(v, hub_ll=None):
    """Geocode one venue dict ({'venue','address','city'?}) with a
    plausibility guard: every candidate query carries a locality (city or
    the address's own state — NEVER a bare venue name), and any hit farther
    than MAX_VENUE_KM from the hub is rejected as a wrong match."""
    addr = (v.get("address") or "").strip()
    name = (v.get("venue") or "").strip()
    city = (v.get("city") or "").strip()
    state = _addr_state(addr)
    cands = []
    if addr:
        cands.append(", ".join(x for x in (addr, city) if x))
        # street-number ranges ("314-347 Main St") break Nominatim; retry
        # with the first number alone
        a2 = re.sub(r'^(\d+)\s*[-–]\s*\d+\s', r'\1 ', addr)
        if a2 != addr:
            cands.append(", ".join(x for x in (a2, city) if x))
    if name and city:
        cands.append(f"{name}, {city}")
    if name and state:
        cands.append(f"{name}, {state}")
    if city:
        cands.append(city)
    for q in cands:
        ll = geocode(q)
        if ll and (hub_ll is None or _dist_km(ll, hub_ll) <= MAX_VENUE_KM):
            return ll
    return None


def _census_geocode(address):
    """US Census geocoder — free, no key, street addresses only. Fallback for
    the many real street addresses OSM has no interpolation for (found live
    2026-07-03: '4617 Lee Waters Road Marietta, GA', the East Cobb Complex,
    misses on Nominatim but matches exactly on Census)."""
    try:
        r = requests.get(
            "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress",
            params={"address": address, "benchmark": "Public_AR_Current",
                    "format": "json"}, headers=_UA, timeout=25)
        r.raise_for_status()
        m = r.json().get("result", {}).get("addressMatches", [])
        if m:
            c = m[0]["coordinates"]
            return [float(c["y"]), float(c["x"])]
    except Exception:
        pass
    return None


def geocode(address):
    """address -> (lat, lon) or None. Nominatim first, US Census geocoder as
    the street-address fallback. Disk-cached; 1 req/sec when live."""
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
    if val is None and re.match(r'^\d+\s', address.strip()):
        val = _census_geocode(address)
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


def build_map_image(points, width_px=1480, height_px=620):
    """points: [{'lat','lon','label' (pin number, '' = hub star),'name'}] ->
    PIL Image with a clean light basemap + labeled pins. None if empty.

    Basemap is CARTO Positron (the pale, Apple-Maps-ish style Chris asked
    for after seeing default OSM: "get rid of the gray and red and all the
    colors") and the fit is FRACTIONAL-zoom: tiles render at the next zoom
    up and downscale to exactly fill the frame, instead of snapping to a
    power-of-two zoom that left dead space on every side."""
    from PIL import Image, ImageDraw, ImageFont
    pts = [p for p in points if p.get("lat") is not None]
    if not pts:
        return None

    # fractional zoom: bbox fills ~86% of width / ~76% of height
    xs0, ys0 = zip(*[_lonlat_to_xy(p["lon"], p["lat"], 0) for p in pts])
    span_x0 = max(max(xs0) - min(xs0), 1e-9)
    span_y0 = max(max(ys0) - min(ys0), 1e-9)
    zf = min(math.log2(width_px * 0.86 / (256.0 * span_x0)),
             math.log2(height_px * 0.76 / (256.0 * span_y0)), 13.0)
    z = min(13, int(math.ceil(zf)))
    scale = 2.0 ** (zf - z)   # <= 1: how much the z-level render shrinks

    # render window at integer zoom z, sized so the downscale hits the frame
    rw, rh = int(width_px / scale), int(height_px / scale)
    xs, ys = zip(*[_lonlat_to_xy(p["lon"], p["lat"], z) for p in pts])
    cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    x0 = cx - rw / 2.0 / 256.0
    y0 = cy - rh / 2.0 / 256.0

    base = Image.new("RGB", (rw, rh), "#F4F4F2")
    tx1 = int(math.floor(x0 + rw / 256.0)) + 1
    ty1 = int(math.floor(y0 + rh / 256.0)) + 1
    for tx in range(int(math.floor(x0)), tx1 + 1):
        for ty in range(int(math.floor(y0)), ty1 + 1):
            if tx < 0 or ty < 0 or tx >= 2 ** z or ty >= 2 ** z:
                continue
            try:
                r = requests.get(
                    f"https://a.basemaps.cartocdn.com/light_all/{z}/{tx}/{ty}.png",
                    headers=_UA, timeout=20)
                r.raise_for_status()
                tile = Image.open(io.BytesIO(r.content)).convert("RGB")
                base.paste(tile, (int((tx - x0) * 256), int((ty - y0) * 256)))
            except Exception:
                pass  # a missing tile leaves a pale square, not a dead build

    img = base.resize((width_px, height_px), Image.LANCZOS)
    draw = ImageDraw.Draw(img)

    def _font(size):
        for fp in ("/System/Library/Fonts/Helvetica.ttc",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
        return ImageFont.load_default()
    f_pin, f_lbl, f_attr = _font(20), _font(17), _font(14)
    placed_labels = []  # boxes already used, for collision avoidance

    def _to_px(p):
        px, py = _lonlat_to_xy(p["lon"], p["lat"], z)
        return ((px - x0) * 256) * scale, ((py - y0) * 256) * scale

    for p in pts:
        X, Y = _to_px(p)
        if p.get("label"):
            r_ = 14
            draw.ellipse([X - r_, Y - r_, X + r_, Y + r_],
                         fill="#14233B", outline="white", width=3)
            t = str(p["label"])
            bb = draw.textbbox((0, 0), t, font=f_pin)
            draw.text((X - (bb[2] - bb[0]) / 2, Y - (bb[3] - bb[1]) / 2 - bb[1]),
                      t, fill="white", font=f_pin)
            if p.get("name"):
                _place_label(draw, X, Y, r_ + 5, p["name"], f_lbl, "#14233B",
                             placed_labels, width_px, height_px)
        else:  # hub star
            s_, s2 = 20, 8
            star = []
            for i in range(10):
                ang = -math.pi / 2 + i * math.pi / 5
                rr = s_ if i % 2 == 0 else s2
                star.append((X + rr * math.cos(ang), Y + rr * math.sin(ang)))
            draw.polygon(star, fill="#C9A227", outline="white")
            if p.get("name"):
                _place_label(draw, X, Y, s_ + 4, p["name"], f_lbl, "#8A6D14",
                             placed_labels, width_px, height_px)

    tag = "© OpenStreetMap © CARTO"
    bb = draw.textbbox((0, 0), tag, font=f_attr)
    draw.text((width_px - (bb[2] - bb[0]) - 8, height_px - (bb[3] - bb[1]) - 8),
              tag, fill="#999999", font=f_attr)
    return img


def _place_label(draw, X, Y, off, text, font, color, placed, W, H):
    """Draw a pin label in the first non-colliding spot: right, below,
    left, above. Real venue sets collide (Woodland HS vs the hub star)."""
    bb = draw.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    candidates = [(X + off, Y - th / 2), (X - tw / 2, Y + off + 2),
                  (X - off - tw, Y - th / 2), (X - tw / 2, Y - off - th - 4)]
    def _clash(box):
        if box[0] < 2 or box[1] < 2 or box[2] > W - 2 or box[3] > H - 2:
            return True
        return any(not (box[2] < b[0] or box[0] > b[2] or
                        box[3] < b[1] or box[1] > b[3]) for b in placed)
    for cx_, cy_ in candidates:
        box = (cx_ - 2, cy_ - 2, cx_ + tw + 2, cy_ + th + 2)
        if not _clash(box):
            break
    placed.append(box)
    draw.text((cx_, cy_), text, font=font, fill=color,
              stroke_width=3, stroke_fill="white")


def _short_name(venue):
    """'Woodland High School' -> 'Woodland HS' — map labels stay compact."""
    import re as _re
    n = _re.sub(r'\s+High School\b', ' HS', venue)
    n = _re.sub(r'\s+(College|Community College)\b', '', n)
    return n[:22]


def venue_map_for(hub, venues, height_px=680, min_aspect=1.35, max_aspect=2.35):
    """Geocode hub + venues (addresses -> pins numbered by drive-time order,
    matching the venue table) and return a PIL map image, or None.
    The frame's aspect adapts to the venue cluster's shape (clamped), so a
    tall cluster doesn't leave dead space on both sides - the page centers
    whatever width comes back."""
    pts = []
    hub_addr = hub.get("address") or hub.get("name", "")
    ll = geocode(hub_addr)
    if ll:
        pts.append({"lat": ll[0], "lon": ll[1], "label": "",
                    "name": hub.get("name", "")[:22]})
    ordered = sorted(venues, key=lambda v: v.get("drive_min", 999))
    hub_ll = ll
    for i, v in enumerate(ordered):
        # drive_minutes() already geocoded most venues — reuse its result
        ll = (v["lat"], v["lon"]) if v.get("lat") is not None else \
            venue_geocode(v, hub_ll)
        if ll:
            pts.append({"lat": ll[0], "lon": ll[1], "label": str(i + 1),
                        "name": _short_name(v.get("venue", ""))})
    real = [p for p in pts if p.get("lat") is not None]
    if not real:
        return None
    xs, ys = zip(*[_lonlat_to_xy(p["lon"], p["lat"], 0) for p in real])
    span_x, span_y = max(max(xs) - min(xs), 1e-9), max(max(ys) - min(ys), 1e-9)
    aspect = max(min_aspect, min(max_aspect, (span_x / 0.86) / (span_y / 0.76)))
    return build_map_image(pts, width_px=int(height_px * aspect),
                           height_px=height_px)


def drive_minutes(hub, venues):
    """Fill each venue's drive_min from the hub by real road routing
    (OSRM public server; geocodes are Nominatim, disk-cached). Venues that
    fail to geocode get no drive_min and sort last in the table."""
    hub_ll = geocode(hub.get("address") or hub.get("name", ""))
    if not hub_ll:
        # last resort: the hub's own city — approximate drive times beat a
        # map with no pins at all (a failed hub used to zero the whole page)
        m = re.search(r'([A-Za-z. ]+,?\s*[A-Z]{2})(?:\s+\d{5})?\s*$',
                      hub.get("address") or "")
        if m:
            hub_ll = geocode(m.group(1))
    if not hub_ll:
        return venues
    hub_name = re.sub(r'[^a-z0-9]', '', (hub.get("name") or "").lower())
    for v in venues:
        ll = venue_geocode(v, hub_ll)
        if not ll:
            # the venue that IS the hub (PG names the complex, not an
            # address: 'East Cobb Complex', 116 games) sits at the hub
            vn = re.sub(r'[^a-z0-9]', '', (v.get("venue") or "").lower())
            if hub_name and vn and (vn in hub_name or hub_name in vn):
                ll = hub_ll
            else:
                continue
        v["lat"], v["lon"] = ll
        if abs(ll[0] - hub_ll[0]) < 1e-6 and abs(ll[1] - hub_ll[1]) < 1e-6:
            v["drive_min"] = 0
            continue
        try:
            r = requests.get(
                f"https://router.project-osrm.org/route/v1/driving/"
                f"{hub_ll[1]},{hub_ll[0]};{ll[1]},{ll[0]}",
                params={"overview": "false"}, headers=_UA, timeout=20)
            r.raise_for_status()
            routes = r.json().get("routes") or []
            if routes:
                v["drive_min"] = int(round(routes[0]["duration"] / 60.0))
        except Exception:
            pass
        time.sleep(0.4)  # be polite to the public router
    return venues
