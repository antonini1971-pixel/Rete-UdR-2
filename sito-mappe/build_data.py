#!/usr/bin/env python3
"""Genera il sito della Rete UdR 2 dal GTFS.

Uso:
    python3 sito-mappe/build_data.py [percorso_gtfs.zip]

Senza argomento usa lo zip GTFS nella radice del repo; se ce n'è più di uno,
quello aggiunto/modificato per ultimo (secondo git, altrimenti per data file).

Riempie sito-mappe/template.html con i dati e scrive due copie identiche del sito,
un unico file HTML autonomo: sito-mappe/index.html (pubblicato online) e index.html
nella radice del repo (da aprire con un doppio clic).
"""
import csv
import datetime
import glob
import io
import json
import math
import os
import re
import subprocess
import sys
import zipfile
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
TITOLO = "Rete bus UdR 2"

# calendari imposti (al posto di calendar.txt; le eccezioni di calendar_dates.txt sono ignorate)
# service_id -> etichetta, giorni della settimana (0 = lunedì), validità
CALENDARI = {
    "udr2_10": ("Scolastico feriale", {0, 1, 2, 3, 4}, "20261012", "20270608"),
    "udr2_20": ("Scolastico sabato", {5}, "20261012", "20270608"),
}

# località scritte in testa al nome fermata ("FARA SABINA / Via Roma") con la grafia estesa;
# le altre diventano "Iniziali Maiuscole" (MONTEROTONDO -> Monterotondo)
LOCALITA = {
    "CIVITELLA S.P.": "Civitella San Paolo", "SANT'ANGELO": "Sant'Angelo Romano", "FIANO": "Fiano Romano",
    "MAGLIANO R.": "Magliano Romano", "MAZZANO": "Mazzano Romano", "RIGNANO": "Rignano Flaminio",
    "CAMPAGNANO": "Campagnano di Roma", "MONTOPOLI": "Montopoli di Sabina", "PALOMBARA": "Palombara Sabina",
    "CASTELNUOVO DI PORTO": "Castelnuovo di Porto", "PONZANO": "Ponzano Romano", "TORRITA": "Torrita Tiberina",
    "CANTALUPO": "Cantalupo in Sabina", "GUIDONIA": "Guidonia Montecelio",
}
NOMI_COMUNI = set(LOCALITA.values()) | {
    "Fara Sabina", "Monterotondo", "Poggio Mirteto", "Capena", "Sacrofano", "Formello", "Montelibretti",
    "Morlupo", "Riano", "Mentana", "Fonte Nuova", "Scandriglia", "Sant'Oreste", "Roma", "Casperia",
    "Poggio Catino", "Filacciano", "Nazzano", "Mompeo", "Salisano", "Nerola", "Nepi", "Roccantica",
    "Poggio Moiano", "Stimigliano",
}
# comune tra parentesi nei nomi fermata scritto in forma breve: "Via Tacito (Guidonia)"
ALIAS_COMUNI = {"Guidonia": "Guidonia Montecelio"}
# fermate il cui nome non indica il comune
COMUNE_FERMATA = {
    "Polo didattico Passo Corese": "Fara Sabina", "Stazione La Storta": "Roma", "Stazione di Cesano": "Roma",
    "Stazione di Guidonia": "Guidonia Montecelio", "Stazione di Pianabella Di Montelibretti": "Montelibretti",
}
PRINC_OGNI_MIN = 5      # almeno una fermata principale ogni 5 minuti di viaggio
PRINC_NODO_LINEE = 4    # nodo di interscambio: fermata servita da almeno 4 altre linee

NOTA_PRINCIPALI = ("Il GTFS non indica le fermate principali: qui sono i capolinea, la prima fermata "
                   "in ogni comune, i nodi serviti da almeno 4 altre linee e una fermata almeno ogni 5 minuti di viaggio.")

GIORNI = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]


def find_gtfs():
    zips = glob.glob(os.path.join(ROOT, "*.zip"))
    if not zips:
        raise SystemExit("Nessun file .zip GTFS trovato nella radice del repo.")

    def committed(path):
        try:
            out = subprocess.run(["git", "log", "-1", "--format=%ct", "--", os.path.basename(path)],
                                 cwd=ROOT, capture_output=True, text=True).stdout.strip()
            return int(out) if out else float("inf")  # non ancora in git: è il più recente
        except OSError:
            return 0

    return max(zips, key=lambda z: (committed(z), os.path.getmtime(z)))


def read(zf, name):
    if name not in zf.namelist():
        return []
    with zf.open(name) as f:
        return list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))


def natural(code):
    """'1D' -> (1, 'D'): ordina 1, 1D, 2, … 10 invece di 1, 10, 1D, 2."""
    m = re.match(r"(\d*)(.*)", code)
    return (int(m.group(1)) if m.group(1) else 10**6, m.group(2))


