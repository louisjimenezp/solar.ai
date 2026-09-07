"""App conversation turns invoke solar-router as channel=app."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

CORE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(CORE / 'skills/solar-app/scripts'))
from interface_store import InterfaceStore
import app_solar
import app_conversations as chats


class AppSolarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name).resolve()
        self.env = patch.dict(os.environ, {'SOLAR_ROOT': str(CORE.parent), 'SOLAR_VOICE_OS_ENABLED': '1'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.tmp.cleanup)
        self.store = InterfaceStore(self.ws)
        self.store.ensure_runtime()
        self.cid = chats.create(self.store)['id']

    def test_finished_before_link_is_reconciled_once(self):
        for state, expected in [('completed', 'succeeded'), ('error', 'failed'), ('cancelled', 'cancelled')]:
            with self.subTest(state=state):
                task_id = 'fast-' + state
                root = self.ws / 'sun/runtime/async-tasks'
                folder = root / state
                folder.mkdir(parents=True, exist_ok=True)
                (folder / (task_id + '.md')).write_text('---\nid: ' + task_id + '\n---\n')
                logs = root / 'logs'
                logs.mkdir(exist_ok=True)
                (logs / (task_id + '.log')).write_text('Metadata\n## Result\nResumen completo.')
                fake = lambda *_: {'status': 'success', 'reply_text': 'Me pongo con ello.',
                    'decision': {'kind': 'async_draft_created', 'task_id': task_id}}
                app_solar.ask(self.store, self.cid, 'Consulta', task_id, invoke_fn=fake)
                run = self.store.get_row('SELECT * FROM runs WHERE task_id=?', (task_id,))
                self.assertIsNotNone(run)
                chats.tick(self.store)
                chats.tick(self.store)
                self.assertEqual(self.store.get_run(run['run_id'])['status'], expected)
                messages = self.store.list_rows('SELECT * FROM app_messages WHERE id=?', ('completion_' + run['run_id'],))
                self.assertEqual(len(messages), 1)
                if state == 'completed':
                    result = self.store.runs_dir / run['run_id'] / 'output.md'
                    self.assertEqual(result.read_text(), 'Resumen completo.')
                    self.assertTrue(self.store.list_rows('SELECT * FROM artifacts WHERE run_id=?', (run['run_id'],)))
                (folder / (task_id + '.md')).unlink()
                self.assertEqual(app_solar.attach_task(self.store, self.cid, 'Consulta', task_id, task_id), run['run_id'])

    def test_payload_is_the_n8n_contract_with_channel_voice(self):
        body = app_solar.payload(self.cid, 'Hola Solar', 'req1')
        self.assertEqual(body['channel'], 'app')
        self.assertEqual(body['mode'], 'auto')
        self.assertEqual(body['session_id'], 'app:' + self.cid)
        self.assertEqual(body['text'], 'Hola Solar')
        self.assertEqual(body['metadata']['origin_channel'], 'app')

    def test_direct_reply_does_not_create_work(self):
        def fake(_store, body):
            self.assertEqual(body['channel'], 'app')
            return {'status': 'success', 'reply_text': 'Aquí estoy.', 'decision': {'kind': 'direct_reply', 'task_id': None}}
        self.assertEqual(app_solar.ask(self.store, self.cid, 'Hola', 'r1', invoke_fn=fake), 'Aquí estoy.')
        self.assertEqual(self.store.list_runs(), [])

    def test_async_draft_is_linked_into_the_conversation(self):
        task_id = 'task-voice-1'
        queued = self.ws / 'sun/runtime/async-tasks/queued'
        queued.mkdir(parents=True)
        (queued / (task_id + '.md')).write_text('---\nid: ' + task_id + '\n---\n')
        def fake(_store, _body):
            return {
                'status': 'success',
                'reply_text': 'Me pongo con ello. Te aviso por aquí cuando termine.',
                'decision': {'kind': 'async_draft_created', 'task_id': task_id},
            }
        reply = app_solar.ask(self.store, self.cid, 'Investiga esto a fondo', 'r2', invoke_fn=fake)
        self.assertIn('Me pongo', reply)
        work = chats.detail(self.store, self.cid)['work']
        self.assertEqual(len(work), 1)
        self.assertEqual(self.store.get_run(work[0]['run_id'])['task_id'], task_id)


if __name__ == '__main__':
    unittest.main()
