"""Real-Chrome rendering regression against intercepted, synthetic responses only.

Run with a Python interpreter containing playwright; no live backend is contacted.
"""
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ATTACK = '\"\'><img src=x onerror=window.pwned=1>&quot;);window.pwned=1;//'
POSTER = '/missing\" onerror=window.pwned=1 x=\"'
ENTITY = 'literal &lt;svg onload=window.pwned=1&gt; &amp; &#39;'
ITEM = dict(id=1, tmdbId=10, movieId=1, title=ATTACK, year=2024, rating=8.2,
            posterUrl=POSTER, backdropUrl='javascript:window.pwned=1',
            overview=ENTITY, cast=[ATTACK], trailerId=ATTACK, imdbId=ATTACK)


def intercept(route):
    req = route.request
    if req.url == 'http://tv.fixture/':
        route.fulfill(status=200, content_type='text/html', body=(ROOT / 'web/index.html').read_text())
    elif req.url.startswith('http://tv.fixture/api/'):
        path = req.url.split('?', 1)[0]
        if path == 'http://tv.fixture/api/config':
            data = {'backendUrl': ATTACK, 'radarrUrl': ENTITY, 'sonarrUrl': ATTACK,
                    'plexUrl': ATTACK, 'radarrRootFolder': ENTITY,
                    'sonarrRootFolder': ATTACK, 'radarrQualityId': 7, 'sonarrQualityId': 8}
        elif path.endswith('/history'):
            data = {'history': [{**ITEM, 'action': 'keep'}]}
        elif path.endswith('/calendar'):
            data = {'calendar': [{**ITEM, 'episodeTitle': ENTITY, 'releaseDate': ATTACK}]}
        else:
            data = {'movies': [ITEM], 'shows': [ITEM]}
        route.fulfill(status=200, json=data)
    else:
        route.abort()


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/usr/bin/google-chrome', headless=True, args=['--no-sandbox'])
    context = browser.new_context()
    context.route('**/*', intercept)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto('http://tv.fixture/')
    expect(page.locator('.single-card-title')).to_have_text(ATTACK)
    page.get_by_role('button', name='Discover', exact=True).focus()
    page.keyboard.press('Enter')
    expect(page.locator('#pageTitle')).to_have_text('Discover')
    page.locator('#discoverTabs [data-type="shows"]').focus()
    page.keyboard.press('Space')
    expect(page.locator('#discoverTabs [data-type="shows"]')).to_have_class('mode-tab active')
    page.get_by_role('button', name='Top Rated', exact=False).focus()
    page.keyboard.press('Enter')
    expect(page.locator('#sortBar [data-sort="vote_average.desc"]')).to_have_class('filter-chip active')
    page.get_by_role('button', name='Movies', exact=True).click()
    expect(page.locator('.single-card-overview')).to_have_text(ENTITY)
    assert page.locator('[onerror]').count() == 0
    page.locator('[data-viewmode="grid"]').click()
    page.locator('.card-title').click()
    expect(page.locator('#detailTitle')).to_have_text(ATTACK)
    expect(page.locator('#detailOverview div').last).to_have_text(ENTITY)
    assert page.locator('#detailOverview img, #detailOverview svg').count() == 0
    assert page.locator('#detailBackdrop').get_attribute('src') == ''
    page.locator('#detailActions').get_by_role('button', name='Close').click()
    page.locator('[data-view="discover"]').click()
    page.locator('.card-title').click()
    expect(page.locator('#detailOverview div').last).to_have_text(ENTITY)
    page.locator('#detailActions').get_by_role('button', name='Close').click()
    page.locator('[data-view="history"]').click()
    expect(page.locator('.history-title')).to_have_count(3)
    page.locator('[data-view="calendar"]').click()
    expect(page.locator('.card-title')).to_have_text(ATTACK)
    page.locator('[data-view="settings"]').click()
    expect(page.locator('#sBackendUrl')).to_have_value(ATTACK)
    expect(page.locator('#sRadarrUrl')).to_have_value(ENTITY)
    expect(page.locator('#sSonarrRoot')).to_have_value(ATTACK)
    assert page.locator('#contentArea img, #contentArea svg').count() == 0
    assert page.locator('[onerror]').count() == 0
    assert page.evaluate('window.pwned || 0') == 0
    assert not errors, errors
    browser.close()
    print('PASS synthetic adversarial titles, poster attributes, entities, detail views and settings: no execution; keyboard navigation/tabs/sort')
