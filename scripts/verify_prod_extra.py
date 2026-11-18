"""Production read-only checks beside verify_sat_workspace_c1.py: Teritorija default area name, Sectors cards,
Forest Map sat_event link, LVM GEO button hook, RM / Ingka instances. GETs only. Usage: BASE CREDS_FILE OUT_DIR"""
import json
import sys
import urllib.request

from playwright.sync_api import sync_playwright


def main():
    base, creds, out = sys.argv[1], sys.argv[2], sys.argv[3]
    user, pw = open(creds).read().split('\n', 1)
    rep = {'checks': {}, 'fail': [], 'console_errors': []}

    def check(n, ok, d=None):
        rep['checks'][n] = {'ok': bool(ok), 'detail': d}
        if not ok:
            rep['fail'].append(n)
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(http_credentials={'username': user.strip(), 'password': pw.strip()}, viewport={'width': 1440, 'height': 900})
        ctx.add_init_script("try{localStorage.setItem('satMonitoring.lang','lv');localStorage.setItem('satWorkspace.hintWhatHere','1')}catch(e){}")
        pg = ctx.new_page(); pg.on('console', lambda m: m.type == 'error' and rep['console_errors'].append(m.text))
        pg.goto(base + '/#sat-monitoring'); pg.wait_for_load_state('networkidle'); pg.wait_for_timeout(3500)
        z = pg.evaluate("window.SatWorkspace.state.map.getZoom()")
        cards = pg.locator('.satw-card').all_inner_texts()
        check('Teritorija: Ķekava–Baloži card + imagery, not country zoom', any('Ķekava–Baloži' in c for c in cards) and z >= 11 and
              pg.evaluate("document.querySelectorAll('#satw-map img.leaflet-image-layer').length") >= 1, [z, [c[:30] for c in cards]])
        pg.screenshot(path=f'{out}/prod-01-teritorija.png')
        pg.goto(base + '/#sat-monitoring?event=62'); pg.wait_for_selector('#satw-card .satw-eyebrow', timeout=30000); pg.wait_for_timeout(2000)
        card = pg.locator('#satw-card').inner_text()
        check('#62 badge "Laba — no radara (S1) 29.07.; optiskie: ierobežota"', 'Laba' in card and 'no radara (S1) 29.07.' in card and 'optiskie: ierobežota' in card, card[:500])
        check('#62 true-colour hint offered', pg.locator('[data-act=tc-pair]').count() == 1, None)
        pg.screenshot(path=f'{out}/prod-02-event62.png')
        pg.goto(base + '/#sectors'); pg.wait_for_load_state('networkidle'); pg.wait_for_timeout(3000)
        n = pg.evaluate("document.querySelectorAll('[class*=sc-card], .sc-card').length")
        check('Sectors cards render', n > 0, n); pg.screenshot(path=f'{out}/prod-03-sectors.png')
        pg.goto(base + '/#forest-map?sat_event=62'); pg.wait_for_load_state('networkidle'); pg.wait_for_timeout(5000)
        fm = pg.evaluate("({active: document.getElementById('sec-forest-map').classList.contains('active'), sat: !!window.ForestMapSat, hash: location.hash})")
        check('Forest Map sat_event=62 link opens Forest Map with the satellite layer module', fm['active'] and fm['sat'], fm)
        pg.screenshot(path=f'{out}/prod-04-forestmap-sat62.png')
        pg.goto(base + '/#lvm-geodata'); pg.wait_for_load_state('networkidle'); pg.wait_for_timeout(3000)
        lv = pg.evaluate("({hook: typeof (window.SatMonitoring||{}).lvmButton, legacy: typeof ((window.SatMonitoring||{})._legacy||{}).lvmButton, active: document.getElementById('sec-lvm-geodata').classList.contains('active')})")
        check('LVM GEO page + add-to-monitoring button hook', lv['active'] and lv['hook'] == 'function', lv)
        b.close()
    for host in ('https://rm.forestaisystems.com/', 'https://ingka.forestaisystems.com/'):
        try:
            st = urllib.request.urlopen(urllib.request.Request(host), timeout=30).status
        except urllib.error.HTTPError as e:
            st = e.code
        except Exception as e:
            st = type(e).__name__
        check(f'{host} loads (401 login or 200)', st in (200, 401), st)
    check('no console errors', not rep['console_errors'], rep['console_errors'][:8])
    print(json.dumps(rep, ensure_ascii=False, indent=1)); sys.exit(1 if rep['fail'] else 0)


if __name__ == '__main__':
    main()
