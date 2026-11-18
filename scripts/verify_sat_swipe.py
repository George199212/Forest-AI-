"""Browser check for the satellite swipe fix (D7) and Forest Map coordinate search (D6). Read-only (GETs only).

Usage: <python with playwright> -I scripts/verify_sat_swipe.py BASE_URL CREDS_FILE OUT_DIR [EVENT_ID]
CREDS_FILE: two lines, user and password (never printed). Screenshots go to OUT_DIR (not versioned).
Exit code 0 = every check passed. Prints a JSON report.
"""
import json
import sys
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

STATE = """() => {
  const d = document.getElementById('satm-swipe'); if (!d) return null;
  const r = d.getBoundingClientRect();
  const imgs = [...d.querySelectorAll('img.leaflet-image-layer')].map(i => { const b = i.getBoundingClientRect();
    return {pane: i.parentElement.className, x: +(b.x - r.x).toFixed(2), y: +(b.y - r.y).toFixed(2), w: +b.width.toFixed(2), h: +b.height.toFixed(2)}; });
  const pane = d.querySelector('.leaflet-satmAfter-pane'), mp = d.querySelector('.leaflet-map-pane');
  const m = new DOMMatrixReadOnly(getComputedStyle(mp).transform);
  const c = (pane.style.clip.match(/-?[\\d.]+/g) || []).map(Number);       // rect(top, right, bottom, left)
  const line = d.querySelector('.satm-swipe-divider'), lb = line.getBoundingClientRect();
  const poly = [...d.querySelectorAll('.leaflet-overlay-pane path')].map(p => p.getBoundingClientRect())
    .reduce((a, b) => ({l: Math.min(a.l, b.left - r.x), t: Math.min(a.t, b.top - r.y), r: Math.max(a.r, b.right - r.x), b: Math.max(a.b, b.bottom - r.y)}),
            {l: 1e9, t: 1e9, r: -1e9, b: -1e9});
  return {size: [r.width, r.height], imgs, clipLeftContainer: c.length === 4 ? +(c[3] + m.m41).toFixed(2) : null,
          clipRightContainer: c.length === 4 ? +(c[1] + m.m41).toFixed(2) : null,
          dividerX: +(lb.x - r.x).toFixed(2), dataX: +d.getAttribute('data-swipe-x'),
          handle: d.querySelector('.satm-swipe-handle')?.getAttribute('aria-valuenow'),
          labels: [...d.querySelectorAll('.satm-swipe-label')].map(n => n.textContent),
          basemapTiles: d.querySelectorAll('.satm-basemap img.leaflet-tile, img.leaflet-tile.satm-basemap, .satm-basemap').length,
          attribution: d.querySelector('.leaflet-control-attribution')?.textContent || '',
          polygons: poly};
}"""
# Sample the clip edge vs the divider on every animation frame while a zoom animation runs.
ANIM = """() => new Promise(res => {
  const d = document.getElementById('satm-swipe'), pane = d.querySelector('.leaflet-satmAfter-pane'),
        mp = d.querySelector('.leaflet-map-pane'), line = d.querySelector('.satm-swipe-divider');
  const out = []; const t0 = performance.now();
  (function f() {
    const r = d.getBoundingClientRect(), m = new DOMMatrixReadOnly(getComputedStyle(mp).transform);
    const c = (pane.style.clip.match(/-?[\\d.]+/g) || []).map(Number);
    out.push(Math.abs((c[3] + m.m41) - (line.getBoundingClientRect().x - r.x)));
    if (performance.now() - t0 < 900) requestAnimationFrame(f); else res({frames: out.length, maxDev: Math.max(...out)});
  })();
  d.querySelector('.leaflet-control-zoom-in').click();
})"""


