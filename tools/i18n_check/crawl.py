"""Visit every dashboard page/tab, collect visible UI text. Usage: crawl.py <port> <out.json>"""
import sys, json, re, os
from playwright.sync_api import sync_playwright
port, out = sys.argv[1], sys.argv[2]
BASE = f"http://127.0.0.1:{port}/"
ROUTES = ['overview','objects','sectors','map','risks','gps','trucks','timber','photos','inspector','satellite',
          'integrations','sector-BIK-001','risk/1','risk/2','financial-breakdown']
COLLECT = r"""() => {
  const out = new Set();
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n; while ((n = w.nextNode())) {
    const p = n.parentElement; if (!p || ['SCRIPT','STYLE','NOSCRIPT'].includes(p.tagName)) continue;
    const t = n.nodeValue.replace(/\s+/g,' ').trim(); if (!t) continue;
    const r = p.getClientRects(); if (!r.length) continue;
    out.add(t);
  }
  document.querySelectorAll('[placeholder],[title],[aria-label]').forEach(el => {
    for (const a of ['placeholder','title','aria-label']) { const v = el.getAttribute(a); if (v && v.trim()) out.add('@'+a+': '+v.trim()); }
  });
  document.querySelectorAll('option, input[type=button], input[type=submit]').forEach(el => { const v=(el.textContent||el.value||'').trim(); if (v) out.add(v); });
  return [...out];
}"""
res = {}; dialogs = []
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(http_credentials={'username':os.environ.get('I18N_USER','rigas-mezi'),'password':os.environ.get('I18N_PASS','test-pass')}, locale='lv-LV', viewport={'width':1500,'height':1000})
    V = os.environ.get('I18N_VENDOR_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vendor'))
    LOCAL = {'chart.umd.min.js': (V+'/chart.js-4.4.1/dist/chart.umd.js','application/javascript'),
             'leaflet.js': (V+'/leaflet-1.9.4/dist/leaflet.js','application/javascript'),
             'leaflet.css': (V+'/leaflet-1.9.4/dist/leaflet.css','text/css')}
    def route(rt):
        u = rt.request.url
        if u.startswith('http://127.0.0.1'): return rt.continue_()
        for k,(f,ct) in LOCAL.items():
            if u.split('?')[0].endswith(k): return rt.fulfill(path=f, content_type=ct)
        return rt.abort()
    ctx.route('**/*', route)
    page = ctx.new_page(); page.set_default_timeout(3000)
    page.on('dialog', lambda d: (dialogs.append(d.message), d.dismiss()))
    errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
    for r in ROUTES:
        page.goto(BASE + '#' + r); page.wait_for_timeout(1800)
        texts = set(page.evaluate(COLLECT))
        # click through tabs / sub-tabs inside the page
        for sel in ['.tab:visible', '.filter-btn:visible']:
            n = page.locator(sel).count()
            for i in range(min(n, 10)):
                try:
                    page.locator(sel).nth(i).click(timeout=800); page.wait_for_timeout(500)
                    texts |= set(page.evaluate(COLLECT))
                except Exception: pass
        print(r, len(texts), flush=True)
        res[r] = sorted(texts)
    b.close()
json.dump({'pages': res, 'dialogs': sorted(set(dialogs)), 'errors': errors}, open(out,'w'), ensure_ascii=False, indent=1)
print('pages', len(res), 'texts', sum(len(v) for v in res.values()), 'dialogs', len(set(dialogs)), 'js errors', len(errors))
