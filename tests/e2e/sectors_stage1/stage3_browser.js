// Stage 3 browser checks on the RELEASE-CANDIDATE sandbox (127.0.0.1:8010, DB copies, test-only auth) + screenshots.
// Run: NODE_PATH=/root/forest_ai_navfix/tests/e2e/node_modules node tests/e2e/sectors_stage1/stage3_browser.js
const { chromium } = require('playwright');
const fs = require('fs');
const SB = '/root/sectors_sandbox', OUT = SB + '/screenshots_stage3', BASE = 'http://127.0.0.1:8010/';
const [user, pass] = fs.readFileSync(SB + '/.sandbox_auth', 'utf8').trim().split('\n');
fs.mkdirSync(OUT, { recursive: true });
const R = [], errors = [];
const ok = (name, cond, info) => R.push(`${cond ? 'PASS' : 'FAIL'}  ${name}${info !== undefined ? '  — ' + info : ''}`);

async function open(browser, vp) {
  const ctx = await browser.newContext({ viewport: vp, httpCredentials: { username: user, password: pass } });
  await ctx.addInitScript(() => { try { localStorage.setItem('satMonitoring.lang', 'lv'); } catch (e) {} });
  const p = await ctx.newPage();
  p.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  p.on('pageerror', e => errors.push(String(e)));
  return { ctx, p };
}
const shot = async (p, n) => { await p.waitForTimeout(900); await p.screenshot({ path: `${OUT}/${n}.png` }); };
async function sector(p, id) {
  await p.goto(BASE + '#sectors/' + id); await p.waitForSelector('.sc-head');
  await p.waitForFunction(() => !document.querySelector('#sc-panel .sc-loading'), null, { timeout: 15000 });
  await p.waitForTimeout(1500);
}