def main():
    base, creds, out = sys.argv[1], sys.argv[2], sys.argv[3]
    event = sys.argv[4] if len(sys.argv) > 4 else '62'
    user, pw = open(creds).read().split('\n', 1)
    rep = {'console_errors': [], 'checks': {}, 'fail': []}

    def check(name, ok, detail=None):
        rep['checks'][name] = {'ok': bool(ok), 'detail': detail}
        if not ok:
            rep['fail'].append(name)

    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(http_credentials={'username': user.strip(), 'password': pw.strip()},
                            viewport={'width': 1440, 'height': 900})
        pg = ctx.new_page()
        pg.on('console', lambda m: m.type == 'error' and rep['console_errors'].append(m.text))
        pg.goto(f'{base}/#sat-monitoring?event={event}')
        pg.wait_for_load_state('networkidle'); pg.wait_for_timeout(2000)
        pg.click('button[data-mode="swipe"]'); pg.wait_for_timeout(2500)
        sw = pg.locator('#satm-swipe'); sw.scroll_into_view_if_needed(); pg.wait_for_timeout(800)

        def aligned(s):
            a, c = s['imgs'][0], s['imgs'][1]
            return all(abs(a[k] - c[k]) < 0.5 for k in ('x', 'y', 'w', 'h'))

        steps = []
        for z in range(3):
            s = pg.evaluate(STATE)
            steps.append(s)
            sw.screenshot(path=f'{out}/swipe-{event}-zoom{z}.png')
            check(f'zoom{z}: before/after overlays identical rect', len(s['imgs']) == 2 and aligned(s), s['imgs'])
            check(f'zoom{z}: clip edge == divider (container px)', abs(s['clipLeftContainer'] - s['dividerX']) < 1.0,
                  [s['clipLeftContainer'], s['dividerX'], s['dataX']])
            check(f'zoom{z}: clip right edge == container width', abs(s['clipRightContainer'] - s['size'][0]) < 1.0,
                  [s['clipRightContainer'], s['size'][0]])
            if z < 2:
                anim = pg.evaluate(ANIM); pg.wait_for_timeout(700)
                check(f'zoom{z}->{z + 1} animation: clip edge never leaves the divider', anim['maxDev'] < 1.0, anim)
        s0 = steps[0]
        check('initial view fits event polygons (not grid scale)',
              s0['imgs'][0]['w'] > 1.3 * s0['size'][0] or s0['imgs'][0]['h'] > 1.3 * s0['size'][1] or
              (s0['polygons']['r'] - s0['polygons']['l']) > 0.6 * s0['size'][0] or
              (s0['polygons']['b'] - s0['polygons']['t']) > 0.6 * s0['size'][1], {'img': s0['imgs'][0], 'polygons': s0['polygons'], 'size': s0['size']})
        check('polygons inside the initial view', s0['polygons']['l'] >= -2 and s0['polygons']['t'] >= -2 and
              s0['polygons']['r'] <= s0['size'][0] + 2 and s0['polygons']['b'] <= s0['size'][1] + 2, s0['polygons'])
        check('labels PIRMS/PĒC on map with date', len(s0['labels']) == 2 and all(any(ch.isdigit() for ch in x) for x in s0['labels']), s0['labels'])
        check('muted basemap + attribution', s0['basemapTiles'] > 0 and 'OpenStreetMap' in s0['attribution'], s0['attribution'])

        # Drag the handle to 25 %, then keyboard +5 %, then pan: divider stays, clip follows.
        hb = pg.locator('.satm-swipe-handle').bounding_box(); box = sw.bounding_box()
        pg.mouse.move(hb['x'] + hb['width'] / 2, hb['y'] + hb['height'] / 2); pg.mouse.down()
        pg.mouse.move(box['x'] + box['width'] * 0.25, hb['y'] + hb['height'] / 2, steps=8); pg.mouse.up()
        s = pg.evaluate(STATE)
        check('drag handle to 25 %', abs(s['dividerX'] - 0.25 * s['size'][0]) < 3 and abs(s['clipLeftContainer'] - s['dividerX']) < 1, [s['dividerX'], s['clipLeftContainer']])
        pg.locator('.satm-swipe-handle').focus(); pg.keyboard.press('ArrowRight')
        s = pg.evaluate(STATE)
        check('keyboard ArrowRight +5 %', s['handle'] == '30', s['handle'])
        before_x = s['dividerX']
        pg.mouse.move(box['x'] + box['width'] * 0.7, box['y'] + box['height'] * 0.6); pg.mouse.down()
        pg.mouse.move(box['x'] + box['width'] * 0.55, box['y'] + box['height'] * 0.4, steps=10); pg.mouse.up(); pg.wait_for_timeout(500)
        s = pg.evaluate(STATE)
        check('pan: divider fixed, clip follows, overlays aligned', abs(s['dividerX'] - before_x) < 1 and abs(s['clipLeftContainer'] - s['dividerX']) < 1 and aligned(s),
              [before_x, s['dividerX'], s['clipLeftContainer']])
        sw.screenshot(path=f'{out}/swipe-{event}-after-drag-pan.png')

        # Side by side still renders three maps with the same view.
        pg.click('button[data-mode="side"]'); pg.wait_for_timeout(2500)
        n = pg.evaluate("document.querySelectorAll('#satm-img-before .leaflet-image-layer, #satm-img-after .leaflet-image-layer, #satm-img-change .leaflet-image-layer').length")
        check('side-by-side: 3 image maps', n == 3, n)
        pg.locator('.satm-imgs').first.screenshot(path=f'{out}/side-{event}.png')

        # D6: Forest Map coordinate search.
        idents = []
        pg.on('request', lambda r: '/forest-map/identify' in r.url and idents.append(parse_qs(urlparse(r.url).query)))
        pg.goto(f'{base}/#forest-map'); pg.wait_for_load_state('networkidle'); pg.wait_for_timeout(2500)
        for text in ('56,9496 24,1052', '56.9496, 24.1052', '56,9496; 24,1052'):
            idents.clear()
            pg.fill('#fm-coordinates', text); pg.press('#fm-coordinates', 'Enter'); pg.wait_for_timeout(1500)
            got = idents[-1] if idents else {}
            ok = got and abs(float(got['lat'][0]) - 56.9496) < 1e-6 and abs(float(got['lon'][0]) - 24.1052) < 1e-6
            check(f'coords {text!r} -> identify 56.9496, 24.1052', ok, got)
        for text in ('abc', '52.52, 13.405'):
            idents.clear()
            pg.fill('#fm-coordinates', text); pg.press('#fm-coordinates', 'Enter'); pg.wait_for_timeout(800)
            msg = pg.locator('#fm-status').text_content()
            check(f'coords {text!r} rejected with message', not idents and '55–59' in (msg or ''), msg)
        b.close()
    check('no console errors', not rep['console_errors'], rep['console_errors'])
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    sys.exit(1 if rep['fail'] else 0)


if __name__ == '__main__':
    main()