def split_stop_name(name):
    """'FARA SABINA /  Via Roma' -> ('Via Roma', 'Fara Sabina'); 'Via Tacito (Guidonia)' -> ('Via Tacito', 'Guidonia Montecelio')."""
    name = re.sub(r"\s+", " ", name.strip())
    if name in COMUNE_FERMATA:
        return (name, COMUNE_FERMATA[name])
    m = re.match(r"^([A-Z][A-Z' .]+?)\s*[/|]\s*(.+)$", name)
    if m:
        loc = LOCALITA.get(m.group(1).strip(), m.group(1).strip().title())
        rest = m.group(2).strip()
        return (rest[:1].upper() + rest[1:], loc)
    m = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", name)
    if m:
        com = ALIAS_COMUNI.get(m.group(2), m.group(2))
        if com in NOMI_COMUNI:
            return (m.group(1), com)
    m = re.match(r"^Stazione di (.+?)(-.*)?$", name)
    if m and m.group(1) in NOMI_COMUNI:
        return (name, m.group(1))
    m = re.match(r"^(.+?) \(", name)  # "Stimigliano (St.ne FS)", "Poggio Moiano (SS 4 / Osteria Nuova)"
    if m and m.group(1) in NOMI_COMUNI:
        return (name, m.group(1))
    if name in NOMI_COMUNI:
        return (name, name)
    return (name, "")


def minutes(t):
    # orari al minuto (hh:mm): i secondi si troncano, 06:54:30 -> 06:54
    h, m, _ = (int(x) for x in t.split(":"))
    return h * 60 + m


def encode_polyline(points):
    out, plat, plon = [], 0, 0
    for lat, lon in points:
        ilat, ilon = round(lat * 1e5), round(lon * 1e5)
        for v in (ilat - plat, ilon - plon):
            v = ~(v << 1) if v < 0 else v << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1f)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        plat, plon = ilat, ilon
    return "".join(out)


def simplify(points, tol_m=5.0):
    """Douglas-Peucker in metri."""
    if len(points) < 3:
        return points
    kx = 111320 * math.cos(math.radians(points[0][0]))
    xy = [(p[1] * kx, p[0] * 110540) for p in points]
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = xy[a], xy[b]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        best, idx = -1.0, -1
        for i in range(a + 1, b):
            px, py = xy[i]
            t = 0 if L2 == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L2))
            d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if d > best:
                best, idx = d, i
        if best > tol_m:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(points, keep) if k]


