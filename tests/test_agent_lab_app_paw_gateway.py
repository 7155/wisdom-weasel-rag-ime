from __future__ import annotations

import io
import json
import tempfile
import threading
import time
import unittest
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs
from urllib.request import Request, urlopen

from rag_ime.agent_lab_app_runtime import AppInputError, create_server
from rag_ime.agent_lab_app_sources import export_zip, freeze_source
from tests.test_agent_lab_apps import write_app


class PawGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        source = write_app(self.root)
        spec = json.loads((source/'app.json').read_text())
        spec['model'] = {'provider':'openai-codex','model':'gpt-5.6-luna','thinkingLevel':'max'}
        (source/'app.json').write_text(json.dumps(spec))
        self.app_id = 'extension:lab-'+'a'*32
        self.version = {**freeze_source(self.root, 'app', spec['model']), 'appId':self.app_id,'version':9}
        _, archive = export_zip(self.version, 'standalone')
        self.exported = self.root/'exported'
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped: zipped.extractall(self.exported)
        self.commands = []
        self.hold = False
        self.bad_hash = False
        self.lose_admission = False
        self.drop_poll = False
        self.owner_state = 'queued'
        self.owner_started = threading.Event()
        self.owner_cancelled = threading.Event()
        test = self

        class Owner(BaseHTTPRequestHandler):
            def log_message(self, *_args): pass

            def respond(self, value):
                body = json.dumps(value).encode()
                self.send_response(200); self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)

            def app(self): return {'appId':test.app_id,'revision':3,'activeVersion':9}

            def call(self):
                return {'appId':test.app_id,'version':9,'callId':'lab-app-call-'+'b'*32,'sessionId':'agent:owner',
                        'state':test.owner_state,'error':'',
                        'progress':{'stage':'answering','text':'Partial','model':{'provider':'openai-codex','model':'gpt-5.6-luna'}},
                        'result':{'text':'A completed owner answer','usage':{'totalTokens':27}} if test.owner_state == 'completed' else {}}

            def do_GET(self):
                query = parse_qs(urlsplit(self.path).query)
                if 'callId' in query:
                    if test.drop_poll:
                        test.drop_poll = False; self.close_connection = True; return
                    if not test.hold and test.owner_state != 'cancelled': test.owner_state = 'completed'
                    self.respond({'ok':True,'app':self.app(),'call':self.call()})
                else:
                    self.respond({'ok':True,'app':self.app(),'version':{'appId':test.app_id,'version':9,
                                 'contentHash':'wrong' if test.bad_hash else test.version['contentHash']}})

            def do_POST(self):
                command = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                test.commands.append(command)
                if command['action'] == 'invoke':
                    test.owner_state = 'running'; test.owner_started.set()
                    if test.lose_admission:
                        self.close_connection = True
                        return
                elif command['action'] == 'cancel':
                    test.owner_state = 'cancelled'; test.owner_cancelled.set()
                self.respond({'ok':True,'app':self.app(),'call':self.call(),
                              'clientRequestId':command['clientRequestId'],'replayed':False})

        self.owner = ThreadingHTTPServer(('127.0.0.1',0), Owner)
        self.owner_thread = threading.Thread(target=self.owner.serve_forever,daemon=True); self.owner_thread.start()
        self.environment = patch.dict('os.environ', {'APP_PAW_GATEWAY_URL':f'http://127.0.0.1:{self.owner.server_port}',
                                      'APP_API_KEY':'','APP_API_BASE_URL':''})
        self.environment.start()
        self.server = create_server(self.exported,'127.0.0.1',0)
        self.worker = threading.Thread(target=self.server.serve_forever,daemon=True); self.worker.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.worker.join(timeout=2)
        self.owner.shutdown(); self.owner.server_close(); self.owner_thread.join(timeout=2)
        self.environment.stop(); self.temp.cleanup()

    def post(self, path, value):
        with urlopen(Request(self.base+path,data=json.dumps(value).encode(),headers={'Content-Type':'application/json'},method='POST'),timeout=3) as response:
            return json.load(response)

    def read(self, path):
        with urlopen(self.base+path,timeout=3) as response: return json.load(response)

    def request(self): return {'requestId':str(uuid.uuid4()),'actionId':'answer','input':{'question':'Use the configured Luna channel'}}

    def settled(self, request_id):
        for _ in range(80):
            record = self.read('/api/requests/'+request_id)['record']
            if record['state'] != 'running': return record
            time.sleep(.025)
        self.fail('request did not settle')

    def test_exported_app_uses_existing_paw_model_without_an_api_key_and_reconnects_once(self):
        request = self.request()
        self.post('/api/invoke', request)
        record = self.settled(request['requestId'])
        self.assertEqual(record['state'],'completed',record.get('message'))
        self.assertEqual(record['result']['text'],'A completed owner answer')
        self.assertEqual(record['result']['transport'],'paw_pi_gateway')
        self.assertEqual(record['result']['runtime']['sessionId'],'agent:owner')
        self.assertEqual(self.post('/api/invoke',request)['record'],record)
        self.assertEqual(len(self.commands),1)
        self.assertEqual(self.commands[0]['input'],{'version':9,'actionId':'answer','values':request['input']})
        self.assertTrue(self.read('/health')['configured'])
        self.assertNotIn('apiKey',json.dumps(self.commands))

    def test_wrong_frozen_version_fails_before_any_owner_invocation(self):
        self.bad_hash = True
        request = self.request(); self.post('/api/invoke',request)
        record = self.settled(request['requestId'])
        self.assertEqual(record['state'],'failed')
        self.assertIn('版本',record['message'])
        self.assertEqual(self.commands,[])

    def test_stop_reaches_the_paw_owner_and_never_creates_another_call(self):
        self.hold = True
        request = self.request(); self.post('/api/invoke',request)
        self.assertTrue(self.owner_started.wait(2))
        record = self.post('/api/cancel',{'requestId':request['requestId']})['record']
        self.assertEqual(record['state'],'cancelled')
        self.assertTrue(self.owner_cancelled.wait(2))
        self.assertEqual([command['action'] for command in self.commands],['invoke','cancel'])
        self.assertEqual(self.commands[-1]['input']['callId'],'lab-app-call-'+'b'*32)
        self.post('/api/invoke',request)
        self.assertEqual([command['action'] for command in self.commands],['invoke','cancel'])

    def test_lost_owner_admission_is_unconfirmed_and_is_not_automatically_replayed(self):
        self.lose_admission = True
        request = self.request(); self.post('/api/invoke',request)
        record = self.settled(request['requestId'])
        self.assertEqual(record['state'],'unconfirmed')
        self.post('/api/invoke',request)
        self.assertEqual(len(self.commands),1)

    def test_gateway_configuration_does_not_allow_an_external_destination(self):
        with patch.dict('os.environ', {'APP_PAW_GATEWAY_URL':'https://example.org'}):
            with self.assertRaises(AppInputError): create_server(self.exported,'127.0.0.1',0)

    def test_restart_reconciles_a_known_owner_call_without_submitting_another_prompt(self):
        import sqlite3
        from contextlib import closing
        self.drop_poll = True
        request = self.request(); self.post('/api/invoke', request)
        deadline = time.monotonic()+3
        while time.monotonic() < deadline:
            with closing(sqlite3.connect(self.exported/'.app-state.sqlite3')) as connection:
                row = connection.execute('SELECT state FROM app_requests WHERE request_id=?',(request['requestId'],)).fetchone()
            if row and row[0] == 'unconfirmed': break
            time.sleep(.02)
        self.assertEqual(row[0], 'unconfirmed')
        self.server.shutdown(); self.server.server_close(); self.worker.join(2)
        self.server = create_server(self.exported,'127.0.0.1',0)
        self.worker = threading.Thread(target=self.server.serve_forever,daemon=True); self.worker.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        record = self.read('/api/requests/'+request['requestId'])['record']
        self.assertEqual(record['state'],'completed')
        self.assertEqual(record['result']['text'],'A completed owner answer')
        self.assertEqual(len(self.commands),1)


if __name__ == '__main__': unittest.main()
