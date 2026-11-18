"""Stage C1 screenshots + checks for the Satelītu monitorings workspace (sandbox only; GETs, no review / add POSTs).

Usage: <python with playwright> -I scripts/verify_sat_workspace_c1.py BASE CREDS_FILE OUT_DIR [BASE_503]
CREDS_FILE: two lines (user, password), never printed. OUT_DIR: docs/evidence/satellite-stage5-v3/c1 (not versioned).
Prints a JSON report; exit 0 = every check passed.
"""
import json
import re
import sys

from playwright.sync_api import sync_playwright

BAD_TEXT = ['undefined', 'NaN', '[object Object]', 'null ha', 'null %']


def main():
    base, creds, out = sys.argv[1], sys.argv[2], sys.argv[3]
    base503 = sys.argv[4] if len(sys.argv) > 4 else None
    user, pw = open(creds).read().split('\n', 1)
    rep = {'checks': {}, 'fail': [], 'console_errors': [], 'shots': [], 'dialogs': []}

    def check(name, ok, detail=None):
        rep['checks'][name] = {'ok': bool(ok), 'detail': detail}
        if not ok:
            rep['fail'].append(name)

    with sync_playwright() as p:
        b = p.chromium.launch()

        def page(w, h, lang, route_health=None):
            ctx = b.new_context(http_credentials={'username': user.strip(), 'password': pw.strip()}, viewport={'width': w, 'height': h})
            ctx.add_init_script("try{localStorage.setItem('satMonitoring.lang','%s');localStorage.setItem('satWorkspace.hintWhatHere','1')}catch(e){}" % lang)
            pg = ctx.new_page()
            pg.on('console', lambda m: m.type == 'error' and rep['console_errors'].append(f'{w}x{h}/{lang}: {m.text}'))
            pg.on('dialog', lambda d: (rep['dialogs'].append(d.message), d.dismiss()))
            if route_health:
                pg.route('**/api/sat-monitoring/health', route_health)
            return ctx, pg

        def wait(pg, ms=1800):
            pg.wait_for_load_state('networkidle'); pg.wait_for_timeout(ms)

        def shot(pg, name):
            path = f'{out}/{name}.png'; pg.screenshot(path=path); rep['shots'].append(name)

        def text_ok(pg, name):
            txt = pg.locator('#satm-root').inner_text()
            bad = [x for x in BAD_TEXT if x in txt]
            check(f'{name}: no undefined/NaN/null text', not bad, bad)
            return txt

        for (w, h) in ((1440, 900), (1920, 1080)):
            for lang in ('lv', 'en'):
                tag = f'{w}x{h}-{lang}'
                ctx, pg = page(w, h, lang)
                # 1 Teritorija default
                pg.goto(f'{base}/#sat-monitoring'); wait(pg, 3500)
                shot(pg, f'01-teritorija-{tag}')
                txt = text_ok(pg, f'teritorija {tag}')
                imgs = pg.evaluate("document.querySelectorAll('#satw-map img.leaflet-image-layer').length")
                check(f'teritorija {tag}: Sentinel overlays on the map', imgs >= 1, imgs)
                z = pg.evaluate("window.SatWorkspace.state.map.getZoom()")
                check(f'teritorija {tag}: not country zoom', z >= 11, z)
                cards = pg.evaluate("[...document.querySelectorAll('.satw-card .satw-card-f')].map(c=>c.textContent)")
                check(f'teritorija {tag}: every area card shows its last acquisition date', cards and all(re.search(r'\d{2}\.\d{2}\.\d{4}|\d{4}-\d{2}-\d{2}', c) for c in cards), cards)
                check(f'teritorija {tag}: status bar', ('Copernicus' in txt) and ('4 800' in txt or '4800' in txt), None)
                if lang == 'lv':
                    check(f'teritorija {tag}: tabs LV', all(x in txt for x in ['Teritorija', 'Izmaiņas', 'Pierādījumi']), None)
                # 2 Izmaiņas #62 — swipe at 3 positions, side, change-only
                pg.goto(f'{base}/#sat-monitoring?event=62'); wait(pg, 1500)
                pg.wait_for_selector('#satw-card .satw-eyebrow', timeout=30000); pg.wait_for_selector('.satw-pill', timeout=30000); pg.wait_for_timeout(1500)
                pressed = pg.evaluate("[...document.querySelectorAll('[data-mode]')].map(b=>[b.dataset.mode,b.getAttribute('aria-pressed'),b.disabled])")
                check(f'#62 {tag}: swipe active by default', ['swipe', 'true', False] in [list(x) for x in pressed], pressed)
                card = pg.locator('#satw-card').inner_text()
                check(f'#62 {tag}: quality badge with source', ('S1' in card and ('radara' in card or 'radar' in card)), card[:400])
                pills = pg.evaluate("[...document.querySelectorAll('.satw-pill')].map(p=>p.textContent)")
                check(f'#62 {tag}: PIRMS/PĒC pills', len(pills) == 2 and '2026' in pills[0] and '2026' in pills[1], pills)
                hd = pg.locator('.satw-handle'); hd.focus(); pg.keyboard.press('Home')
                for pos, n in ((25, 5), (50, 5), (75, 5)):
                    for _ in range(n):
                        pg.keyboard.press('ArrowRight')
                    pg.wait_for_timeout(300)
                    st = pg.evaluate("""()=>{const mw=document.getElementById('satw-mapwrap'),r=mw.getBoundingClientRect(),
                      ims=[...mw.querySelectorAll('img.leaflet-image-layer')].map(i=>{const b=i.getBoundingClientRect();return [b.x,b.y,b.width,b.height].map(v=>Math.round(v))});
                      const pane=mw.querySelector('.leaflet-satwAfter-pane'),m=new DOMMatrixReadOnly(getComputedStyle(mw.querySelector('.leaflet-map-pane')).transform);
                      const c=(pane.style.clip.match(/-?[\\d.]+/g)||[]).map(Number);const d=mw.querySelector('.satw-divider').getBoundingClientRect();
                      return {ims, clipLeft:c[3]+m.m41, divider:d.x-r.x, pills:[...mw.querySelectorAll('.satw-divider .satw-pill')].map(p=>p.getBoundingClientRect().x-r.x)}}""")
                    check(f'#62 {tag}: swipe {pos}% aligned + clip at divider', len(st['ims']) == 2 and st['ims'][0] == st['ims'][1] and abs(st['clipLeft'] - st['divider']) < 1.5, st)
                    shot(pg, f'02-izmainas-62-swipe{pos}-{tag}')
                # owner C1 review: true-colour pair hint (never switched silently)
                srcs0 = pg.evaluate("[...document.querySelectorAll('#satw-mapwrap img.leaflet-image-layer')].map(i=>i.getAttribute('src'))")
                hint = pg.locator('[data-act=tc-pair]')
                htxt = hint.inner_text() if hint.count() else ''
                check(f'#62 {tag}: true-colour pair hint offered, default still false colour',
                      hint.count() == 1 and ('29.06.2026' in htxt or '2026-06-29' in htxt) and ('21.08.2026' in htxt or '2026-08-21' in htxt)
                      and all('/quicklook' in x for x in srcs0), [htxt, srcs0])
                if hint.count():
                    hint.click(); wait(pg, 2500)
                    srcs1 = pg.evaluate("[...document.querySelectorAll('#satw-mapwrap img.leaflet-image-layer')].map(i=>i.getAttribute('src'))")
                    pills1 = pg.evaluate("[...document.querySelectorAll('.satw-pill')].filter(p=>!p.hidden&&p.offsetParent).map(p=>p.textContent)")
                    card1 = pg.locator('#satw-card').inner_text()
                    check(f'#62 {tag}: after switch true colour 299 → 331 on map, pills and card',
                          any('/299/truecolor' in x for x in srcs1) and any('/331/truecolor' in x for x in srcs1)
                          and any('29.06.2026' in x or '2026-06-29' in x for x in pills1) and any('21.08.2026' in x or '2026-08-21' in x for x in pills1)
                          and 'S2A_MSIL2A_20260629T094121' in card1 and 'S2B_MSIL2A_20260821T094029' in card1
                          and pg.locator('[data-act=tc-pair]').count() == 0, [srcs1, pills1, card1[-400:]])
                    if (w, h, lang) == (1440, 900, 'lv'):
                        shot(pg, f'15-izmainas-62-truecolour-pair-after-hint-{tag}')
                pg.click('[data-mode=side]'); wait(pg, 2200); shot(pg, f'03-izmainas-62-side-{tag}')
                n2 = pg.evaluate("document.querySelectorAll('#satw-map2 img.leaflet-image-layer').length")
                check(f'#62 {tag}: side-by-side two maps', n2 == 1, n2)
                pg.click('[data-mode=change]'); wait(pg, 1500); shot(pg, f'04-izmainas-62-change-{tag}')
                n0 = pg.evaluate("document.querySelectorAll('#satw-mapwrap img.leaflet-image-layer').length")
                check(f'#62 {tag}: change-only has no Sentinel image', n0 == 0, n0)
                text_ok(pg, f'#62 {tag}')
                if (w, h) == (1440, 900):
                    # timeline tooltip + timeline click + stepper
                    pg.click('[data-mode=change]'); wait(pg, 800)
                    g = pg.locator('#satw-tl g.acq[data-state=ok]').last; g.hover(); pg.wait_for_timeout(400)
                    tip = pg.locator('#satw-tip').inner_text()
                    check(f'timeline tooltip {tag}', 'UTC' in tip and ('S1' in tip or 'S2' in tip), tip)
                    shot(pg, f'05-timeline-tooltip-{tag}')
                    before = pg.evaluate("window.SatWorkspace.state.acq && window.SatWorkspace.state.acq.acq_id")
                    pg.locator('#satw-card [data-act=close]').click(); wait(pg, 800)
                    pg.locator('#satw-tl g.acq[data-state=ok]').nth(3).click(); wait(pg, 1200)
                    after = pg.evaluate("window.SatWorkspace.state.acq && window.SatWorkspace.state.acq.acq_id")
                    step_txt = pg.locator('.satw-stepper').inner_text()
                    check(f'timeline click changes acquisition + stepper {tag}', after and after != before, [before, after, step_txt])
                    shot(pg, f'06-acq-via-timeline-{tag}')
                    pg.locator('[data-step="-1"]').click(); wait(pg, 1200)
                    after2 = pg.evaluate("window.SatWorkspace.state.acq && window.SatWorkspace.state.acq.acq_id")
                    img = pg.evaluate("[...document.querySelectorAll('#satw-mapwrap img.leaflet-image-layer')].map(i=>i.getAttribute('src'))")
                    check(f'stepper changes acquisition + map image {tag}', after2 != after and any(f'/{after2}/' in s for s in img), [after, after2, img])
                    shot(pg, f'07-acq-via-stepper-{tag}')
                    # true-colour fallback never mixed: event 60 default pair 299 → 325 (325 has no true colour)
                    pg.goto(f'{base}/#sat-monitoring?event=60'); wait(pg, 1500)
                    pg.wait_for_selector('#satw-card .satw-eyebrow', timeout=30000); pg.wait_for_timeout(1500)
                    srcs = pg.evaluate("[...document.querySelectorAll('#satw-mapwrap img.leaflet-image-layer')].map(i=>i.getAttribute('src'))")
                    kinds = sorted(set(s.split('?')[0].rsplit('/', 1)[-1] for s in srcs))
                    note = pg.locator('#satw-composites').inner_text()
                    check(f'#60 {tag}: composites never mixed (fallback false colour both sides + note)', len(kinds) == 1, [srcs, note])
                    shot(pg, f'08-izmainas-60-falsecolour-both-{tag}')
                    # Pierādījumi tab (existing page)
                    pg.click('[data-tab=evidence]'); wait(pg, 3000); shot(pg, f'09-pieradijumi-62-{tag}')
                    check(f'pierādījumi {tag}: legacy page rendered', pg.locator('#satm-evidence').inner_text().strip() != '', None)
                # 3 BIK-001 (no events)
                pg.goto(f'{base}/#sat-monitoring?area=1'); wait(pg, 3000); shot(pg, f'10-izmainas-bik001-{tag}')
                txt = text_ok(pg, f'BIK-001 {tag}')
                check(f'BIK-001 {tag}: honest no-change state', ('nav iespējamo izmaiņu' in txt) or ('No suspected change' in txt), None)
                check(f'BIK-001 {tag}: no event card', pg.locator('#satw-card').is_hidden(), None)
                # 4 Kas šeit? inside (Ķekava centre) and outside monitoring (a real VMD compartment), via coordinate search
                pg.goto(f'{base}/#sat-monitoring'); wait(pg, 2500)
                pg.fill('#satw-q', '56,8390 24,1500'); pg.press('#satw-q', 'Enter'); wait(pg, 3500)
                pop = pg.locator('.satw-what').inner_text()
                check(f'Kas šeit inside {tag}', ('Kekava' in pop or 'Ķekava' in pop) and ('56.83900' in pop), pop[:300])
                shot(pg, f'11-kas-seit-inside-{tag}')
                pg.fill('#satw-q', '56.65949, 24.20804'); pg.press('#satw-q', 'Enter'); wait(pg, 3500)
                pop = pg.locator('.satw-what').inner_text()
                check(f'Kas šeit outside {tag}', ('40640040054' in pop) and (('netiek uzraudzīta' in pop) or ('not monitored' in pop)), pop[:300])
                shot(pg, f'12-kas-seit-outside-{tag}')
                btn = pg.locator('.satw-what-add button')
                pg.wait_for_timeout(800)
                if btn.is_enabled():
                    btn.click(); pg.wait_for_timeout(500)          # dialog is dismissed → no POST
                    d = rep['dialogs'][-1] if rep['dialogs'] else ''
                    check(f'add confirm {tag}: cost "not available" + month vs guard, dismissed', ('Nav pieejams' in d or 'Not available' in d) and ('PU' in d), d)
                ctx.close()
        # 5 Copernicus degraded (SYNTHETIC /health in the browser only) and satellite.db 503 (real, second sandbox)
        def degraded(route):
            r = route.fetch(); d = r.json()
            d['provider'] = dict(d.get('provider') or {}, state='DEGRADED', auth_failure=True,
                                 error='HTTP 401 invalid_client — SYNTHETIC test response (sandbox screenshot only)')
            route.fulfill(response=r, json=d)
        ctx, pg = page(1440, 900, 'lv', degraded)
        pg.goto(f'{base}/#sat-monitoring'); wait(pg, 3000)
        pg.click('.satw-cop'); pg.wait_for_timeout(300)
        check('Copernicus degraded: compact red indicator with detail', pg.locator('.satw-cop.bad').count() == 1 and 'SYNTHETIC' in pg.locator('#satw-cop-detail').inner_text(), None)
        shot(pg, '13-copernicus-degraded-SYNTHETIC-1440x900-lv'); ctx.close()
        if base503:
            ctx, pg = page(1440, 900, 'lv')
            pg.goto(f'{base503}/#sat-monitoring'); wait(pg, 2500)
            t = pg.locator('#satm-root').inner_text()
            check('satellite.db 503: honest error view', 'satellite.db' in t, t[:200])
            shot(pg, '14-satellite-db-503-1440x900-lv'); ctx.close()
        b.close()
    errs = [e for e in rep['console_errors'] if '503' not in e]          # the 503 sandbox logs its failed fetches on purpose
    check('no console errors (except the intentional 503 sandbox)', not errs, errs[:10])
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    sys.exit(1 if rep['fail'] else 0)


if __name__ == '__main__':
    main()
