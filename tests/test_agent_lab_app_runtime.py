from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import patch

from rag_ime.agent_lab_app_runtime import AppInputError, AppRequestStore, create_server
from tests.test_agent_lab_apps import write_app


class StandaloneRequestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'app-state.sqlite3'
        self.store = AppRequestStore(self.path, 'frozen-source-a')
        self.request = {'requestId':str(uuid.uuid4()),'actionId':'consult','input':{'question':'第七天能退吗？'}}

    def tearDown(self): self.temp.cleanup()

    def test_parallel_admission_keeps_one_logical_call(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            receipts = list(pool.map(lambda _: self.store.claim(self.request), range(6)))
        self.assertEqual(sum(created for _, created in receipts), 1)
        self.assertEqual({value['requestId'] for value, _ in receipts}, {self.request['requestId']})

    def test_completed_result_survives_restart_without_new_call(self):
        self.store.claim(self.request)
        self.store.finish(self.request['requestId'], 'completed', {'text':'第7天仍在范围内。','usage':{'total_tokens':33}})
        restarted = AppRequestStore(self.path, 'frozen-source-a')
        record, created = restarted.claim(self.request)
        self.assertFalse(created)
        self.assertEqual(record['state'], 'completed')
        self.assertEqual(record['result']['text'], '第7天仍在范围内。')
        self.assertEqual(restarted.history()[0]['input'], self.request['input'])

    def test_unsettled_old_owner_is_unconfirmed_and_never_replayed(self):
        self.store.claim(self.request)
        restarted = AppRequestStore(self.path, 'frozen-source-a')
        record, created = restarted.claim(self.request)
        self.assertFalse(created)
        self.assertEqual(record['state'], 'unconfirmed')
        # The original process may still settle; a new reader accepts that fact.
        self.store.finish(self.request['requestId'], 'completed', {'text':'原调用已完成'})
        self.assertEqual(restarted.read(self.request['requestId'])['state'], 'completed')

    def test_reused_id_cannot_change_input_or_frozen_sources(self):
        self.store.claim(self.request)
        with self.assertRaises(AppInputError):
            self.store.claim({**self.request,'input':{'question':'另一个问题'}})
        with self.assertRaises(AppInputError):
            AppRequestStore(self.path, 'different-source').claim(self.request)

    def test_only_the_admitting_runtime_can_settle_and_terminal_receipts_stay_fixed(self):
        self.store.claim(self.request)
        other = AppRequestStore(self.path, 'frozen-source-a')
        self.assertFalse(other.finish(self.request['requestId'], 'completed', {'text':'wrong owner'}))
        self.assertTrue(self.store.finish(self.request['requestId'], 'completed', {'text':'first settlement'}))
        self.assertFalse(self.store.finish(self.request['requestId'], 'failed', {'message':'late overwrite'}))
        self.assertEqual(other.read(self.request['requestId'])['result']['text'], 'first settlement')

    def test_call_limit_is_checked_before_creating_a_receipt(self):
        for _ in range(4): self.store.claim({**self.request,'requestId':str(uuid.uuid4())})
        with self.assertRaises(AppInputError): self.store.claim(self.request)
        self.assertIsNone(self.store.read(self.request['requestId']))
        self.assertEqual(len(self.store.history()), 4)

    def test_state_file_is_private_and_does_not_store_environment_credentials(self):
        self.store.claim(self.request)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('APP_API_KEY', json.dumps(self.store.history()))

    def test_local_server_rejects_foreign_host_even_when_origin_matches_it(self):
        root = write_app(Path(self.temp.name))
        with patch('rag_ime.agent_lab_app_runtime.provider_complete') as complete:
            server = create_server(root,'127.0.0.1',0)
            worker = threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                for path in ['/','/api/history']:
                    with self.assertRaises(HTTPError) as caught:
                        urlopen(Request(base+path,headers={'Host':f'foreign.test:{server.server_port}'}),timeout=3)
                    self.assertEqual(caught.exception.code,403)
                    caught.exception.close()
                headers = {'Host':f'foreign.test:{server.server_port}',
                           'Origin':f'http://foreign.test:{server.server_port}','Content-Type':'application/json'}
                request = {**self.request,'actionId':'answer'}
                with self.assertRaises(HTTPError) as caught:
                    urlopen(Request(base+'/api/invoke',data=json.dumps(request).encode(),headers=headers,method='POST'),timeout=3)
                self.assertEqual(caught.exception.code,403);caught.exception.close()
                with urlopen(base+'/api/history',timeout=3) as response: self.assertEqual(json.load(response)['records'],[])
                with urlopen(base,timeout=3) as response: self.assertEqual(response.headers['X-Frame-Options'],'DENY')
                complete.assert_not_called()
            finally:
                server.shutdown();server.server_close();worker.join(timeout=3)

    def test_http_browser_reconnect_reads_original_receipt_without_extra_provider_call(self):
        root = write_app(Path(self.temp.name))
        entered, release = threading.Event(), threading.Event()
        calls = []
        def complete(prompt, _spec):
            calls.append(prompt); entered.set(); release.wait(3)
            return {'text':'真实回执占位测试','usage':{'total_tokens':9}}
        with patch('rag_ime.agent_lab_app_runtime.provider_complete', side_effect=complete):
            server = create_server(root, '127.0.0.1', 0)
            worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
            base = f'http://127.0.0.1:{server.server_port}'
            request = {**self.request, 'actionId':'answer'}
            def read(path):
                with urlopen(base+path, timeout=3) as response: return json.load(response)
            def submit():
                with urlopen(Request(base+'/api/invoke',data=json.dumps(request).encode(),headers={'Content-Type':'application/json'},method='POST'), timeout=3) as response:
                    return response.status, json.load(response)
            try:
                self.assertEqual(submit()[0], 202); self.assertTrue(entered.wait(2))
                self.assertEqual(submit()[1]['record']['requestId'], request['requestId'])
                self.assertEqual(read('/api/history')['records'][0]['state'], 'running')
                self.assertEqual(len(calls), 1)
                release.set()
                deadline = time.monotonic()+3
                while time.monotonic() < deadline:
                    record = read('/api/requests/'+request['requestId'])['record']
                    if record['state']=='completed': break
                    time.sleep(.01)
                self.assertEqual(record['state'], 'completed')
                self.assertEqual(submit()[1]['record']['result']['text'], '真实回执占位测试')
                self.assertEqual(len(calls), 1)
                self.assertEqual(read('/api/history')['records'][0]['input'], request['input'])
            finally:
                release.set(); server.shutdown(); server.server_close(); worker.join(3)


if __name__ == '__main__': unittest.main()
