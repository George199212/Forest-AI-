#!/usr/bin/env python3
"""Audit the live review UI on loopback. Reads auth from environment; never logs credentials.

Run on the VPS host, after restarting only forest-review-api:
  cd /root/forest_ai_review
  set -a; . ./.env; set +a
  /root/forest_ai/venv/bin/python scripts/verify_review_ui.py --report /tmp/review-ui-report.json

Requires Playwright + Chromium. Does not restart services or modify the database.
"""
import argparse
import json
import os
from pathlib import Path
import re
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

FOREIGN = re.compile(r'[āčēģīķļņšūžĀČĒĢĪĶĻŅŠŪŽ\u0400-\u052f]')
SCREENS = ['overview', 'objects', 'sectors', 'map', 'risks', 'gps', 'trucks', 'timber',
           'photos', 'inspector', 'satellite', 'integrations']
PROTECTED = {'api.anthropic.com', 'api.telegram.org', 'sh.dataspace.copernicus.eu'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    results, errors, attempted = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(http_credentials={
            'username': os.environ['DASHBOARD_USERNAME'], 'password': os.environ['DASHBOARD_PASSWORD']},
            viewport={'width': 1440, 'height': 1000}, locale='en-GB', timezone_id='UTC')
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))

        def watch(request):
            if urlparse(request.url).hostname in PROTECTED:
                attempted.append(urlparse(request.url).hostname)
        page.on('request', watch)
        page.goto('http://127.0.0.1:8003/', wait_until='domcontentloaded')
        page.wait_for_function('window.ForestI18n?.lang === "en" && window.ForestInstance?.readOnly === true')
        page.wait_for_function('document.querySelector(".forest-review-banner")')
        assert page.title() == 'Forest AI — Integration Review'

        def record(name):
            page.wait_for_timeout(700)
            # Visible text, attributes of visible controls, and read-only textarea contents.
            text = page.locator('body').inner_text()
            extra = page.evaluate('''() => [...document.querySelectorAll('[title],[placeholder],[aria-label],textarea')]
                .filter(e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden')
                .map(e => [e.title,e.placeholder,e.getAttribute('aria-label'),e.tagName==='TEXTAREA'?e.value:''].filter(Boolean).join(' ')).join('\\n')''')
            remainder = sorted(set(re.findall(r'[^\n]*[āčēģīķļņšūžĀČĒĢĪĶĻŅŠŪŽ\u0400-\u052f][^\n]*', text+'\n'+extra)))
            unsafe = page.evaluate('''() => [...document.querySelectorAll('button,[onclick],[role=button],input[type=file],input[type=submit]')]
                .filter(e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden'
                  && !e.disabled && !window.ForestReview.allowed(e)).length''')
            connected = len(re.findall(r'(?<![\w-])(?:Connected|Pieslēgts)(?![\w-])',text,re.I))
            results.append({'screen':name,'foreign_characters':len(FOREIGN.findall(text+'\n'+extra)),
                            'visible_unsafe_controls':unsafe,'connection_claims':connected,'remainder':remainder})

        for screen in SCREENS:
            page.evaluate('(screen) => nav(screen)', screen)
            page.wait_for_function('(screen) => document.querySelector("#sec-"+screen)?.classList.contains("active")',arg=screen)
            record(screen)
            if screen == 'integrations':
                for category in ['machine','fleet','gis','satellite','timber','weighbridge','erp','worker','audit']:
                    page.evaluate('(category) => setIntCategoryFilter(category)',category)
                    record('integrations/'+category)
                page.evaluate('setIntCategoryFilter(null)')

        page.evaluate('openSector("FIELD-TEST-01")')
        page.wait_for_function('document.querySelector("#detail-name")?.textContent === "FIELD-TEST-01" && !!currentDetailData')
        for tab in ['gps','photos','compare','risks','comments','trucks','timber','employees','vehicles','forest','map','satellite','history']:
            page.evaluate('(tab) => detailTab(tab)',tab)
            record('FIELD-TEST-01/'+tab)
            if tab == 'compare':
                for view in ['all','match','decide','nochange','reshoot','oneside']:
                    page.evaluate('(view) => pcSetFilter(view)',view)
                    record('FIELD-TEST-01/compare/'+view)
            if tab == 'map':
                sessions=page.evaluate('trkSessions.map(s=>s.id)')
                for sid in sessions:
                    page.evaluate('(id) => trkShow(id)',sid)
                    record('FIELD-TEST-01/worker-route/'+str(sid))
        risk_ids=page.evaluate('currentDetailData.risks.map(r=>r.id)')
        for rid in risk_ids:
            page.evaluate('(id) => openRisk(id)',rid)
            page.wait_for_function('(id) => currentRiskId === id && rcRiskId === id && !!rcData',arg=rid)
            record('FIELD-TEST-01/risk-conclusion/'+str(rid))
            details=page.locator('#risk-conclusion details')
            for i in range(details.count()): details.nth(i).evaluate('(e) => e.open = true')
            record('FIELD-TEST-01/risk-conclusion-expanded/'+str(rid))
        browser.close()
    success=not errors and not attempted and all(not r['foreign_characters'] and not r['visible_unsafe_controls'] and not r['connection_claims'] for r in results)
    Path(args.report).write_text(json.dumps({'passed':success,'screens':results,'page_errors':errors,
        'browser_protected_host_requests':attempted,
        'limitation':'Browser request monitoring does not prove absence of server-side outbound connections.'},indent=2)+'\n')
    print('Screens:',len(results),'passed:',success,'page errors:',len(errors),'protected-host browser requests:',len(attempted))
    raise SystemExit(0 if success else 1)


if __name__ == '__main__':
    main()
