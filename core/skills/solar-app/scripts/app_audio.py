"""Local microphone capture with explicit state, bounded duration and local STT."""
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
import voice_core as vc
import voice_config as config

_lock = threading.RLock()
_session = None


def status(workspace):
    with _lock:
        if not _session or _session['workspace'] != str(workspace):
            return {'state':'idle'}
        return {k:v for k,v in _session.items() if k not in ('proc','path','workspace')}


def start(workspace, conversation):
    global _session
    with _lock:
        if _session and _session['state'] in ('recording','transcribing'):
            raise ValueError('A recording is already in progress')
        ok, hint = vc.check_voice_deps(require_whisper=True)
        if not ok:
            raise ValueError(hint)
        sid = uuid.uuid4().hex
        path = Path(tempfile.gettempdir()) / ('solar-audio-'+sid+'.wav')
        config.prepare_capture(path)
        argv = config.rec_argv(path)
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=config.subprocess_env())
        _session = dict(id=sid, workspace=str(workspace), conversation_id=conversation, state='recording', started=time.time(), text='', proc=proc, path=path)
        threading.Thread(target=_limit, args=(workspace,sid), daemon=True).start()
        return status(workspace)


def _limit(workspace, sid):
    for _ in range(240):
        time.sleep(0.25)
        with _lock:
            if not _session or _session['id'] != sid or _session['state'] != 'recording':
                return
            if _session['proc'].poll() is not None:
                stop(workspace, sid)
                return
    stop(workspace, sid)


def stop(workspace, sid, discard=False):
    with _lock:
        s = _session
        if not s or s['id'] != sid or s['workspace'] != str(workspace):
            raise ValueError('Recording not found')
        if discard:
            s['state'] = 'discarded'
            vc._stop_rec(s['proc'])
            if not s.get('transcribing'):
                s['path'].unlink(missing_ok=True)
            return status(workspace)
        if s['state'] != 'recording':
            return status(workspace)
        s['state'] = 'transcribing'
        s['transcribing'] = True
        threading.Thread(target=_transcribe, args=(s,), daemon=True).start()
        return status(workspace)


def _transcribe(s):
    try:
        vc._stop_rec(s['proc'])
        text = vc.transcribe(s['path'])
        with _lock:
            if s['state'] == 'transcribing':
                s.update(state='ready' if text.strip() and not text.startswith('[voice]') else 'error', text=text.strip() or 'No se detectó voz.')
    except Exception:
        with _lock:
            if s['state'] == 'transcribing':
                s.update(state='error', text='No se pudo transcribir. Revisa el micrófono y vuelve a intentarlo.')
    finally:
        s['path'].unlink(missing_ok=True)
