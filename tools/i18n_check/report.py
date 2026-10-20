"""List on-screen strings still in Russian or English after the i18n layer.
Usage: python3 report.py <crawl.json>"""
import json, re, sys
d = json.load(open(sys.argv[1]))
LV = re.compile('[āēīūčšžņļģķĀĒĪŪČŠŽŅĻĢĶ]')
EN = re.compile(r"\b(the|and|not|yet|no|all|add|new|save|sector|risk|risks|status|view|back|details|loading|approved|"
                r"active|worker|workers|report|reports|photo|photos|vehicle|map|level|reason|name|type|date|time|note|"
                r"comment|area|volume|satellite|machine|fleet|generic|road|access|zone|already|confirmed|vendor|planned|"
                r"failed|error|search|click|open|close|total|registered|minimum|session|required|logged)\b", re.I)
KEEP = re.compile(r'OpenStreetMap|JavaScript library|Leaflet|PONSSE|Komatsu|John Deere|Maxar|ICEYE|SkySat|PlanetScope|'
                  r'Landsat|ZF SCALAR|LVM GEO|TIMBRO Forest Audit|KRAUZERS Fleet GPS|ESA/Copernicus|USGS/NASA|Forest AI demo')
left = {}
for page, texts in d['pages'].items():
    for t in texts:
        core = re.sub(r'^@[\w-]+: ', '', t)
        if re.search('[А-Яа-яЁё]', core) or (EN.search(core) and not KEEP.search(core) and not LV.search(core)) \
                or re.fullmatch(r'[A-Z][A-Z_]{4,}', core):
            left.setdefault(t, set()).add(page)
for t, pages in sorted(left.items()):
    print(f"{t[:140]}\t[{','.join(sorted(pages))[:60]}]")
print(f"--- {len(left)} candidate(s); JS errors: {d['errors']}")
