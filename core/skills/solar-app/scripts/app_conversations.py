"""Persistent assistant conversations linked to independently executed work threads."""
from __future__ import annotations
import re
import threading
import uuid
from voice_conductor import EXTERNAL
from interface_store import now_iso
import app_solar
import voice_work


def create(store, title='New conversation'):
    cid = 'chat_' + uuid.uuid4().hex
    now = now_iso()
    with store.connect_db() as db:
        db.execute('INSERT INTO app_conversations VALUES (?,?,?,?)', (cid, title[:100], now, now))
    return {'id': cid, 'title': title}


def require(store, cid):
    row = store.get_row('SELECT * FROM app_conversations WHERE id=?', (cid,))
    if row is None:
        raise KeyError('Conversation not found')
    return row


def add_message(store, cid, role, text, *, mid=None, request_id=None, thread_id=None):
    with store.connect_db() as db:
        db.execute('INSERT OR IGNORE INTO app_messages(id,conversation_id,role,text,created_at,request_id,work_thread_id) VALUES (?,?,?,?,?,?,?)',
                   (mid or uuid.uuid4().hex, cid, role, text, now_iso(), request_id, thread_id))
        db.execute('UPDATE app_conversations SET updated_at=? WHERE id=?', (now_iso(), cid))


def reconcile(store):
    voice_work.reconcile(store)
    links = store.list_rows('SELECT l.*,r.status,r.summary,r.error FROM app_work_links l JOIN runs r ON l.run_id=r.run_id WHERE l.delivered=0')
    for link in links:
        if link['status'] not in ('succeeded', 'failed', 'cancelled'):
            continue
        if link['status'] == 'succeeded':
            text = 'El encargo está listo. ' + (link['summary'] or 'Puedes abrir el resultado.')
        elif link['status'] == 'cancelled':
            text = 'El encargo se ha detenido.'
        else:
            text = 'El encargo no se pudo completar. Abre la ejecución para ver el error.'
        # Stable message ID makes polling and process restart idempotent.
        add_message(store, link['conversation_id'], 'assistant', text,
                    mid='completion_' + link['run_id'], thread_id=link['thread_id'])
        with store.connect_db() as db:
            db.execute('UPDATE app_work_links SET delivered=1 WHERE run_id=?', (link['run_id'],))


def detail(store, cid):
    conversation = require(store, cid)
    return {'conversation': conversation,
            'messages': store.list_rows('SELECT * FROM app_messages WHERE conversation_id=? ORDER BY rowid', (cid,)),
            'work': store.list_rows('SELECT l.*,r.status,r.summary,r.provider_used,r.provider_requested,r.cancellation_requested,t.title FROM app_work_links l JOIN runs r ON r.run_id=l.run_id JOIN threads t ON t.thread_id=l.thread_id WHERE l.conversation_id=? ORDER BY r.started_at', (cid,))}


def answer(store, cid, text, request_id='turn'):
    """Talk goes to Solar (router), never a private conductor."""
    return app_solar.ask(store, cid, text, request_id)


_locks = {}
_locks_guard = threading.Lock()


def turn(store, cid, text, request_id, responder=answer):
    require(store, cid)
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 4000:
        raise ValueError('Write a message of 1 to 4000 characters')
    if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',request_id):
        raise ValueError('Invalid request id')
    with _locks_guard:
        lock = _locks.setdefault((str(store.workspace), cid), threading.Lock())
    if not lock.acquire(blocking=False):
        raise ValueError('This conversation is answering. Wait before sending another message.')
    try:
        old = store.get_row('SELECT * FROM app_messages WHERE request_id=?', (request_id,))
        if old:
            if old['text'] != text or old['conversation_id'] != cid:
                raise ValueError('Request id already used')
            if store.get_row('SELECT id FROM app_messages WHERE id=?', ('reply_'+request_id,)):
                return detail(store, cid)
        else:
            add_message(store, cid, 'user', text, request_id=request_id)
        with store.connect_db() as db:
            db.execute("UPDATE app_conversations SET title=? WHERE id=? AND title='New conversation'", (text[:80], cid))
        if voice_work.local_preparation(text) or text.casefold().strip(' .!¿?') in voice_work.STOP:
            with store.voice_lock:
                if voice_work.local_preparation(text):
                    with store.connect_db() as db:
                        db.execute('UPDATE app_messages SET dispatch_pending=1 WHERE request_id=?',(request_id,))
                    add_message(store,cid,'assistant','Me pongo con ello. Prepararé el resultado y te avisaré aquí.',mid='reply_'+request_id)
                elif text.casefold().strip(' .!¿?') in voice_work.STOP:
                    with store.connect_db() as db:
                        pending=db.execute('UPDATE app_messages SET dispatch_pending=0 WHERE conversation_id=? AND dispatch_pending=1',(cid,)).rowcount
                        active=store.list_rows("SELECT l.run_id FROM app_work_links l JOIN runs r ON r.run_id=l.run_id WHERE l.conversation_id=? AND r.status IN ('queued','running')",(cid,))
                        if len(active)==1:
                            db.execute('UPDATE runs SET cancellation_requested=1 WHERE run_id=?',(active[0]['run_id'],))
                    reply='Lo estoy parando.' if pending or len(active)==1 else 'Selecciona el encargo que quieres detener en el panel de actividad.'
                    add_message(store,cid,'assistant',reply,mid='reply_'+request_id)
        elif EXTERNAL.search(text):
            add_message(store,cid,'assistant','Esa acción requiere aprobación formal antes de ejecutarse. No la he encolado.',mid='reply_'+request_id)
        else:
            try:
                try:
                    reply = responder(store, cid, text, request_id)
                except TypeError:
                    reply = responder(store, cid, text)
            except Exception:
                reply = 'Solar no ha respondido. Puedes volver a intentarlo o revisar el estado de Solar.'
            add_message(store, cid, 'assistant', reply, mid='reply_'+request_id)
        return detail(store, cid)
    finally:
        lock.release()


