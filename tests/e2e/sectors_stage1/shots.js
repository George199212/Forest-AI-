// Stage 1 screenshots of the sectors prototype on the 127.0.0.1:8010 sandbox (test-only auth, DB copies).
// Run: NODE_PATH=/root/forest_ai_navfix/tests/e2e/node_modules node /root/sectors_sandbox/shots.js
const { chromium } = require('playwright');
const fs = require('fs');
const SB = '/root/sectors_sandbox', OUT = SB + '/screenshots', BASE = 'http://127.0.0.1:8010/';
const [user, pass] = fs.readFileSync(SB + '/.sandbox_auth', 'utf8').trim().split('\n');
fs.mkdirSync(OUT, { recursive: true });
const VP = { '1366': { width: 1366, height: 768 }, '1440': { width: 1440, height: 900 }, '1920': { width: 1920, height: 1080 }, '1279': { width: 1279, height: 768 } };
const log = [], errors = [];

async function page(ctx) {
  const p = await ctx.newPage();
  p.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  p.on('pageerror', e => errors.push(String(e)));
  return p;
}
async function context(browser, vp, lang) {
  const ctx = await browser.newContext({ viewport: VP[vp], httpCredentials: { username: user, password: pass }, deviceScaleFactor: 1 });
  await ctx.addInitScript(l => { try { localStorage.setItem('satMonitoring.lang', l); } catch (e) {} }, lang);
  return ctx;
}
async function shot(p, name) { await p.waitForTimeout(700); await p.screenshot({ path: `${OUT}/${name}.png` }); log.push(name); }
async function settleImages(p) {
  await p.evaluate(async () => {
    const imgs = [...document.querySelectorAll('.sc-prev img')];
    imgs.forEach(i => { i.loading = 'eager'; });
    await Promise.all(imgs.map(i => i.complete ? 0 : new Promise(r => { i.onload = i.onerror = r; setTimeout(r, 4000); })));
  });
}
async function list(p, vp, lang, tag = '') {
  await p.goto(BASE + '#sectors'); await p.waitForSelector('.sc-card');
  await settleImages(p); await shot(p, `list_${vp}_${lang}${tag}`);
}
async function sector(p, id, vp, lang, name, opts = {}) {
  await p.goto(BASE + '#sectors/' + encodeURIComponent(id)); await p.waitForSelector('.sc-head');
  await p.waitForFunction(() => !document.querySelector('#sc-panel .sc-loading'), null, { timeout: 15000 });
  if (opts.drawer) await p.click('[data-act=drawer]');
  await p.waitForTimeout(1500);                      // OSM tiles
  await shot(p, `sector_${name}_${vp}_${lang}${opts.drawer ? '_drawer' : ''}`);
}

(async () => {
  const browser = await chromium.launch({ executablePath: '/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome' });
  const t0 = Date.now();
  for (const lang of ['lv', 'en']) {
    for (const vp of ['1366', '1440', '1920']) {
      const ctx = await context(browser, vp, lang), p = await page(ctx);
      await list(p, vp, lang);
      const pages = vp === '1366' ? [[26, 'BIK-001_monitored_image'], [76, 'sector76_monitored_small'], [81, 'sector81_not_monitored'], ['fixture-kekava', 'kekava_fixture_events']]
                                  : (lang === 'lv' ? [[26, 'BIK-001_monitored_image'], [81, 'sector81_not_monitored']] : []);
      for (const [id, n] of pages) await sector(p, id, vp, lang, n);
      await ctx.close();
    }
    // ≤1279 px: panel becomes a drawer (closed + open)
    const ctx = await context(browser, '1279', lang), p = await page(ctx);
    await sector(p, 81, '1279', lang, 'sector81_not_monitored');
    await sector(p, 26, '1279', lang, 'BIK-001_monitored_image', { drawer: true });
    await ctx.close();
  }
  // filter + search state, then card → sector → browser Back: scroll position and filters must survive
  {
    const ctx = await context(browser, '1366', 'lv'), p = await page(ctx);
    await p.goto(BASE + '#sectors'); await p.waitForSelector('.sc-card');
    for (const [q, n] of [['Т-56', 'sector76_small_card'], ['Kekava', 'kekava_fixture_card'], ['BIK', 'BIK-001_card']]) {
      await p.fill('.sc-search', q); await p.waitForTimeout(400); await settleImages(p); await shot(p, 'list_1366_lv_search_' + n);
    }
    await p.click('[data-status=NOT_MONITORED]'); await p.fill('.sc-search', 'LG917'); await p.waitForTimeout(400);
    await shot(p, 'list_1366_lv_filter_not_monitored_LG917');
    await p.fill('.sc-search', ''); await p.waitForTimeout(300);
    await p.evaluate(() => { document.querySelector('.content').scrollTop = 900; });
    const card = p.locator('.sc-link').nth(12); const cid = await card.getAttribute('data-id');
    await card.hover();                                   // Playwright scrolls the card into view here
    const before = await p.evaluate(() => document.querySelector('.content').scrollTop);
    await card.click(); await p.waitForSelector('.sc-head');
    const hash1 = await p.evaluate(() => location.hash);
    await p.goBack(); await p.waitForSelector('.sc-card'); await p.waitForTimeout(500);
    const after = await p.evaluate(() => ({ s: document.querySelector('.content').scrollTop, f: document.querySelector('.sc-filter.on')?.dataset.status, h: location.hash }));
    log.push(`BACK: card ${cid} → ${hash1}; scroll ${before} → ${after.s}; filter ${after.f}; hash ${after.h}`);
    await p.reload(); await p.waitForSelector('.sc-card'); log.push('RELOAD #sectors: ' + await p.evaluate(() => location.hash));
    await p.goto(BASE + '#sectors/81'); await p.reload(); await p.waitForSelector('.sc-head');
    log.push('DEEP LINK reload #sectors/81: title=' + await p.textContent('.sc-title'));
    await p.goto(BASE + '#sectors/999999'); await p.waitForSelector('.sc-head'); log.push('UNKNOWN #sectors/999999: ' + (await p.textContent('.sc-error')));
    // keyboard: Tab reaches a card link with a visible focus ring
    await p.goto(BASE + '#sectors'); await p.waitForSelector('.sc-card');
    await p.focus('.sc-link'); await shot(p, 'list_1366_lv_keyboard_focus');
    await ctx.close();
  }
  await browser.close();
  log.push(`done in ${((Date.now() - t0) / 1000).toFixed(1)} s; console errors: ${errors.length}`);
  errors.slice(0, 20).forEach(e => log.push('ERR ' + e));
  fs.writeFileSync(OUT + '/LOG.txt', log.join('\n') + '\n');
  console.log(log.join('\n'));
})().catch(e => { console.error(e); process.exit(1); });
