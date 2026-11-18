// Stage 1 revision (owner D10–D12, 2026-11-18): screenshots into /root/sectors_sandbox/screenshots_v2.
// Run: NODE_PATH=/root/forest_ai_navfix/tests/e2e/node_modules node tests/e2e/sectors_stage1/shots_v2.js
const { chromium } = require('playwright');
const fs = require('fs');
const SB = '/root/sectors_sandbox', OUT = SB + '/screenshots_v2', BASE = 'http://127.0.0.1:8010/';
const [user, pass] = fs.readFileSync(SB + '/.sandbox_auth', 'utf8').trim().split('\n');
fs.mkdirSync(OUT, { recursive: true });
const log = [], errors = [];
const VP = { 1366: { width: 1366, height: 768 }, 1920: { width: 1920, height: 1080 } };

async function open(browser, vp) {
  const ctx = await browser.newContext({ viewport: VP[vp], httpCredentials: { username: user, password: pass } });
  await ctx.addInitScript(() => { try { localStorage.setItem('satMonitoring.lang', 'lv'); } catch (e) {} });
  const p = await ctx.newPage();
  p.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  p.on('pageerror', e => errors.push(String(e)));
  return { ctx, p };
}
async function shot(p, name) { await p.waitForTimeout(800); await p.screenshot({ path: `${OUT}/${name}.png` }); log.push(name); }
async function images(p) {
  await p.evaluate(async () => {
    const imgs = [...document.querySelectorAll('.sc-prev img')]; imgs.forEach(i => { i.loading = 'eager'; });
    await Promise.all(imgs.map(i => i.complete ? 0 : new Promise(r => { i.onload = i.onerror = r; setTimeout(r, 4000); })));
  });
}
async function sector(p, id) {
  await p.goto(BASE + '#sectors/' + id); await p.waitForSelector('.sc-head');
  await p.waitForFunction(() => !document.querySelector('#sc-panel .sc-loading'), null, { timeout: 15000 });
  await p.waitForTimeout(1200);
}

(async () => {
  const browser = await chromium.launch({ executablePath: '/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome' });
  for (const vp of [1366, 1920]) {
    const { ctx, p } = await open(browser, vp);
    await p.goto(BASE + '#sectors'); await p.waitForSelector('.sc-card'); await images(p); await shot(p, `list_${vp}_lv`);
    await sector(p, 26); await shot(p, `sector_BIK-001_${vp}_lv`);
    if (vp === 1366) {
      await p.evaluate(() => document.querySelector('#sc-panel .sc-counters').scrollIntoView({ block: 'end' }));
      await shot(p, 'sector_BIK-001_1366_lv_panel_aktivitate');
      // ≤2 clicks: sector page → "Foto (foto salīdzināšana) 48" → existing photo comparison
      const before = await p.evaluate(() => location.hash);
      await p.click('#sc-panel a[data-module=compare]');
      await p.waitForSelector('#sc-module-bar .sc-module-title'); await p.waitForTimeout(2500);
      const after = await p.evaluate(() => ({ h: location.hash, tab: window.currentDetailTab,
        hidden: ['#detail-tabs', '#detail-stats', '#detail-score-card'].map(s => getComputedStyle(document.querySelector(s)).display) }));
      log.push(`FOTO: ${before} → 1 click → ${after.h}; currentDetailTab=${after.tab}; legacy chrome display=${after.hidden.join('/')}`);
      await shot(p, 'sector_BIK-001_1366_lv_foto_salidzinasana');
      await p.goBack(); await p.waitForSelector('.sc-head'); log.push('BACK from Foto → ' + await p.evaluate(() => location.hash));
      // legacy entry points redirect to the one sector page when the flag is off
      await p.goto(BASE + '#sector-BIK-001'); await p.waitForSelector('.sc-head'); log.push('LEGACY #sector-BIK-001 → ' + await p.evaluate(() => location.hash));
      await p.goto(BASE + '#gps'); await p.waitForSelector('#gps-table .tbl-link');
      await p.click('#gps-table .tbl-link'); await p.waitForSelector('.sc-head'); log.push('GPS table sector link → ' + await p.evaluate(() => location.hash));
      // Objects → sectors filter renders cards (no RU table)
      await p.goto(BASE + '#objects'); await p.waitForTimeout(800);
      await p.evaluate(() => { objectFilter = 17; nav('sectors'); }); await p.waitForSelector('.sc-objbar'); await images(p);
      log.push('OBJECT filter 17: ' + await p.textContent('.sc-objbar span') + ' | RU headers present: ' + await p.evaluate(() => /Подрядчик|Сектор</.test(document.getElementById('sec-sectors').innerHTML)));
      await shot(p, 'list_1366_lv_object_filter_plan17');
      await sector(p, 76); await shot(p, 'sector_76_monitored_small_1366_lv');
      await sector(p, 81); await shot(p, 'sector_81_not_monitored_1366_lv');
    }
    await ctx.close();
  }
  await browser.close();
  log.push(`console errors: ${errors.length}`); errors.slice(0, 10).forEach(e => log.push('ERR ' + e));
  fs.writeFileSync(OUT + '/LOG.txt', log.join('\n') + '\n'); console.log(log.join('\n'));
})().catch(e => { console.error(e); process.exit(1); });
