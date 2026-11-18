// Stage 1 revision 3 (owner R1–R5, 2026-11-18): screenshots into /root/sectors_sandbox/screenshots_v3.
// Run: NODE_PATH=/root/forest_ai_navfix/tests/e2e/node_modules node tests/e2e/sectors_stage1/shots_v3.js
const { chromium } = require('playwright');
const fs = require('fs');
const SB = '/root/sectors_sandbox', OUT = SB + '/screenshots_v3', BASE = 'http://127.0.0.1:8010/';
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
    if (vp === 1366) { await p.goto(BASE + '#sectors'); await p.waitForSelector('.sc-card'); await images(p); await shot(p, 'list_1366_lv'); }
    await sector(p, 26); await p.waitForTimeout(1500); await shot(p, `sector_BIK-001_${vp}_lv`);
    if (vp === 1366) {
      log.push('BIK-001 overlay images on map: ' + await p.evaluate(() => document.querySelectorAll('#sc-map img.leaflet-image-layer').length) +
               ' | caption: ' + await p.textContent('.sc-img-card .sc-cap') + ' | top bar title: "' + await p.textContent('#page-title') + '"');
      await sector(p, 76); await shot(p, 'sector_T-56_small_1366_lv');
      log.push('T-56 overlay images: ' + await p.evaluate(() => document.querySelectorAll('#sc-map img.leaflet-image-layer').length) +
               ' | small note: ' + await p.evaluate(() => [...document.querySelectorAll('#sc-panel .sc-warn')].map(e => e.textContent).join(' / ')));
      await sector(p, 81); await shot(p, 'sector_LG917_not_monitored_1366_lv');
      const dev = await p.evaluate(() => /Stage\s*\d|SatWorkspace|\bD1\b|mount\(/.test(document.querySelector('.main').innerText));
      log.push('developer text visible: ' + dev);
      await sector(p, 26); await p.click('#sc-panel a[data-module=compare]'); await p.waitForSelector('#sc-module-bar .sc-module-title');
      log.push('photo page top bar: title="' + await p.textContent('#page-title') + '" sub="' + await p.textContent('#page-sub') + '"');
    }
    await ctx.close();
  }
  await browser.close();
  log.push(`console errors: ${errors.length}`); errors.slice(0, 10).forEach(e => log.push('ERR ' + e));
  fs.writeFileSync(OUT + '/LOG.txt', log.join('\n') + '\n'); console.log(log.join('\n'));
})().catch(e => { console.error(e); process.exit(1); });
