"""Loopback HTTP acceptance tests for voice/UI contracts, with a fake conductor."""
import http.client
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

CORE=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(CORE/'skills/solar-app/scripts'))
import host_server
from interface_store import InterfaceStore
import voice_work
import app_conversations

class VoiceHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.ws=Path(self.tmp.name).resolve()
        self.env=patch.dict(os.environ,{'SOLAR_ROOT':str(CORE.parent),'SOLAR_VOICE_OS_ENABLED':'1'})
        self.env.start();self.store=InterfaceStore(self.ws);self.store.ensure_runtime()
        self.server=ThreadingHTTPServer(('127.0.0.1',0),host_server.HostHandler)
        self.port=self.server.server_port
        original=voice_work.turn
        def decide(*args):return {'action':'dispatch','title':'Informe','thread_id':None,'reply':'Me pongo.'}
        self.patches=[patch.object(host_server,'PORT',self.port),patch.object(host_server,'_active_workspace',lambda:self.ws),patch.object(host_server,'_active_store',lambda:self.store),patch.object(voice_work,'turn',lambda *a,**kw:original(*a,**kw,conductor=decide))]
        for p in self.patches:p.start()
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        for p in reversed(self.patches):p.stop()
        self.env.stop();self.tmp.cleanup()
    def request(self,path,body=None,headers=None):
        c=http.client.HTTPConnection('127.0.0.1',self.port,timeout=8)
        h={'Content-Type':'application/json'};h.update(headers or {})
        c.request('POST' if body is not None else 'GET',path,json.dumps(body) if body is not None else None,h)
        r=c.getresponse();raw=r.read();status=r.status;c.close();return status,raw
    def test_full_request_open_and_cancel(self):
        status,raw=self.request('/api/app/conversations',{'workspace':str(self.ws)})
        self.assertEqual(status,200,raw);cid=json.loads(raw)['id']
        body={'workspace':str(self.ws),'text':'Prepara un resumen de los gastos de agosto','request_id':'one'}
        status,raw=self.request('/api/app/conversations/'+cid+'/messages',body)
        self.assertEqual(status,200,raw);result=json.loads(raw)
        self.assertIn('Me pongo con ello',result['messages'][-1]['text'])
        self.assertEqual(result['work'],[])
        app_conversations.tick(self.store)
        work=app_conversations.detail(self.store,cid)['work'][0]
        self.assertEqual(work['status'],'queued')
        run=self.store.get_run(work['run_id'])
        self.assertTrue((self.ws/'sun/runtime/async-tasks/queued'/(run['task_id']+'.md')).is_file())
        status,page=self.request('/app');self.assertEqual(status,200)
        status,raw=self.request('/api/app/runs/'+run['run_id']+'/cancel',{'workspace':str(self.ws)})
        self.assertEqual(json.loads(raw)['status'],'cancellation_requested')
        app_conversations.tick(self.store)
        from task_cancel import acknowledge
        root=voice_work.task_root(self.store)
        self.assertTrue((root/'cancellation'/(run['task_id']+'.json')).exists())
        acknowledge(root/'queued'/(run['task_id']+'.md'))
        app_conversations.tick(self.store)
        self.assertEqual(app_conversations.detail(self.store,cid)['work'][0]['status'],'cancelled')

    def test_retired_surfaces_do_not_create_threads(self):
        self.assertEqual(self.request('/work')[0],404)
        self.assertEqual(self.request('/api/work/threads')[0],404)
        self.assertEqual(self.request('/api/chat',{'message':'hello'})[0],410)
        self.assertEqual(self.store.list_threads(),[])

    def test_other_origin_cannot_dispatch(self):
        status,_=self.request('/api/voice/turn',{'workspace':str(self.ws),'text':'Prepara un informe','request_id':'x'},{'Origin':'https://evil.example'})
        self.assertEqual(status,403);self.assertEqual(self.store.list_runs(),[])
    def test_workspace_mismatch_and_invalid_json_shape(self):
        status,_=self.request('/api/voice/turn',{'workspace':'/another','text':'Prepara un informe','request_id':'x'})
        self.assertEqual(status,409)
        status,_=self.request('/api/voice/turn',['invalid'])
        self.assertEqual(status,400)
    def test_html_uses_text_content_for_untrusted_output(self):
        status,page=self.request('/app');self.assertEqual(status,200)
        self.assertNotIn(b'chatModel',page);self.assertNotIn(b'workerModel',page)
        status,script=self.request('/app.js');self.assertEqual(status,200)
        self.assertNotIn(b'innerHTML',script);self.assertIn(b'textContent',script)


if __name__=='__main__':unittest.main()
