from __future__ import annotations

import base64
import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from itertools import count
from pathlib import Path
from unittest.mock import patch

from rag_ime.agent_lab.app_runtime import build_prompt, validate_input, AppInputError
from rag_ime.agent_lab.app_sources import freeze_source
from rag_ime.agent_lab.apps import AgentLabAppApplication, AgentLabAppStore
from rag_ime.agent_lab.projects import AgentLabProjectStore, AgentLabProjectValidationError, AgentLabProjectConflict, AgentLabProjectNotFound


MODEL = {'provider':'configured','model':'test-model','thinkingLevel':'medium'}


def write_app(root: Path, title: str = '规则助手') -> Path:
    source = root/'app'; source.mkdir(exist_ok=True)
    (source/'app.json').write_text(json.dumps({'schemaVersion':'paw.lab-app-source.v1','title':title,'description':'按项目方法处理输入',
        'html':'index.html','skill':'SKILL.md','context':['rules.md'],
        'actions':[{'id':'answer','title':'处理问题','prompt':'依据材料回答并指出缺失信息。',
                    'inputSchema':{'type':'object','properties':{'question':{'type':'string','title':'问题','maxLength':300}},'required':['question']}}]},ensure_ascii=False))
    (source/'index.html').write_text('<h1>规则助手</h1><script>window.ready=Boolean(window.pawApp);</script>')
    (source/'SKILL.md').write_text('---\nname: rules-assistant\ndescription: Answer from the supplied rules.\n---\n\n只使用材料，不猜测。')
    (source/'rules.md').write_text('在第 7 天仍可申请，第 8 天不能申请。')
    return source


class LabAppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name).resolve()
        self.db = self.root/'paw.sqlite'; self.workspace = self.root/'workspace'; self.workspace.mkdir()
        self.apps = AgentLabAppStore(self.db)
        self.projects = AgentLabProjectStore(self.db,create_guide=lambda _conn,_project:{'sessionId':'guide-1','workspace':{'kind':'managed','path':str(self.workspace),'createdAtMs':1}},
            prepare_app=lambda conn,project,value:self.apps.prepare(conn,project,value,MODEL))
        self.project = self.projects.command({'action':'create','expectedRevision':0,'clientRequestId':'project','input':{'description':'规则工作台'}})['project']
        write_app(self.workspace)

    def tearDown(self): self.tmp.cleanup()

    def prepare(self, client='prepare', app_id=''):
        receipt = self.projects.command({'action':'prepare_app','projectId':self.project['projectId'],'expectedRevision':self.project['revision'],
            'clientRequestId':client,'input':{'directory':'app',**({'appId':app_id} if app_id else {})}})
        self.project = receipt['project']; return receipt['application']

    def command(self, app: dict, action: str, value: dict, client: str):
        return self.apps.command({'appId':app['appId'],'expectedRevision':app['revision'],'action':action,'input':value,'clientRequestId':client})

    def test_per_call_model_is_durable_and_does_not_rewrite_evaluated_version(self):
        app = self.prepare()
        selection = {'provider':'openai-codex','model':'gpt-5.6-luna','thinkingLevel':'max'}
        seen = []
        runner = AgentLabAppApplication(self.apps,complete=lambda **kwargs:seen.append(kwargs) or {'text':'answer'},abort=lambda _:None,start_workers=False)
        receipt = self.command(app,'invoke',{'version':1,'actionId':'answer','values':{'question':'day 7'},'model':selection},'selected-model')
        call, version = self.apps.call_input(receipt['call']['callId'])
        self.assertEqual(call['model'],selection)
        self.assertEqual(version['spec']['model'],MODEL)
        runner.run_call(call['callId'])
        self.assertEqual(seen[0]['model'],selection)
        self.assertIn('在第 7 天仍可申请',seen[0]['prompt'])
        self.assertEqual(self.apps.read({'appId':app['appId']})['version']['contentHash'],version['contentHash'])
        runner.close()

    def test_prepare_freezes_files_without_activation_or_execution(self):
        app = self.prepare()
        self.assertIsNone(app['activeVersion']); self.assertEqual(app['version']['fileCount'],3)
        (self.workspace/'app/rules.md').write_text('源文件已经改变。')
        filename = self.apps.download({'appId':app['appId'],'version':1,'target':'standalone'})
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(filename['base64']))) as archive:
            self.assertEqual(archive.read('rules.md').decode(),'在第 7 天仍可申请，第 8 天不能申请。')
            runtime = archive.read('app.py').decode()
            self.assertNotIn('from rag_ime',runtime); compile(runtime,'app.py','exec')
            self.assertNotIn(str(self.root),''.join(archive.read(name).decode() for name in archive.namelist()))
        self.assertEqual(self.apps.read({'appId':app['appId']})['calls'],[])

    def test_external_workspace_is_a_frozen_browser_dependency_without_tool_authority(self):
        path = self.workspace/'app/app.json'; source = json.loads(path.read_text())
        source['externalWorkspace'] = {'title':'空间工作台','url':'http://127.0.0.1:5173/'}
        path.write_text(json.dumps(source)); app = self.prepare()
        self.assertEqual(app['version']['spec']['externalWorkspace'],source['externalWorkspace'])
        source['externalWorkspace']['url'] = 'https://example.org/workbench'
        path.write_text(json.dumps(source)); newer = self.prepare('workspace-2',app['appId'])
        self.assertEqual(newer['latestVersion'],2)
        archive = self.apps.download({'appId':app['appId'],'version':1,'target':'standalone'})
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(archive['base64']))) as output:
            frozen = json.loads(output.read('app.json'))
            self.assertEqual(frozen['externalWorkspace']['url'],'http://127.0.0.1:5173/')
            self.assertIn('没有随此包复制',output.read('README.md').decode())
        self.assertEqual(self.apps.read({'appId':app['appId']})['calls'],[])

    def test_app_identity_is_frozen_and_legacy_apps_keep_their_default(self):
        legacy = self.prepare()
        self.command(legacy,'activate',{'version':1},'identity-default')
        self.assertEqual(self.apps.read({})['items'][0]['installation']['icon']['symbol'], 'assistant')
        path = self.workspace/'app/app.json'; source = json.loads(path.read_text())
        source['appearance'] = {'accent':'blue','icon':{'symbol':'analytics','background':'#215d74'}}
        path.write_text(json.dumps(source)); app = self.prepare('identity-2', legacy['appId'])
        self.command(app,'activate',{'version':2},'identity-custom')
        manifest = self.apps.read({})['items'][0]['installation']
        self.assertEqual(manifest['icon'], source['appearance']['icon'])
        self.assertEqual(manifest['accent'], 'blue')
        source['appearance']['icon']['background'] = 'url(https://example.org/image)'
        path.write_text(json.dumps(source))
        with self.assertRaises(AgentLabProjectValidationError): freeze_source(self.workspace,'app',MODEL)

    def test_external_workspace_rejects_credentials_and_non_browser_destinations(self):
        path = self.workspace/'app/app.json'; source = json.loads(path.read_text())
        for url in ['javascript:alert(1)', 'file:///private/data', 'http://example.org/',
                    'https://user:password@example.org/', 'https://example.org/?token=secret',
                    'https://example.org/#secret', 'https://example.org/\"; frame-src *', 'http://127.0.0.1:0/']:
            with self.subTest(url=url):
                source['externalWorkspace'] = {'title':'工作台','url':url}; path.write_text(json.dumps(source))
                with self.assertRaises(AgentLabProjectValidationError): freeze_source(self.workspace,'app',MODEL)

    def test_versions_are_immutable_and_activation_can_restore_previous(self):
        app = self.prepare(); app = self.command(app,'activate',{'version':1},'install')['app']
        (self.workspace/'app/SKILL.md').write_text('新方法，先核对边界。')
        newer = self.prepare('prepare-2',app['appId'])
        self.assertEqual(newer['latestVersion'],2); self.assertEqual(newer['activeVersion'],1)
        active = self.command(newer,'activate',{'version':2},'update')['app']
        rollback = self.command(active,'activate',{'version':1},'rollback')['app']
        self.assertEqual(rollback['activeVersion'],1)
        with sqlite3.connect(self.db) as conn:
            with self.assertRaises(sqlite3.IntegrityError): conn.execute("UPDATE agent_lab_app_versions SET payload_json='{}'")

    def test_export_is_deterministic_and_both_targets_share_source(self):
        app = self.prepare()
        first = self.apps.download({'appId':app['appId'],'version':1,'target':'standalone'})
        second = self.apps.download({'appId':app['appId'],'version':1,'target':'standalone'})
        paw = self.apps.download({'appId':app['appId'],'version':1,'target':'paw'})
        self.assertEqual(first,second); self.assertEqual(first['contentHash'],paw['contentHash'])
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(first['base64']))) as a, zipfile.ZipFile(io.BytesIO(base64.b64decode(paw['base64']))) as b:
            for path in ['app.json','index.html','SKILL.md','rules.md','app.py']: self.assertEqual(a.read(path),b.read(path))

    def test_prepared_export_keeps_its_runtime_after_product_code_changes(self):
        app = self.prepare()
        first = self.apps.download({'appId':app['appId'],'version':1,'target':'standalone'})
        original_read = Path.read_text
        def changed_runtime(path, *args, **kwargs):
            if path.name == 'app_runtime.py': return '# a later incompatible runner\n'
            return original_read(path,*args,**kwargs)
        with patch.object(Path,'read_text',changed_runtime):
            later = self.apps.download({'appId':app['appId'],'version':1,'target':'standalone'})
        self.assertEqual(first,later)
        with patch('rag_ime.agent_lab.apps.export_zip',side_effect=AssertionError('A saved package must not be rebuilt')):
            self.assertEqual(first,self.apps.download({'appId':app['appId'],'version':1,'target':'standalone'}))

    def test_new_export_recipe_creates_a_version_without_mutating_old_downloads(self):
        app = self.prepare()
        original = self.apps.download({'appId':app['appId'],'version':1,'target':'standalone'})
        with patch('rag_ime.agent_lab.app_sources.EXPORT_RECIPE_VERSION','a-later-export-recipe'):
            updated = self.prepare('new-export-recipe',app['appId'])
        self.assertEqual(updated['latestVersion'],2)
        self.assertEqual(original,self.apps.download({'appId':app['appId'],'version':1,'target':'standalone'}))

    def test_source_cannot_be_silently_replaced_by_export_support_files(self):
        source = self.workspace/'app'
        spec = json.loads((source/'app.json').read_text()); spec['context']=['README.md']
        (source/'app.json').write_text(json.dumps(spec)); (source/'README.md').write_text('The actual business rules')
        with self.assertRaisesRegex(AgentLabProjectValidationError,'保留'):
            self.prepare()

    def test_commands_replay_exactly_and_scope_cannot_cross(self):
        app = self.prepare()
        first = self.command(app,'activate',{'version':1},'same')
        replay = self.command(app,'activate',{'version':1},'same')
        self.assertTrue(replay['replayed']); self.assertEqual(first['app'],replay['app'])
        with self.assertRaises(AgentLabProjectConflict): self.command(app,'deactivate',{},'same')
        other = AgentLabAppStore(self.db,scope_id='other')
        self.assertEqual(other.read()['items'],[])
        with self.assertRaises(AgentLabProjectNotFound): other.read({'appId':app['appId']})
        with self.assertRaises(AgentLabProjectNotFound): other.download({'appId':app['appId'],'version':1,'target':'paw'})

    def test_recent_history_does_not_hide_an_older_active_call(self):
        app = self.prepare()
        request = {'version':1,'actionId':'answer','values':{'question':'待处理的问题'}}
        with patch('rag_ime.agent_lab.apps._now',side_effect=count(100).__next__):
            active = self.command(app,'invoke',request,'long-running')['call']
            for index in range(31):
                call = self.command(app,'invoke',request,f'newer-{index}')['call']
                self.apps.update_call(call['callId'],state='completed',result_json='{}')
        calls = self.apps.read({'appId':app['appId']})['calls']
        self.assertEqual(len(calls),31)
        self.assertIn(active['callId'],[call['callId'] for call in calls])
        self.assertEqual(sum(call['state']=='completed' for call in calls),30)

    def test_resuming_respects_the_same_concurrency_limit_as_new_calls(self):
        app = self.prepare()
        request = {'version':1,'actionId':'answer','values':{'question':'问题'}}
        interrupted = self.command(app,'invoke',request,'interrupted')['call']
        self.apps.update_call(interrupted['callId'],state='interrupted')
        for index in range(4): self.command(app,'invoke',request,f'active-{index}')
        with self.assertRaisesRegex(AgentLabProjectConflict,'4 项'):
            self.command(app,'resume',{'callId':interrupted['callId']},'resume-full')
        self.assertEqual(self.apps.call_input(interrupted['callId'])[0]['state'],'interrupted')

    def test_intake_rejects_symlinks_and_credential_files(self):
        source = self.workspace/'app'; (source/'rules.md').unlink(); (source/'rules.md').symlink_to(self.root/'outside.md')
        (self.root/'outside.md').write_text('outside')
        with self.assertRaises(AgentLabProjectValidationError): self.prepare()
        (source/'rules.md').unlink(); (source/'rules.md').write_text('ok')
        spec = json.loads((source/'app.json').read_text()); spec['context']=['.env']
        (source/'app.json').write_text(json.dumps(spec)); (source/'.env').write_text('SECRET=not-for-export')
        with self.assertRaises(AgentLabProjectValidationError): self.prepare()

    def test_input_schema_is_project_specific_and_validated_before_call(self):
        app = self.prepare()
        with self.assertRaises(AgentLabProjectValidationError): self.command(app,'invoke',{'version':1,'actionId':'answer','values':{}},'missing')
        with self.assertRaises(AgentLabProjectValidationError): self.command(app,'invoke',{'version':1,'actionId':'answer','values':{'question':'q','password':'no'}},'extra')
        self.assertEqual(self.apps.read({'appId':app['appId']})['calls'],[])
        values = validate_input({'properties':{'count':{'type':'integer','minimum':0,'maximum':3}},'required':['count']},{'count':2})
        self.assertEqual(values,{'count':2})
        with self.assertRaises(AppInputError): validate_input({'properties':{'count':{'type':'integer'}}},{'count':True})

    def test_execution_retains_identity_and_only_actual_completion_sets_result(self):
        app = self.prepare(); observed = []
        def complete(**value):
            observed.append(value); value['on_session']('app-session-1')
            return {'text':'第 7 天可申请。','usage':{'inputTokens':40,'outputTokens':10},'receipt':{'settlementReceiptId':'actual-settlement'}}
        application = AgentLabAppApplication(self.apps,complete=complete,abort=lambda _id:None,start_workers=False)
        request = {'appId':app['appId'],'expectedRevision':app['revision'],'action':'invoke','input':{'version':1,'actionId':'answer','values':{'question':'第七天可以申请吗？'}},'clientRequestId':'invoke-1'}
        queued = application.command(request)['call']; self.assertEqual(queued['state'],'queued')
        replay = application.command(request)['call']; self.assertEqual(replay['callId'],queued['callId'])
        self.assertEqual(observed,[])
        application.run_call(queued['callId']); application.run_call(queued['callId'])
        result = self.apps.read({'appId':app['appId'],'callId':queued['callId']})['call']
        self.assertEqual(result['state'],'completed'); self.assertEqual(result['sessionId'],'app-session-1'); self.assertEqual(len(observed),1)
        self.assertEqual(application.session_identity(queued['callId'])['owner_app_id'],app['appId'])
        frozen = freeze_source(self.workspace,'app',MODEL)
        self.assertEqual(observed[0]['prompt'],build_prompt(frozen['spec'],frozen['files'],'answer',{'question':'第七天可以申请吗？'}))
        application.close()

    def test_queued_cancel_never_runs_and_interrupted_calls_keep_their_original_id(self):
        app = self.prepare(); calls = []
        application = AgentLabAppApplication(self.apps,complete=lambda **value:calls.append(value),abort=lambda _id:None,start_workers=False)
        request = {'version':1,'actionId':'answer','values':{'question':'q'}}
        queued = self.command(app,'invoke',request,'start')['call']
        self.command(app,'cancel',{'callId':queued['callId']},'stop'); application.run_call(queued['callId'])
        self.assertEqual(calls,[])
        self.assertEqual(self.apps.read({'appId':app['appId'],'callId':queued['callId']})['call']['state'],'cancelled')
        second = self.command(app,'invoke',request,'start-2')['call']
        self.apps.update_call(second['callId'],state='interrupted')
        resumed = self.command(app,'resume',{'callId':second['callId']},'resume')['call']
        self.assertEqual(resumed['callId'],second['callId']); self.assertEqual(resumed['state'],'queued')
        application.close()

    def test_interrupted_stop_can_be_reconciled_after_abort_transport_failure(self):
        app = self.prepare(); attempts = []
        def abort(session_id):
            attempts.append(session_id)
            if len(attempts) == 1: raise ConnectionError('temporary transport failure')
        application = AgentLabAppApplication(self.apps,complete=lambda **_value:None,abort=abort,start_workers=False)
        call = self.command(app,'invoke',{'version':1,'actionId':'answer','values':{'question':'q'}},'start')['call']
        self.apps.update_call(call['callId'],state='interrupted',session_id='real-session')
        request = {'appId':app['appId'],'expectedRevision':app['revision'],'action':'cancel','input':{'callId':call['callId']},'clientRequestId':'stop'}
        application.command(request)
        pending = self.apps.read({'appId':app['appId'],'callId':call['callId']})['call']
        self.assertEqual(pending['state'],'interrupted'); self.assertTrue(pending['cancelRequested'])
        application.command(request)
        stopped = self.apps.read({'appId':app['appId'],'callId':call['callId']})['call']
        self.assertEqual(stopped['state'],'cancelled'); self.assertEqual(attempts,['real-session','real-session'])
        application.close()


if __name__ == '__main__': unittest.main()
