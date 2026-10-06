"""Real browser + real isolated backend bootstrap and process-restart proof."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT.parent/'tv-tenderr-audit/evidence'
TOKEN = 'synthetic-bootstrap-token'

with tempfile.TemporaryDirectory(prefix='tv-bootstrap-') as directory:
    dest = Path(directory)
    shutil.copy2(ROOT/'backend.py', dest/'backend.py')
    shutil.copytree(ROOT/'web', dest/'web')
    env = {k:v for k,v in os.environ.items() if not k.startswith(('RADARR_', 'SONARR_', 'PLEX_', 'TMDB_', 'TV_TENDERR_', 'BACKEND_', 'PYTHONPATH'))}
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    origin = f'http://127.0.0.1:{port}'
    log = (OUT/'bootstrap-server.log').open('w')
    def start():
        child = subprocess.Popen([sys.executable,'-m','uvicorn','backend:app','--host','127.0.0.1','--port',str(port)], cwd=dest, env=env, stdout=log, stderr=log)
        for _ in range(100):
            try:
                urllib.request.urlopen(origin+'/api/health', timeout=.2).close()
                return child
            except OSError:
                time.sleep(.05)
        child.terminate()
        raise RuntimeError('isolated backend did not start')
    child = start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='/usr/bin/google-chrome', headless=True, args=['--no-sandbox'])
            context = browser.new_context()
            # Only configuration API can reach backend. Block library/Arr paths and all external requests.
            def route(r):
                path = r.request.url.removeprefix(origin)
                if r.request.url.startswith(origin) and (path in ('/setup','/','/api/config','/api/save-env') or not path.startswith('/api/')):
                    r.continue_()
                else:
                    r.fulfill(status=503, json={'detail':'fixture blocks upstream'})
            context.route('**/*', route)
            page = context.new_page()
            page.goto(origin+'/')
            page.locator('#radarrUrl').fill('http://fixture.invalid:7878')
            page.locator('#radarrKey').fill('synthetic-arr')
            page.get_by_role('button', name='Next →').click()
            page.get_by_role('button', name='Next →').click()
            page.get_by_role('button', name='Save & Start').click()
            expect(page.locator('#status')).to_contain_text('400')
            assert not (dest/'.env').exists()
            page.get_by_role('button', name='← Back').click()
            page.get_by_role('button', name='← Back').click()
            page.locator('#bootstrapToken').fill(TOKEN)
            page.get_by_role('button', name='Next →').click()
            page.get_by_role('button', name='Next →').click()
            page.locator('#radarrRoot').fill('/synthetic/movies')
            page.get_by_role('button', name='Save & Start').click()
            expect(page.locator('#status')).to_contain_text('Configuration saved')
            assert page.evaluate("sessionStorage.getItem('tvTenderrToken')") == TOKEN
            page.screenshot(path=str(OUT/'web-bootstrap.png'))
            before = (dest/'.env').read_bytes()
            for token in ('', 'wrong'):
                response = context.request.post(origin+'/api/config', headers={'Authorization':'Bearer '+token}, data={'radarrUrl':'http://unwanted.invalid'})
                assert response.status == 401
                assert (dest/'.env').read_bytes() == before
            response = context.request.get(origin+'/api/config', headers={'Authorization':'Bearer '+TOKEN})
            assert response.status == 200
            assert TOKEN not in response.text() and 'synthetic-arr' not in response.text()
            child.terminate(); child.wait(timeout=10)
            child = start()
            response = context.request.get(origin+'/api/config', headers={'Authorization':'Bearer '+TOKEN})
            assert response.status == 200, response.text()
            assert response.json()['radarrRootFolder'] == '/synthetic/movies'
            assert response.json()['radarrQualityId'] == 4
            assert TOKEN not in response.text()
            browser.close()
            print('PASS real browser bootstrap: blank token 400/no file; successful local setup; missing/invalid token 401/no writes; process restart preserves auth/root/quality; config does not leak secrets')
    finally:
        child.terminate(); child.wait(timeout=10)
        log.close()