def tick(store):
    """Host reconciliation, never an executor: SQLite intents -> canonical queue."""
    # Serialize claim/publication with stop requests through the same runtime lock.
    with store.voice_lock:
        pending=store.list_rows('SELECT * FROM app_messages WHERE dispatch_pending=1 ORDER BY rowid') if voice_work.enabled(store) else []
        for message in pending:
            cid=message['conversation_id']
            previous=store.list_rows('SELECT role,text FROM app_messages WHERE conversation_id=? AND request_id IS NOT ? ORDER BY rowid DESC LIMIT 6',(cid,message['request_id']))
            context='\n'.join(m['role']+': '+m['text'][:1000] for m in reversed(previous))
            try:
                result=voice_work.turn(store,message['text'],message['request_id'],context=context)
                with store.connect_db() as db:
                    if result.get('run_id'):
                        db.execute('INSERT OR IGNORE INTO app_work_links(run_id,conversation_id,thread_id) VALUES (?,?,?)',(result['run_id'],cid,result['thread_id']))
                        db.execute('UPDATE app_messages SET work_thread_id=? WHERE id=?',(result['thread_id'],'reply_'+message['request_id']))
                    db.execute('UPDATE app_messages SET dispatch_pending=0 WHERE id=?',(message['id'],))
                if not result.get('run_id'):
                    add_message(store,cid,'assistant',result['reply'],mid='dispatch_'+message['request_id'])
            except (ValueError,OSError) as exc:
                add_message(store,cid,'assistant','No se pudo encolar el encargo. Revisa el estado de Solar.',mid='dispatch_'+message['request_id'])
                with store.connect_db() as db:
                    db.execute('UPDATE app_messages SET dispatch_pending=0 WHERE id=?',(message['id'],))
    for run in store.list_rows("SELECT task_id FROM runs WHERE cancellation_requested=1 AND task_id IS NOT NULL AND status IN ('queued','running')"):
        voice_work.cancel_task(voice_work.task_root(store),run['task_id'])
    reconcile(store)
    # Project bounded run content into SQLite; the application reads these records.
    for run in store.list_runs(100):
        fields=[]
        for filename in ('input.md','output.md'):
            path=store.runs_dir/run['run_id']/filename
            fields.append(path.read_text()[:100000] if path.is_file() else '')
        logpath=voice_work.task_root(store)/'logs'/((run.get('task_id') or run['run_id'])+'.log')
        log=logpath.read_text()[-16000:] if logpath.is_file() else ''
        with store.connect_db() as db:
            db.execute('INSERT OR REPLACE INTO app_run_content VALUES (?,?,?,?)',(run['run_id'],*fields,log))
            if fields[1]:
                path=str((store.runs_dir/run['run_id']/'output.md').relative_to(store.workspace))
                db.execute('INSERT OR IGNORE INTO artifacts VALUES (?,?,?,?,?,?)',('app_'+run['run_id'],run['run_id'],'file',path,'output.md',now_iso()))


def work_detail(store,thread_id):
    thread=store.get_thread(thread_id)
    if thread is None: raise KeyError(thread_id)
    runs=store.list_rows("SELECT r.*,COALESCE(c.input,'') AS input,COALESCE(c.output,'') AS output FROM runs r LEFT JOIN app_run_content c ON c.run_id=r.run_id WHERE r.thread_id=? ORDER BY r.started_at",(thread_id,))
    return {'thread':thread,'runs':runs,'artifacts':store.list_rows('SELECT a.* FROM artifacts a JOIN runs r ON r.run_id=a.run_id WHERE r.thread_id=?',(thread_id,))}


def cancel(store,run_id):
    with store.connect_db() as db:
        run=db.execute('SELECT status FROM runs WHERE run_id=?',(run_id,)).fetchone()
        if run is None: raise KeyError(run_id)
        if run['status'] not in ('queued','running','active'): return {'status':run['status']}
        db.execute('UPDATE runs SET cancellation_requested=1 WHERE run_id=?',(run_id,))
    return {'run_id':run_id,'status':'cancellation_requested'}
