import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import httpx
import backend


class CorrectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_read_await_modify_write_serialized(self):
        # Deliberately yield between loading and saving via the real keep route's
        # upstream GET; a lock around save alone loses updates here.
        async def upstream(request):
            await asyncio.sleep(.005)
            return httpx.Response(200, json={'id': int(request.url.path.split('/')[-1]), 'title':'Synthetic', 'images':[]})
        original = httpx.AsyncClient
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'decisions.json'
            with patch.object(backend, 'DECISIONS_FILE', path), patch.object(backend, 'decision_lock', asyncio.Lock()), patch.dict(os.environ, {backend.API_TOKEN_ENV:'synthetic'}):
                transport = httpx.ASGITransport(app=backend.app)
                async with original(transport=transport, base_url='http://fixture') as client:
                    with patch.object(backend.httpx, 'AsyncClient', side_effect=lambda **kw: original(transport=httpx.MockTransport(upstream))):
                        responses = await asyncio.gather(*(client.post(f'/api/movies/{i}/keep', headers={'Authorization':'Bearer synthetic'}) for i in range(1, 21)))
                self.assertTrue(all(r.status_code == 200 for r in responses))
                self.assertEqual(20, len(backend.load_json_store(path)))

    async def test_queued_old_token_rechecked_after_lock(self):
        with patch.object(backend, 'decision_lock', asyncio.Lock()), patch.dict(os.environ, {backend.API_TOKEN_ENV:'old'}):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=backend.app), base_url='http://fixture') as client:
                await backend.decision_lock.acquire()
                task = asyncio.create_task(client.get('/api/config', headers={'Authorization':'Bearer old'}))
                await asyncio.sleep(.02)
                os.environ[backend.API_TOKEN_ENV] = 'new'
                backend.decision_lock.release()
                self.assertEqual(401, (await task).status_code)

    async def test_config_roundtrip_literals_blank_token_and_failed_write(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {backend.API_TOKEN_ENV:'synthetic'}):
            path = Path(directory)/'.env'
            values = {'RADARR_ROOT_FOLDER': "Z:\\Media #1\\Roy's ${HOME}", 'TV_TENDERR_API_TOKEN':'synthetic', 'RADARR_KEY':'synthetic # key'}
            backend.write_env_values(path, values)
            self.assertEqual(values, backend.read_env_values(path))
            self.assertEqual(0o600, path.stat().st_mode & 0o777)
            with patch.object(backend, 'ENV_FILE', path):
                backend.persist_config({'apiToken':'', 'radarrKey':''})
                self.assertEqual('synthetic', backend.read_env_values(path)['TV_TENDERR_API_TOKEN'])
                before = path.read_bytes()
                prior = backend.RADARR_URL
                with patch.object(backend.os, 'replace', side_effect=OSError('synthetic failure')):
                    with self.assertRaises(OSError): backend.persist_config({'radarrUrl':'http://fixture.invalid'})
                self.assertEqual(before, path.read_bytes())
                self.assertEqual(prior, backend.RADARR_URL)

    async def test_clean_partial_failure_preserves_history_and_stops(self):
        calls = []
        def upstream(request):
            calls.append((request.method, request.url.path))
            if request.method == 'GET' and '/series/' in request.url.path:
                return httpx.Response(200, json={'title':'Synthetic', 'images':[]})
            if request.url.path.endswith('/episodefile'):
                return httpx.Response(200, json=[{'id':1,'size':100}, {'id':2,'size':200}])
            return httpx.Response(204 if request.url.path.endswith('/1') else 503)
        original = httpx.AsyncClient
        with tempfile.TemporaryDirectory() as directory, patch.object(backend, 'SHOW_DECISIONS_FILE', Path(directory)/'shows.json'):
            backend.save_show_decisions({'9':{'action':'keep'}})
            with patch.object(backend.httpx, 'AsyncClient', side_effect=lambda **kw: original(transport=httpx.MockTransport(upstream))):
                with self.assertRaises(backend.HTTPException) as caught:
                    await backend.clean_show(9)
            self.assertEqual(503, caught.exception.status_code)
            self.assertIn('after 1 deletes', caught.exception.detail)
            self.assertEqual({'9':{'action':'keep'}}, backend.load_show_decisions())
            self.assertFalse(any(method == 'PUT' for method, _ in calls))

    async def test_bootstrap_requires_token_before_writing(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(backend, 'ENV_FILE', Path(directory)/'.env'), patch.dict(os.environ, {backend.API_TOKEN_ENV:''}):
            for handler in (backend.update_config, backend.save_env):
                with self.assertRaises(backend.HTTPException) as caught:
                    await handler({'radarrKey':'synthetic'})
                self.assertEqual(400, caught.exception.status_code)
                self.assertFalse(backend.ENV_FILE.exists())

    async def test_bad_quality_is_400_and_no_write(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(backend, 'ENV_FILE', Path(directory)/'.env'):
            with self.assertRaises(backend.HTTPException) as caught:
                backend.persist_config({'radarrQualityId':'bad'})
            self.assertEqual(400, caught.exception.status_code)
            self.assertFalse(backend.ENV_FILE.exists())
