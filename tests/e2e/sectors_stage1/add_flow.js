// Real "Pievienot monitoringam" on the SANDBOX COPY (POST /api/sat-monitoring/areas → ADD_AREA job; no worker runs in the
// sandbox, so the sector stays "Gaida pirmos datus"). Sector 81 (LVM GEO registration, not monitored).
const { chromium } = require('playwright'); const fs = require('fs');
const SB = '/root/sectors_sandbox', OUT = SB + '/screenshots', BASE = 'http://127.0.0.1:8010/';
const [user, pass] = fs.readFileSync(SB + '/.sandbox_auth', 'utf8').trim().split('\n');
(async () => {
  const b = await chromium.launch({ executablePath: '/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome' });
  const errs = [];
  for (const lang of ['lv', 'en']) {
    const ctx = await b.newContext({ viewport: { width: 1366, height: 768 }, httpCredentials: { username: user, password: pass } });
    await ctx.addInitScript(l => localStorage.setItem('satMonitoring.lang', l), lang);
    const p = await ctx.newPage(); p.on('pageerror', e => errs.push(String(e))); p.on('console', m => m.type() === 'error' && errs.push(m.text()));
    if (process.argv[2] === 'click') {
      await p.goto(BASE + '#sectors/81'); await p.waitForSelector('[data-add-page]');
      const [resp] = await Promise.all([p.waitForResponse(r => r.url().endsWith('/api/sat-monitoring/areas') && r.request().method() === 'POST'), p.click('[data-add-page]')]);
      console.log('POST', resp.status(), JSON.stringify(await resp.json()));
      await p.waitForSelector('.sc-chip-awaiting_first_data'); await p.waitForTimeout(1500);
      await p.screenshot({ path: `${OUT}/sector_sector81_awaiting_after_add_1366_${lang}.png` });
      await ctx.close(); break;                         // one POST only
    }
    await p.goto(BASE + '#sectors'); await p.waitForSelector('.sc-card');
    await p.click('[data-status=AWAITING_FIRST_DATA]'); await p.waitForTimeout(500);
    await p.screenshot({ path: `${OUT}/list_1366_${lang}_filter_awaiting_from_stored_job.png` });
    await p.goto(BASE + '#sectors/81'); await p.waitForSelector('.sc-head .sc-chip-awaiting_first_data'); await p.waitForTimeout(1500);
    await p.screenshot({ path: `${OUT}/sector_sector81_awaiting_from_stored_job_1366_${lang}.png` });
    await ctx.close();
  }
  await b.close(); console.log('console errors:', errs.length, errs.slice(0, 5));
})().catch(e => { console.error(e); process.exit(1); });