(async () => {
  const browser = await chromium.launch({ executablePath: '/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome' });
  const W = { width: 1366, height: 768 };
  { // ── list, cards from the real /api/sectors/cards
    const { ctx, p } = await open(browser, W);
    const resp = p.waitForResponse(r => r.url().endsWith('/api/sectors/cards'));
    await p.goto(BASE + '#sectors'); await p.waitForSelector('.sc-card'); const r = await resp;
    ok('list loads from GET /api/sectors/cards (one request)', r.status() === 200, `${(await r.body()).length} B`);
    const n = await p.locator('.sc-card').count(); ok('cards rendered', n >= 85, n);
    ok('no RU headers / no risk score in the list', !(await p.evaluate(() => /Подрядчик|Risk Score|Финансовый/.test(document.getElementById('sec-sectors').innerText))));
    await p.evaluate(async () => { const i = [...document.querySelectorAll('.sc-prev img')]; i.forEach(x => x.loading = 'eager');
      await Promise.all(i.map(x => x.complete ? 0 : new Promise(r => { x.onload = x.onerror = r; setTimeout(r, 4000); }))); });
    await shot(p, 'list_1366_lv');
    const note = id => p.evaluate(i => { const a = document.querySelector(`.sc-link[data-id="${i}"]`); return !!(a && a.querySelector('.sc-smallnote')); }, String(id));
    ok('F1/F2 card note: T-56 (76, 0.21 ha, monitored) shown', await note(76));
    ok('F1/F2 card note: LG917 (81, 1.08 ha, not monitored) not shown', !(await note(81)));
    ok('F2 card note: small but NOT monitored sector (16, stored 0 ha) not shown', !(await note(16)));
    // filter + scroll → card → Back
    await p.click('[data-status=NOT_MONITORED]'); await p.waitForTimeout(300);
    await p.evaluate(() => { document.querySelector('.content').scrollTop = 800; });
    const card = p.locator('.sc-link').nth(10); await card.hover();
    const before = await p.evaluate(() => document.querySelector('.content').scrollTop);
    await card.click(); await p.waitForSelector('.sc-head'); await p.goBack(); await p.waitForSelector('.sc-card'); await p.waitForTimeout(500);
    const after = await p.evaluate(() => ({ s: document.querySelector('.content').scrollTop, f: document.querySelector('.sc-filter.on')?.dataset.status }));
    ok('Back keeps scroll position and filter', after.s === before && after.f === 'NOT_MONITORED', `${before} → ${after.s}, ${after.f}`);
    await ctx.close();
  }
  { // ── sector pages
    const { ctx, p } = await open(browser, W);
    await sector(p, 26);
    ok('BIK-001: fallback B map with the Sentinel overlay', await p.locator('#sc-map img.leaflet-image-layer').count() === 1,
       await p.textContent('.sc-img-card .sc-cap'));
    ok('BIK-001: no developer text', !(await p.evaluate(() => /Stage\s*\d|SatWorkspace|\bD1\b|mount\(/.test(document.querySelector('.main').innerText))));
    ok('BIK-001: top bar has no duplicated title', (await p.textContent('#page-title')).trim() === '');
    await shot(p, 'sector_BIK-001_1366_lv');
    await p.click('#sc-panel a[data-module=compare]'); await p.waitForSelector('#sc-module-bar .sc-module-title');
    ok('BIK-001 Foto → photo comparison in 1 click', (await p.evaluate(() => location.hash)) === '#sectors/26/compare');
    await sector(p, 76);
    ok('T-56 page: detection note next to Izmaiņas', await p.evaluate(() => [...document.querySelectorAll('#sc-panel .sc-warn')].some(e => /mazs Sentinel-2/.test(e.textContent))));
    ok('T-56 page: no image overlay (too small, D4)', await p.locator('#sc-map img.leaflet-image-layer').count() === 0);
    await shot(p, 'sector_T-56_1366_lv');
    // Meža karte round trip
    await p.click('.sc-head a[href^="#forest-map?sector="]');
    await p.waitForFunction(() => document.querySelector('.leaflet-popup a.fm-open-sector'), null, { timeout: 30000 }).catch(() => {});
    const popup = await p.locator('.leaflet-popup a.fm-open-sector').count();
    ok('Atvērt Meža kartē → Meža karte focuses the sector (popup open)', popup === 1, await p.evaluate(() => location.hash));
    await shot(p, 'forest_map_focus_T-56_1366_lv');
    if (popup) { await p.click('.leaflet-popup a.fm-open-sector'); await p.waitForSelector('.sc-head');
      ok('Meža karte popup "Atvērt sektoru" → sector page', (await p.evaluate(() => location.hash)) === '#sectors/76'); }
    await sector(p, 81);
    ok('LG917 page: not monitored, polygon map, no detection note', await p.evaluate(() =>
      !!document.querySelector('[data-add-page]') && ![...document.querySelectorAll('#sc-panel .sc-warn')].some(e => /mazs Sentinel-2/.test(e.textContent))));
    ok('LG917: full cadastral number in the UI (F3)', /\b\d{11}\b/.test(await p.textContent('.sc-head')));
    await shot(p, 'sector_LG917_1366_lv');
    await p.reload(); await p.waitForSelector('.sc-head');
    ok('deep link reload #sectors/81', (await p.textContent('.sc-title')).startsWith('LG917'));
    await p.goto(BASE + '#sector-BIK-001'); await p.waitForSelector('.sc-head');
    ok('legacy #sector-{name} → one sector page', (await p.evaluate(() => location.hash)) === '#sectors/26');
    await p.goto(BASE + '#sectors/999999'); await p.waitForSelector('.sc-head');
    ok('unknown id → "Sektors nav atrasts"', /nav atrasts/.test(await p.textContent('.sc-page')));
    // add to monitoring (sandbox copy) on another not-monitored sector, then reload: status from the stored job
    const freeId = await p.evaluate(async () => (await (await fetch('/api/sectors/cards')).json()).sectors
      .find(c => c.id >= 30 && c.id !== 81 && !c.monitoring && !c.queued_job_id && c.ring).id);
    await sector(p, freeId);
    const [post] = await Promise.all([p.waitForResponse(r => r.url().endsWith('/api/sat-monitoring/areas') && r.request().method() === 'POST'), p.click('[data-add-page]')]);
    await p.waitForSelector('.sc-head .sc-chip-awaiting_first_data');
    await p.reload(); await p.waitForSelector('.sc-head');
    ok('add to monitoring → Gaida pirmos datus (from the stored job after reload)', post.status() === 202 &&
       await p.locator('.sc-head .sc-chip-awaiting_first_data').count() === 1, `POST ${post.status()}`);
    await ctx.close();
  }
  { // ── 1920
    const { ctx, p } = await open(browser, { width: 1920, height: 1080 });
    await sector(p, 26); await shot(p, 'sector_BIK-001_1920_lv'); await ctx.close();
  }
  { // ── 1,000 sectors: generated payload (stage3_api.py, DB copy) served for /api/sectors/cards
    const { ctx, p } = await open(browser, W);
    const body = fs.readFileSync(SB + '/perf_1000/cards_1000.json');
    await p.route('**/api/sectors/cards', r => r.fulfill({ status: 200, contentType: 'application/json', body }));
    const t0 = Date.now(); await p.goto(BASE + '#sectors'); await p.waitForSelector('.sc-card'); const tList = Date.now() - t0;
    const n = await p.locator('.sc-card').count(); const pager = await p.textContent('.sc-pager span');
    const t1 = Date.now(); await p.fill('.sc-search', 'PERF-0777'); await p.waitForFunction(() => document.querySelectorAll('.sc-card').length === 1); const tSearch = Date.now() - t1;
    const t2 = Date.now(); await p.fill('.sc-search', ''); await p.click('[data-status=NOT_MONITORED]'); await p.waitForTimeout(50); const tFilter = Date.now() - t2;
    ok('1,000 sectors: paginated, first page rendered', n === 100, `${tList} ms to first cards, "${pager}", search ${tSearch} ms, filter ${tFilter} ms`);
    await ctx.close();
  }
  await browser.close();
  R.push(`console errors: ${errors.length}`); errors.slice(0, 10).forEach(e => R.push('ERR ' + e));
  fs.writeFileSync(OUT + '/REPORT.txt', R.join('\n') + '\n'); console.log(R.join('\n'));
})().catch(e => { console.error(e); process.exit(1); });