def line_colors(n):
    # colori distinti, abbastanza scuri da reggere il testo bianco del riquadro linea
    def hsl(h, s, l):
        s, l = s / 100, l / 100
        c = (1 - abs(2 * l - 1)) * s
        x = c * (1 - abs((h / 60) % 2 - 1))
        m = l - c / 2
        r, g, b = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][int(h // 60) % 6]
        return "#%02X%02X%02X" % tuple(round((v + m) * 255) for v in (r, g, b))
    return [hsl((i * 137.508) % 360, 70, 40) for i in range(n)]


def service_label(weekdays):
    """Insieme di giorni della settimana -> 'Lunedì–Venerdì', 'Sabato', 'Domenica e festivi', …"""
    ds = sorted(weekdays)
    if not ds:
        return "Nessun giorno"
    if ds == [6]:
        return "Domenica e festivi"
    runs, start = [], ds[0]
    for a, b in zip(ds, ds[1:] + [None]):
        if b != a + 1:
            runs.append((start, a))
            start = b
    parts = [GIORNI[a] if a == b else (f"{GIORNI[a]} e {GIORNI[b]}" if b == a + 1 else f"{GIORNI[a]}–{GIORNI[b]}")
             for a, b in runs]
    return ", ".join(parts)


def ymd(d):
    return d.strftime("%Y%m%d")


def build(zpath):
    zf = zipfile.ZipFile(zpath)
    agency = (read(zf, "agency.txt") or [{}])[0]
    routes = read(zf, "routes.txt")
    stops = {s["stop_id"]: s for s in read(zf, "stops.txt")}
    trips = read(zf, "trips.txt")

    st_by_trip = defaultdict(list)
    for r in read(zf, "stop_times.txt"):
        st_by_trip[r["trip_id"]].append(r)
    for v in st_by_trip.values():
        v.sort(key=lambda r: int(r["stop_sequence"]))
    trips = [t for t in trips if st_by_trip.get(t["trip_id"])]

    # ---- calendari: imposti da CALENDARI, senza eccezioni
    servizi = {}
    for svc, (label, wd, dal, al) in CALENDARI.items():
        d = datetime.datetime.strptime(dal, "%Y%m%d").date()
        end = datetime.datetime.strptime(al, "%Y%m%d").date()
        ds = []
        while d <= end:
            if d.weekday() in wd:
                ds.append(ymd(d))
            d += datetime.timedelta(days=1)
        servizi[svc] = {"label": label, "dal": ds[0], "al": ds[-1], "esclusi": [],
                        "date": ds, "giorni": len(ds), "scol": True}
    used_svc = [s for s in CALENDARI if any(t["service_id"] == s for t in trips)]
    servizi = {s: servizi[s] for s in used_svc}
    labels = Counter(v["label"] for v in servizi.values())
    for s, v in servizi.items():  # due calendari con la stessa etichetta: si distinguono col codice
        if labels[v["label"]] > 1:
            v["label"] += f" ({s})"
    trips = [t for t in trips if t["service_id"] in servizi]

    # ---- fermate usate
    used_stops = sorted({r["stop_id"] for t in trips for r in st_by_trip[t["trip_id"]]},
                        key=lambda sid: split_stop_name(stops[sid]["stop_name"])[::-1])
    stop_idx = {sid: i for i, sid in enumerate(used_stops)}
    fermate = []
    for sid in used_stops:
        s = stops[sid]
        nome, loc = split_stop_name(s["stop_name"])
        fermate.append([s.get("stop_code") or sid, nome, loc, round(float(s["stop_lat"]), 6), round(float(s["stop_lon"]), 6)])

    # ---- percorsi
    pts = defaultdict(list)
    for r in read(zf, "shapes.txt"):
        pts[r["shape_id"]].append((int(r["shape_pt_sequence"]), float(r["shape_pt_lat"]), float(r["shape_pt_lon"]),
                                   float(r.get("shape_dist_traveled") or 0)))
    shapes, shape_km = {}, {}
    for sid in sorted({t["shape_id"] for t in trips}):
        seq = sorted(pts.get(sid, []))
        line = [(p[1], p[2]) for p in seq]
        km = seq[-1][3] / 1000 if seq and seq[-1][3] else 0
        if not km and len(line) > 1:  # senza shape_dist_traveled: lunghezza geometrica
            kx = 111.32 * math.cos(math.radians(line[0][0]))
            km = sum(math.hypot((b[1] - a[1]) * kx, (b[0] - a[0]) * 110.54) for a, b in zip(line, line[1:]))
        shapes[sid] = encode_polyline(simplify(line))
        shape_km[sid] = round(km, 1)

    # ---- linee
    route_lines = defaultdict(set)  # fermata -> linee che la servono (per le fermate di interscambio)
    for t in trips:
        for r in st_by_trip[t["trip_id"]]:
            route_lines[r["stop_id"]].add(t["route_id"])

    # comune principale di ogni linea (quello con più passaggi) e comuni serviti
    passaggi = defaultdict(Counter)
    for t in trips:
        for r in st_by_trip[t["trip_id"]]:
            com = split_stop_name(stops[r["stop_id"]]["stop_name"])[1]
            if com:
                passaggi[t["route_id"]][com] += 1
    area = {rid: c.most_common(1)[0][0] for rid, c in passaggi.items()}
    routes = sorted(routes, key=lambda r: natural(r["route_short_name"]))
    colors = line_colors(len(routes))
    linee = []
    for ri, r in enumerate(routes):
        rtrips = [t for t in trips if t["route_id"] == r["route_id"]]
        if not rtrips:
            continue
        tabs = []
        groups = defaultdict(list)
        for t in rtrips:
            groups[(t["service_id"], t["direction_id"] or "0")].append(t)
        for (svc, d), ts in sorted(groups.items(), key=lambda kv: (used_svc.index(kv[0][0]), kv[0][1])):
            tabs.append(make_tab(svc, d, ts, st_by_trip, stops, stop_idx, route_lines))
        color = (r.get("route_color") or "").strip()
        shp = sorted({t["shape_id"] for t in rtrips})
        linee.append({
            "id": r["route_short_name"], "n": r["route_short_name"], "nome": r["route_long_name"] or r["route_short_name"],
            "area": area.get(r["route_id"], ""), "comuni": sorted(passaggi[r["route_id"]]), "col": "#" + color.upper() if color else colors[ri],
            "shapes": shp, "km": max(shape_km[s] for s in shp), "tab": tabs,
        })

    linee.sort(key=lambda l: (l["area"], natural(l["n"])))
    all_dates = [d for v in servizi.values() for d in v["date"]]
    ver = re.search(r"(\d{8})T(\d{4})", os.path.basename(zpath))
    return {
        "agenzia": {"nome": agency.get("agency_name", ""), "url": agency.get("agency_url", ""),
                    "tel": agency.get("agency_phone", "")},
        "feed": {"dal": min(all_dates), "al": max(all_dates),
                 "versione": (f"esportato il {ver.group(1)[6:]}/{ver.group(1)[4:6]}/{ver.group(1)[:4]} "
                              f"alle {ver.group(2)[:2]}:{ver.group(2)[2:]}") if ver else "",
                 "file": os.path.basename(zpath)},
        "servizi": servizi, "fermate": fermate, "shapes": shapes, "shape_km": shape_km, "linee": linee,
        "nota_principali": NOTA_PRINCIPALI,
    }


def make_tab(svc, d, ts, st_by_trip, stops, stop_idx, route_lines):
    """Quadro orario di una direzione: righe = unione ordinata delle fermate di tutte le corse."""
    # chiave (fermata, n-esima occorrenza): le circolari passano due volte dalla stessa fermata
    def keyed(t):
        seen = Counter()
        out = []
        for r in st_by_trip[t["trip_id"]]:
            out.append((r["stop_id"], seen[r["stop_id"]]))
            seen[r["stop_id"]] += 1
        return out
    ts = sorted(ts, key=lambda t: minutes(st_by_trip[t["trip_id"]][0]["departure_time"]))
    ks = [keyed(t) for t in ts]
    main = Counter(tuple(k) for k in ks).most_common()
    main = max(main, key=lambda kv: (kv[1], len(kv[0])))[0]
    rows = list(main)
    for k in ks:
        prev = -1
        for key in k:
            if key in rows:
                at = rows.index(key)
                if at > prev:
                    prev = at
            else:
                rows.insert(prev + 1, key)
                prev += 1
    pos = {key: i for i, key in enumerate(rows)}

    corse = []
    for t, k in zip(ts, ks):
        o = [None] * len(rows)
        for key, r in zip(k, st_by_trip[t["trip_id"]]):
            o[pos[key]] = minutes(r["departure_time"] or r["arrival_time"])
        corse.append({"id": t.get("trip_short_name") or t["trip_id"], "shape": t["shape_id"], "o": o})

    # fermate principali (il GTFS non le indica: timepoint è sempre 1)
    princ = [0] * len(rows)
    for c in corse:  # capolinea di ogni corsa
        served = [i for i, v in enumerate(c["o"]) if v is not None]
        princ[served[0]] = princ[served[-1]] = 1
    route_id = ts[0]["route_id"]
    last_com = None
    for i, (sid, _) in enumerate(rows):
        com = split_stop_name(stops[sid]["stop_name"])[1]
        if com in NOMI_COMUNI:
            if last_com and com != last_com:  # ingresso in un altro comune
                princ[i] = 1
            last_com = com
        if len(route_lines[sid] - {route_id}) >= PRINC_NODO_LINEE:
            princ[i] = 1
    longest = max(corse, key=lambda c: sum(v is not None for v in c["o"]))
    last_t = None
    for i, v in enumerate(longest["o"]):
        if v is None:
            continue
        if princ[i] or last_t is None or v - last_t >= PRINC_OGNI_MIN:
            princ[i] = 1
            last_t = v

    heads = Counter(t["trip_headsign"].strip() for t in ts if t["trip_headsign"].strip())
    last = split_stop_name(stops[rows[-1][0]]["stop_name"])[0]
    titolo = heads.most_common(1)[0][0] if heads else last
    titolo = re.sub(r"\s*\((Andata|Ritorno)\)\s*$", "", titolo)
    return {"svc": svc, "dir": d, "titolo": titolo, "fermate": [stop_idx[sid] for sid, _ in rows],
            "princ": princ, "corse": corse}


def main():
    zpath = sys.argv[1] if len(sys.argv) > 1 else find_gtfs()
    print(f"GTFS: {os.path.basename(zpath)}")
    data = build(zpath)
    with open(os.path.join(HERE, "template.html"), encoding="utf-8") as f:
        html = f.read()
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    for old, new in (("/*DATI*/null", blob), ("/*TITOLO*/", TITOLO)):
        if old not in html:
            raise SystemExit(f"Segnaposto {old} non trovato in template.html")
        html = html.replace(old, new)
    for out in (os.path.join(HERE, "index.html"), os.path.join(ROOT, "index.html")):
        with open(out, "w", encoding="utf-8") as f:
            f.write(html)
    n = sum(len(t["corse"]) for l in data["linee"] for t in l["tab"])
    print(f"index.html: {len(html.encode()) / 1024:.0f} KB — {len(data['linee'])} linee, {len(data['fermate'])} fermate, "
          f"{n} corse, dal {data['feed']['dal']} al {data['feed']['al']}")


if __name__ == "__main__":
    main()
