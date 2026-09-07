"""Application routes: SQLite projections, reviewed dictation and artifact preview."""
from pathlib import Path
import app_conversations as conversations
import app_artifacts as artifacts
import app_audio as audio
import voice_core
import voice_work

ASSETS = Path(__file__).resolve().parent.parent/'assets'


def get(handler,path,qs,store):
    if path=='/':
        handler.send_response(302);handler.send_header('Location','/app');handler.end_headers();return
    if path in ('/app','/app.js','/app.css'):
        asset={'/app':'app.html','/app.js':'app.js','/app.css':'app.css'}[path]
        mime='text/javascript' if asset.endswith('.js') else 'text/css' if asset.endswith('.css') else 'text/html'
        handler._send((ASSETS/asset).read_bytes(),content_type=mime+'; charset=utf-8');return
    if path=='/api/app/bootstrap':
        handler._send_json({'workspace':str(store.workspace),'enabled':voice_work.enabled(store),
            'conversations':store.list_rows('SELECT * FROM app_conversations ORDER BY updated_at DESC'),'threads':store.list_threads()});return
    if (qs.get('workspace') or [''])[0]!=str(store.workspace):
        handler._send_json({'error':'El espacio de trabajo ha cambiado. Recarga la aplicación.'},409);return
    if path.startswith('/api/app/conversations/'):
        handler._send_json(conversations.detail(store,path.rsplit('/',1)[-1]))
    elif path.startswith('/api/app/threads/'):
        handler._send_json(conversations.work_detail(store,path.rsplit('/',1)[-1]))
    elif path=='/api/app/files':
        handler._send_json(artifacts.listing(store,(qs.get('q') or [''])[0],(qs.get('planet') or [''])[0]))
    elif path=='/api/app/file':
        raw,mime=artifacts.read(store,(qs.get('path') or [''])[0]);handler._send(raw,content_type=mime)
    elif path=='/api/app/audio':
        handler._send_json(audio.status(store.workspace))
    elif path=='/api/app/logs':
        handler._send_json({'events':[{'type':'run.'+r['status'],'created_at':r['started_at'],'payload':{'run_id':r['run_id'],'summary':r['summary']}} for r in store.list_runs(40)],'logs':store.list_rows("SELECT run_id AS name,log AS text FROM app_run_content WHERE log!='' ORDER BY rowid DESC LIMIT 5")})
    else: handler._send_json({'error':'Not found'},404)


def post(handler,path,body,store):
    if body.get('workspace')!=str(store.workspace):
        handler._send_json({'error':'El espacio de trabajo ha cambiado. Recarga la aplicación.'},409);return
    if path=='/api/app/conversations': result=conversations.create(store)
    elif path.startswith('/api/app/conversations/') and path.endswith('/messages'):
        if not voice_work.enabled(store): raise ValueError('La conversación está desactivada en este servicio')
        result=conversations.turn(store,path.split('/')[-2],body.get('text'),body.get('request_id'))
    elif path.startswith('/api/app/runs/') and path.endswith('/cancel'):
        result=conversations.cancel(store,path.split('/')[-2])
    elif path=='/api/app/audio/start':
        conversations.require(store,body.get('conversation_id'))
        result=audio.start(store.workspace,body['conversation_id'])
    elif path in ('/api/app/audio/stop','/api/app/audio/discard'):
        result=audio.stop(store.workspace,body.get('id'),path.endswith('/discard'))
    elif path=='/api/app/speak':
        message=store.get_row("SELECT text FROM app_messages WHERE id=? AND role='assistant'",(body.get('message_id'),))
        if not message: raise KeyError('Message not found')
        voice_core.speak_brief(message['text']);result={'ok':True}
    else: handler._send_json({'error':'Not found'},404);return
    handler._send_json(result)
