"""Voice contracts: durable authority, dedupe, state and cancellation (no LLM)."""
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

CORE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(CORE / 'skills/solar-app/scripts'))
from interface_store import InterfaceStore
import voice_work
from voice_conductor import validate, local_preparation


def dispatch(text, threads, root):
    return {'action':'dispatch', 'title':'Informe', 'thread_id':None, 'reply':'Me pongo.'}


class VoiceWorkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'SOLAR_ROOT':str(CORE.parent), 'SOLAR_VOICE_OS_ENABLED':'1'})
        self.env.start()
        self.store = InterfaceStore(self.ws)
        self.store.ensure_runtime()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def turn(self, text='Prepara un informe de pruebas', key='req1', conductor=dispatch, **kw):
        return voice_work.turn(self.store, text, key, conductor=conductor, **kw)

    def test_migration_is_repeatable_and_preserves_threads(self):
        thread = self.store.create_thread('Existing')
        self.store.ensure_runtime()
        self.assertEqual(self.store.get_thread(thread['thread_id'])['title'], 'Existing')
        self.assertEqual(self.store.get_row('SELECT version FROM schema_version')['version'], 5)

    def test_original_authority_and_queued_linkage(self):
        r = self.turn()
        self.assertEqual(r['status'], 'queued')
        run = self.store.get_run(r['run_id'])
        self.assertEqual(run['task_id'], r['task_id'])
        authority = json.loads((self.store.runs_dir/r['run_id']/'authority.json').read_text())
        self.assertEqual(authority['source_text'], 'Prepara un informe de pruebas')
        self.assertEqual(authority['scope'], 'local_preparation')
        self.assertTrue((voice_work.task_root(self.store)/'queued'/(r['task_id']+'.md')).exists())

    def test_request_replay_does_not_enqueue_twice(self):
        a=self.turn(); b=self.turn()
        self.assertEqual(a,b)
        self.assertEqual(len(self.store.list_runs()),1)
        with self.assertRaises(ValueError): self.turn('Prepara otra cosa')

    def test_conductor_cannot_self_authorize(self):
        for i,text in enumerate(['Quizá estaría bien un informe', 'Prepara y envía el informe', 'Borra el informe']):
            r=self.turn(text, str(i))
            self.assertEqual(r['status'],'needs_you')
        self.assertEqual(self.store.list_runs(), [])

    def test_unknown_thread_and_malformed_decision_fail_closed(self):
        def bad(*args): return {**dispatch(*args), 'thread_id':'invented'}
        self.assertEqual(self.turn('abre ese hilo', conductor=bad)['status'], 'needs_you')
        self.assertEqual(self.store.list_runs(), [])

    def test_model_timeout_does_not_dispatch_an_ambiguous_request(self):
        def unavailable(*args): raise TimeoutError()
        self.assertEqual(self.turn('¿Qué encargos están activos?', conductor=unavailable)['status'],'needs_you')
        self.assertEqual(self.store.list_runs(), [])

    def test_explicit_local_preparation_bypasses_model_and_keeps_authority(self):
        result = self.turn(conductor=lambda *args: self.fail('model should not authorize dispatch'))
        self.assertEqual(result['status'], 'queued')
        self.assertEqual(self.store.get_thread(result['thread_id'])['title'], 'Un informe de pruebas')

    def test_stop_does_not_call_model_or_claim_immediate_cancel(self):
        r=self.turn()
        stopped=self.turn('para', 'stop1', thread_id=r['thread_id'], conductor=lambda *a: self.fail('LLM for stop'))
        self.assertEqual(stopped['status'],'cancellation_requested')
        self.assertEqual(self.store.get_run(r['run_id'])['status'],'queued')
        self.assertTrue((voice_work.task_root(self.store)/'cancellation'/(r['task_id']+'.json')).exists())

    def test_stop_unknown_target_asks(self):
        self.assertEqual(self.turn('para')['status'],'needs_you')

    def test_completion_materializes_result_and_deduplicates_event(self):
        r=self.turn(); root=voice_work.task_root(self.store)
        (root/'completed').mkdir(); (root/'logs').mkdir()
        (root/'queued'/(r['task_id']+'.md')).rename(root/'completed'/(r['task_id']+'.md'))
        (root/'logs'/(r['task_id']+'.log')).write_text('# Task\n## Result\nEl informe está listo.\nDetalle')
        events=[]; self.store.set_event_hook(lambda *e: events.append(e))
        d=voice_work.detail(self.store,r['thread_id']); voice_work.reconcile(self.store)
        self.assertEqual(d['thread']['state'],'done')
        self.assertIn('Detalle', d['runs'][0]['output'])
        self.assertEqual(len(events),1)

    def test_late_run_does_not_close_newer_run(self):
        r=self.turn(); root=voice_work.task_root(self.store)
        self.store.update_thread_last_run(r['thread_id'],'newer')
        (root/'cancelled').mkdir()
        (root/'queued'/(r['task_id']+'.md')).rename(root/'cancelled'/(r['task_id']+'.md'))
        voice_work.reconcile(self.store)
        self.assertEqual(self.store.get_thread(r['thread_id'])['state'],'running')
        self.assertEqual(self.store.get_thread(r['thread_id'])['active_run_id'],'newer')

    def test_long_queued_task_is_not_deleted_as_stale(self):
        r=self.turn()
        with self.store.connect_db() as c: c.execute("UPDATE runs SET started_at='2000-01-01T00:00:00+00:00'")
        with self.assertRaises(ValueError): self.store.delete_thread(r['thread_id'])

    def test_disabled_does_not_mutate(self):
        self.store.env['SOLAR_VOICE_OS_ENABLED']='0'
        with self.assertRaises(ValueError): self.turn()
        self.assertEqual(self.store.list_runs(), [])

    def test_stop_missing_run_records_a_replayable_answer(self):
        thread=self.store.create_thread('Old thread')
        self.store.update_thread_last_run(thread['thread_id'], 'missing')
        a=self.turn('para','stop-old',thread_id=thread['thread_id'])
        b=self.turn('para','stop-old',thread_id=thread['thread_id'])
        self.assertEqual(a['status'],'needs_you')
        self.assertEqual(a,b)
        self.assertIsNotNone(self.store.get_row("SELECT response_json FROM voice_requests WHERE request_id='stop-old'")['response_json'])

    def test_failed_migration_rolls_back_schema_changes(self):
        migration=self.store.migrations_dir/'006_broken.sql'
        migration.write_text('ALTER TABLE threads ADD COLUMN should_rollback TEXT; INSERT INTO missing_table VALUES(1);')
        with self.assertRaises(sqlite3.OperationalError):self.store._apply_migrations()
        columns=self.store.list_rows('PRAGMA table_info(threads)')
        self.assertNotIn('should_rollback',{c['name'] for c in columns})
        self.assertEqual(self.store.get_row('SELECT version FROM schema_version')['version'],5)

    def test_schema_rejects_additional_worker_commands(self):
        with self.assertRaises(ValueError): validate({**dispatch(None,None,None),'command':'rm'},set())

if __name__ == '__main__': unittest.main()
