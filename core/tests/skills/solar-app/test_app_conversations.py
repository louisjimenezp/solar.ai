"""End-to-end state contracts without calling a paid model or live workspace."""
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
from unittest.mock import patch

CORE=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(CORE/'skills/solar-app/scripts'))
from interface_store import InterfaceStore
import app_conversations as chats
import app_artifacts as artifacts
import voice_work


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.ws=Path(self.tmp.name).resolve()
        self.env=patch.dict(os.environ,{'SOLAR_ROOT':str(CORE.parent),'SOLAR_VOICE_OS_ENABLED':'1'})
        self.env.start(); self.addCleanup(self.env.stop); self.addCleanup(self.tmp.cleanup)
        self.store=InterfaceStore(self.ws); self.store.ensure_runtime(); self.cid=chats.create(self.store)['id']

    def test_worker_result_returns_to_original_chat_once_after_reload(self):
        data=chats.turn(self.store,self.cid,'Prepara una nota sobre pruebas locales','first')
        self.assertEqual(data['work'],[])
        self.assertFalse((self.ws/'sun/runtime/async-tasks/queued').exists())
        chats.tick(self.store)
        data=chats.detail(self.store,self.cid)
        self.assertEqual(len(data['work']),1)
        link=data['work'][0]; self.assertNotEqual(link['thread_id'],self.cid)
        run=self.store.get_run(link['run_id']); root=voice_work.task_root(self.store)
        self.assertEqual(root,self.ws/'sun/runtime/async-tasks')
        # A second user turn does not wait for the queued worker.
        second=chats.turn(self.store,self.cid,'¿Sigues aquí?','second',responder=lambda *_:'Sí, sigo aquí.')
        self.assertEqual(second['messages'][-1]['text'],'Sí, sigo aquí.')
        scripts=CORE/'skills/solar-async-tasks/scripts'
        env={**os.environ,'SOLAR_WORKSPACE':str(self.ws),'SOLAR_TASK_ROOT':str(root),'SOLAR_AI_ROUTER_PYTHON':sys.executable}
        router=self.ws/'fixture_router.py'
        router.write_text("import json; print(json.dumps({'status':'success','reply_text':'Nota de pruebas terminada.','provider_used':'claude'}))")
        for argv in (["bash",str(scripts/'start_next.sh')],
                     [sys.executable,str(scripts/'execute_active.py'),str(root/'active'/(run['task_id']+'.md')),str(router),run['task_id'],'Fixture'],
                     ['bash',str(scripts/'complete.sh'),run['task_id']]):
            proc=subprocess.run(argv,env=env,capture_output=True,text=True,timeout=15)
            self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
        reloaded=InterfaceStore(self.ws); reloaded.ensure_runtime()
        chats.tick(reloaded); chats.tick(reloaded)
        result=chats.detail(reloaded,self.cid)
        self.assertEqual(len([m for m in result['messages'] if m['id'].startswith('completion_')]),1)
        self.assertIn('Nota de pruebas',result['messages'][-1]['text'])
        d=chats.work_detail(reloaded,link['thread_id'])
        raw,_=artifacts.read(reloaded,d['artifacts'][0]['path'])
        self.assertIn(b'Nota de pruebas',raw)

    def test_replay_does_not_duplicate_and_rejects_cross_conversation(self):
        chats.turn(self.store,self.cid,'Prepara una nota','same')
        chats.turn(self.store,self.cid,'Prepara una nota','same')
        self.assertEqual(len(chats.detail(self.store,self.cid)['messages']),2)
        other=chats.create(self.store)['id']
        with self.assertRaises(ValueError): chats.turn(self.store,other,'Prepara una nota','same')
        chats.tick(self.store)
        self.assertEqual(len(self.store.list_runs()),1)

    def test_cancel_uses_canonical_queue_and_does_not_touch_other_chat(self):
        chats.turn(self.store,self.cid,'Prepara una nota','a');chats.tick(self.store)
        a=chats.detail(self.store,self.cid)['work'][0]
        other=chats.create(self.store)['id']
        chats.turn(self.store,other,'Prepara otra nota','b');chats.tick(self.store)
        b=chats.detail(self.store,other)['work'][0]
        chats.turn(self.store,self.cid,'Para','stop')
        self.assertTrue(self.store.get_run(a['run_id'])['cancellation_requested'])
        self.assertFalse(self.store.get_run(b['run_id'])['cancellation_requested'])
        chats.tick(self.store)
        run=self.store.get_run(a['run_id'])
        self.assertTrue((voice_work.task_root(self.store)/'cancellation'/(run['task_id']+'.json')).exists())

    def test_talk_uses_solar_router_not_a_private_conductor(self):
        with patch('app_conversations.app_solar.ask',return_value='Listo') as ask:
            self.assertEqual(chats.answer(self.store,self.cid,'hola','talk1'),'Listo')
        ask.assert_called_once()
        self.assertEqual(ask.call_args.args[1],self.cid)
        self.assertEqual(ask.call_args.args[2],'hola')
        self.assertEqual(ask.call_args.args[3],'talk1')

    def test_file_changes_and_path_boundaries(self):
        folder=self.ws/'planets/demo';folder.mkdir(parents=True);f=folder/'note.md';f.write_text('initial')
        artifacts.scan(self.store); self.assertEqual(artifacts.listing(self.store)['total'],1)
        f.write_text('changed'); artifacts._last.clear(); artifacts.scan(self.store)
        f.unlink(); artifacts._last.clear(); artifacts.scan(self.store)
        self.assertEqual([e['action'] for e in artifacts.listing(self.store)['events']],['deleted','modified'])
        with self.assertRaises(ValueError): artifacts.read(self.store,'planets/../../etc/passwd')
        with self.assertRaises(ValueError): artifacts.read(self.store,'planets/demo/.env')
        (folder/'escape.md').symlink_to('/etc/passwd')
        with self.assertRaises(ValueError): artifacts.read(self.store,'planets/demo/escape.md')

    def test_banned_conductor_models_never_reach_adapter(self):
        from voice_conductor import chat
        for model in ('solar','solar:latest','qwen3.5:0.8b',''):
            with patch.dict(os.environ,{'SOLAR_VOICE_CONDUCTOR_MODEL':model}), patch('voice_conductor.urllib.request.urlopen') as request:
                with self.assertRaises(ValueError): chat([])
                request.assert_not_called()

    def test_stop_before_publication_never_creates_task(self):
        chats.turn(self.store,self.cid,'Prepara un resumen de los gastos de agosto','pending')
        chats.turn(self.store,self.cid,'para','stop-pending')
        chats.tick(self.store)
        self.assertEqual(self.store.list_runs(),[])

    def test_file_list_reads_only_projection(self):
        with patch('app_artifacts.os.walk',side_effect=AssertionError('UI cannot scan folders')):
            self.assertEqual(artifacts.listing(self.store)['files'],[])
