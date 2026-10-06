"""Isolated Chromium behavioral regression. Every request is intercepted; no live services.
Run with a disposable venv containing playwright, using system Chrome.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT.parent / 'tv-tenderr-audit/evidence'
OUT.mkdir(parents=True, exist_ok=True)
TOKEN = 'synthetic-browser-token'
ATTACK = '\"\'><img src=x onerror=window.pwned=1>&quot;);window.pwned=1;//'
item = dict(id=1, tmdbId=10, movieId=1, title=ATTACK, year=ATTACK, rating=8.2,
            posterUrl='/missing\" onerror=window.pwned=1 x=\"', overview=ATTACK,
            cast=[ATTACK], trailerId=ATTACK, imdbId=ATTACK, sizeGB=ATTACK)
state = {'posts': [], 'requests': [], 'fail': False, 'config': {'radarrUrl':'http://fixture.invalid', 'sonarrUrl':'http://fixture.invalid', 'plexUrl':'http://fixture.invalid'}}

def route_request(route):
    req = route.request
    url = urlsplit(req.url)
    if url.hostname != 'tv.fixture':
        route.abort(); return
    path = url.path
    if path in ('/', '/setup'):
        route.fulfill(status=200, content_type='text/html', body=(ROOT/'web'/('setup.html' if path == '/setup' else 'index.html')).read_text()); return
    if not path.startswith('/api/'):
        route.fulfill(status=404, body=''); return
    state['requests'].append((req.method, path, parse_qs(url.query), req.headers.get('authorization')))
    if req.headers.get('authorization') != 'Bearer ' + TOKEN:
        route.fulfill(status=401, json={'detail':'unauthorized'}); return
    if req.method == 'POST':
        state['posts'].append((path, req.post_data_json if req.post_data else None))
        if state['fail']:
            route.fulfill(status=503, json={'detail':'fixture failure'}); return
        if path == '/api/config': state['config'].update(req.post_data_json)
        route.fulfill(status=200, json={'ok':True}); return
    if path == '/api/config': data = state['config']
    elif path.endswith('/history'): data = {'history':[{**item, 'action':'clean' if 'shows' in path else 'hidden' if 'discover' in path else 'keep'}]}
    elif path == '/api/calendar': data = {'calendar':[{**item, 'type':'movie', 'releaseDate':ATTACK}]}
    elif path == '/api/latest-release': data = {'version':ATTACK, 'htmlUrl':'javascript:window.pwned=1'}
    else: data = {'movies':[item], 'shows':[item]}
    route.fulfill(status=200, json=data)

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/usr/bin/google-chrome', headless=True, args=['--no-sandbox'])
    context = browser.new_context()
    context.route('**/*', route_request)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto('http://tv.fixture/')
    expect(page.locator('#contentArea')).to_contain_text('401')
    page.locator('[data-view="settings"]').click()
    page.locator('#loginToken').fill('wrong')
    page.get_by_role('button', name='Connect', exact=True).click()
    expect(page.locator('#toast')).to_contain_text('401')
    assert not state['posts']
    page.locator('#loginToken').fill(TOKEN)
    page.get_by_role('button', name='Connect', exact=True).click()
    page.locator('#sRadarrRoot').fill('/synthetic/movies')
    page.locator('#sRadarrQuality').fill('7')
    page.get_by_role('button', name='Save Settings', exact=True).click()
    expect(page.locator('#toast')).to_contain_text('Settings saved')
    assert state['posts'][-1][1]['radarrRootFolder'] == '/synthetic/movies'
    assert 'apiToken' not in state['posts'][-1][1]
    print('PASS missing/invalid auth zero mutation; token login and config save')
    page.locator('[data-view="movies"]').click()
    expect(page.locator('.single-card-title')).to_have_text(ATTACK)
    page.get_by_role('button', name='Block', exact=True).click()
    before = len(state['posts'])
    page.get_by_role('button', name='Undo', exact=True).click()
    page.wait_for_timeout(10200)
    assert len(state['posts']) == before
    expect(page.locator('.single-card-title')).to_have_text(ATTACK)
    state['fail'] = True
    page.get_by_role('button', name='Keep', exact=True).click()
    expect(page.locator('#toast')).to_contain_text('503')
    expect(page.locator('.single-card-title')).to_have_text(ATTACK)
    page.get_by_role('button', name='Block', exact=True).click()
    before = len(state['posts'])
    page.wait_for_timeout(9000)
    assert len(state['posts']) == before
    page.wait_for_timeout(1300)
    assert len(state['posts']) == before + 1
    expect(page.locator('.single-card-title')).to_have_text(ATTACK)
    print('PASS destructive 10s delay, Undo zero effects, HTTP failure recoverable')
    state['fail'] = False
    page.locator('[data-viewmode="grid"]').click()
    expect(page.locator('.card-title')).to_have_text(ATTACK)
    page.locator('.card-title').click()
    expect(page.locator('#detailTitle')).to_have_text(ATTACK)
    page.locator('#detailActions').get_by_role('button', name='Close', exact=True).click()
    page.locator('[data-view="discover"]').click()
    expect(page.locator('.card-title')).to_have_text(ATTACK)
    page.locator('.card-title').click()
    expect(page.locator('#detailTitle')).to_have_text(ATTACK)
    page.locator('#detailActions').get_by_role('button', name='Close', exact=True).click()
    page.locator('[data-view="history"]').click()
    expect(page.locator('.history-title')).to_have_count(3)
    state['fail'] = True
    page.get_by_role('button', name='Re-monitor', exact=True).click()
    expect(page.locator('#toast')).to_contain_text('503')
    expect(page.locator('.history-title')).to_have_count(3)
    state['fail'] = False
    page.locator('[data-view="calendar"]').click()
    expect(page.locator('.card-title')).to_contain_text(ATTACK)
    page.screenshot(path=str(OUT/'web-adversarial.png'))
    assert page.evaluate('window.pwned || 0') == 0
    assert not errors, errors
    print('PASS adversarial title/poster/entities in single/grid/detail/discover/history/calendar: no code execution')
    page.locator('[data-view="movies"]').click()
    page.locator('#searchInput').fill('img')
    page.wait_for_timeout(500)
    assert any(r[2].get('search') == ['img'] for r in state['requests'])
    page.evaluate('showFilter()')
    page.locator('[data-genre="Drama"]').click()
    page.locator('#fMinYear').fill('2000')
    page.locator('#fMaxYear').fill('2026')
    page.locator('[data-rating="7"]').click()
    page.get_by_role('button', name='Apply', exact=True).click()
    page.wait_for_timeout(300)
    assert any(r[2].get('genre') == ['Drama'] and r[2].get('min_year') == ['2000'] and r[2].get('max_year') == ['2026'] and r[2].get('min_rating') == ['7'] for r in state['requests'])
    print('PASS search/year/genre/rating filters transmitted')
    assert all(r[3] == 'Bearer ' + TOKEN for r in state['requests'] if r[0] == 'POST')
    (OUT/'browser-results.json').write_text(json.dumps({'page_errors': errors, 'requests':state['requests'], 'posts':state['posts']}, indent=2))
    browser.close()
