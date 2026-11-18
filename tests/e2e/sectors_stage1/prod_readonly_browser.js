// Stage 4 post-restart READ-ONLY browser checks on production :8000 (no POST, no clicks that change data).
// Credentials only via env FA_USER / FA_PASS (read from /root/forest_ai/.env by the caller, never printed).
// Run: FA_USER=… FA_PASS=… NODE_PATH=/root/forest_ai_navfix/tests/e2e/node_modules node prod_readonly_browser.js
const { chromium } = require('playwright');
const fs = require('fs');
const OUT = '/root/sectors_sandbox/screenshots_prod_20261118', BASE = 'http://127.0.0.1:8000/';
fs.mkdirSync(OUT, { recursive: true });
const [user, pass] = [process.env.FA_USER, process.env.FA_PASS];   // from the caller's environment, never printed
const R = [], errors = [], posts = [];
const ok = (name, cond, info) => R.push(`${cond ? 'PASS' : 'FAIL'}  ${name}${info !== undefined ? '  — ' + info : ''}`);

(async () => {
  const browser = await chromium.launch({ executablePath: '/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome' });
  const ctx = await browser.newContext({ viewport: { width: 1366, height: 768 }, httpCredentials: { username: user, password: pass } });
  await ctx.addInitScript(() => { try { localStorage.setItem('satMonitoring.lang', 'lv'); } catch (e) {} });
  const p = await ctx.newPage();
  p.on('console', m => { if (m.type() === 'error') errors.push(p.url() + ' :: ' + m.text()); });
  p.on('pageerror', e => errors.push(p.url() + ' :: ' + String(e)));
  p.on('request', r => { if (!['GET', 'HEAD', 'OPTIONS'].includes(r.method())) posts.push(r.method() + ' ' + r.url()); });
  const shot = async n => { await p.waitForTimeout(1200); await p.screenshot({ path: `${OUT}/${n}.png` }); };
  const sector = async id => { await p.goto(BASE + '#sectors/' + id); await p.waitForSelector('.sc-head', { timeout: 20000 });
    await p.waitForFunction(() => !document.querySelector('#sc-panel .sc-loading'), null, { timeout: 20000 }); await p.waitForTimeout(1500); };

  await p.goto(BASE + '#sectors'); await p.waitForSelector('.sc-card', { timeout: 20000 });
  ok('Sektori list renders cards', (await p.locator('.sc-card').count()) >= 85, await p.locator('.sc-card').count());
  await shot('list_1366_lv');
  await sector(26);
  ok('BIK-001 fallback B with Sentinel overlay', (await p.locator('#sc-map img.leaflet-image-layer').count()) === 1, await p.textContent('.sc-img-card .sc-cap'));
  await shot('sector_BIK-001_1366_lv');
  await p.click('#sc-panel a[data-module=compare]'); await p.waitForSelector('#sc-module-bar .sc-module-title', { timeout: 20000 });
  ok('BIK-001 Foto → photo comparison (1 click)', (await p.evaluate(() => location.hash)) === '#sectors/26/compare');
  await sector(76);
  ok('T-56 detection note', await p.evaluate(() => [...document.querySelectorAll('#sc-panel .sc-warn')].some(e => /mazs Sentinel-2/.test(e.textContent))));
  await shot('sector_T-56_1366_lv');
  await p.click('.sc-head a[href^="#forest-map?sector="]');
  await p.waitForFunction(() => document.querySelector('.leaflet-popup a.fm-open-sector'), null, { timeout: 30000 }).catch(() => {});
  ok('Meža karte focuses T-56 (popup with "Atvērt sektoru")', (await p.locator('.leaflet-popup a.fm-open-sector').count()) === 1);
  await shot('forest_map_focus_T-56_1366_lv');
  await sector(81);
  ok('LG917 not monitored, full cadastral number', !!(await p.locator('[data-add-page]').count()) && /\b\d{11}\b/.test(await p.textContent('.sc-head')));
  await shot('sector_LG917_1366_lv');
  await p.goto(BASE + '#sat-monitoring'); await p.waitForTimeout(5000);
  ok('Satelītu monitorings overview renders', await p.evaluate(() => { const s = document.getElementById('sec-sat-monitoring'); return !!s && s.classList.contains('active') && s.innerText.trim().length > 50; }));
  await shot('sat_monitoring_overview_1366_lv');
  await p.goto(BASE + '#lvm-geodata'); await p.waitForTimeout(5000);
  ok('LVM GEO page renders', await p.evaluate(() => { const s = document.getElementById('sec-lvm-geodata'); return !!s && s.classList.contains('active') && s.innerText.trim().length > 50; }));
  await shot('lvm_geo_1366_lv');
  await browser.close();
  ok('no data-changing requests (read-only)', posts.length === 0, posts.slice(0, 3).join(', ') || 'none');
  ok('console errors', errors.length === 0, errors.length);
  errors.slice(0, 10).forEach(e => R.push('ERR ' + e));
  fs.writeFileSync(OUT + '/REPORT.txt', R.join('\n') + '\n'); console.log(R.join('\n'));
  process.exit(R.some(x => x.startsWith('FAIL')) ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
