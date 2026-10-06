"""R1/R2 real Chrome regressions; synthetic intercepted requests only, no backend import.

Use --case R1 or --case R2 for the original minimal reproduction. Default runs
all surfaces and identity boundaries sequentially with the real ten-second timer.
The independent review's bug-asserting probe remains historical failure evidence.
"""
import argparse
import json
from pathlib import Path
from typing import Any
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
fixture = ROOT / 'tests/browser_regression.py'
ns: dict[str, Any] = {'__file__': str(fixture)}
exec(compile(fixture.read_text().split('with sync_playwright() as p:')[0], str(fixture), 'exec'), ns)
state = ns['state']
OUT = ROOT.parent / 'tv-tenderr-audit/evidence'
parser = argparse.ArgumentParser()
parser.add_argument('--case', choices=['R1', 'R2', 'all'], default='all')
args = parser.parse_args()
results = []

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/usr/bin/google-chrome', headless=True, args=['--no-sandbox'])
    context = browser.new_context(service_workers='block')
    context.route('**/*', ns['route_request'])
    context.add_init_script("sessionStorage.setItem('tvTenderrToken', 'synthetic-browser-token')")

    def fresh(view='movies', surface='single', media='movies'):
        state['posts'].clear()
        page = context.new_page()
        page.goto('http://tv.fixture/')
        expect(page.locator('.single-card-title')).to_have_count(1)
        if view != 'movies':
            page.locator(f'[data-view="{view}"]').click()
        if view == 'discover' and media != 'movies':
            page.locator(f'#discoverTabs [data-type="{media}"]').click()
        expect(page.locator('.single-card-title')).to_have_count(1)
        if surface != 'single':
            page.locator('[data-viewmode="grid"]').click()
            expect(page.locator('.card-title')).to_have_count(1)
        if surface == 'detail':
            page.locator('.card-title').click()
            expect(page.locator('#detailPanel')).to_have_class('detail-panel open')
        return page

    def controls(page, surface):
        return page.locator('#detailActions' if surface == 'detail' else '#contentArea')

    def finish(page, name, expected):
        page.wait_for_timeout(10300)
        actual = list(state['posts'])
        results.append({'case': name, 'posts': actual, 'expected': expected})
        print(name, json.dumps(actual), flush=True)
        assert actual == expected, (name, actual, expected)
        page.close()

    surfaces = ['single'] if args.case != 'all' else ['single', 'grid', 'detail']
    if args.case in ('R1', 'all'):
        for media in (['movies'] if args.case == 'R1' else ['movies', 'shows']):
            for surface in surfaces:
                decisions = ['keep'] if args.case == 'R1' else ['keep', 'super_keep']
                for decision in decisions:
                    page = fresh(media, surface)
                    controls(page, surface).get_by_role('button', name='Block', exact=True).click()
                    # Grid exposes Keep; Super Keep is exposed in its detail panel.
                    target = surface
                    if surface == 'grid' and decision == 'super_keep':
                        page.locator('.card-title').click()
                        target = 'detail'
                    label = 'Super Keep' if decision == 'super_keep' else 'Keep (6mo)' if target == 'detail' else 'Keep'
                    controls(page, target).get_by_role('button', name=label, exact=True).click()
                    finish(page, f'R1 {media} {surface} block->{decision}', [(f'/api/{media}/1/{decision}', None)])
        if args.case == 'all':
            for media in ['movies', 'shows']:
                for surface in surfaces:
                    page = fresh('discover', surface, media)
                    controls(page, surface).get_by_role('button', name='Dislike', exact=True).click()
                    label = 'Add to Library' if surface == 'detail' else 'Add'
                    controls(page, surface).get_by_role('button', name=label, exact=True).click()
                    endpoint = 'add_movie' if media == 'movies' else 'add_show'
                    finish(page, f'R1 discover {media} {surface} dislike->add', [(f'/api/discover/10/{endpoint}', None)])
            page = fresh()
            controls(page, 'single').get_by_role('button', name='Block', exact=True).click()
            page.locator('[data-view="shows"]').click()
            controls(page, 'single').get_by_role('button', name='Keep', exact=True).click()
            finish(page, 'R1 same numeric library ID distinct types', [('/api/shows/1/keep', None), ('/api/movies/1/block', None)])

    if args.case in ('R2', 'all'):
        item = ns['item']
        body = {'title': item['title'], 'year': item['year'], 'posterUrl': item['posterUrl'], 'type': 'movies'}
        for surface in surfaces:
            page = fresh('discover', surface)
            controls(page, surface).get_by_role('button', name='Dislike', exact=True).click()
            if surface == 'detail':
                controls(page, surface).get_by_role('button', name='Close', exact=True).click()
            for media in ['shows', 'movies', 'shows']:
                page.locator(f'#discoverTabs [data-type="{media}"]').click()
            finish(page, f'R2 {surface} movie dislike then rapid tabs', [('/api/discover/10/dislike', body)])
        if args.case == 'all':
            page = fresh('discover')
            controls(page, 'single').get_by_role('button', name='Dislike', exact=True).click()
            page.locator('#discoverTabs [data-type="shows"]').click()
            controls(page, 'single').get_by_role('button', name='Add', exact=True).click()
            finish(page, 'R1/R2 same TMDb ID distinct types', [('/api/discover/10/add_show', None), ('/api/discover/10/dislike', body)])
    browser.close()

(OUT / f'deferred-actions-{args.case}.json').write_text(json.dumps(results, indent=2) + '\n')
print(f'PASS {len(results)} deferred-action scenarios (real 10.3s waits)', flush=True)
