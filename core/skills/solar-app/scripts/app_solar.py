"""Send /app conversation turns to solar-router, same contract as n8n."""
from __future__ import annotations
import json
import os
import subprocess
import uuid
from pathlib import Path
from interface_store import now_iso
import voice_work

VOICE_TIMEOUT_SEC = 90


def router_cmd(store):
    script = Path(store.solar_root) / 'core/skills/solar-router/scripts/run_router.py'
    python = os.environ.get('SOLAR_AI_ROUTER_PYTHON', 'python3')
    return [python, str(script)]


def payload(cid, text, request_id):
    return {
        'request_id': request_id,
        'session_id': 'app:' + cid,
        'user_id': os.environ.get('USER', 'louis'),
        'text': text,
        'channel': 'app',
        'mode': 'auto',
        'metadata': {'origin_channel': 'app', 'conversation_id': cid},
    }


def invoke(store, body, *, timeout=VOICE_TIMEOUT_SEC):
    proc = subprocess.run(
        router_cmd(store),
        input=json.dumps(body),
        text=True,
        capture_output=True,
        timeout=timeout,
        cwd=str(store.workspace),
        env=os.environ.copy(),
    )
    raw = (proc.stdout or '').strip()
    if not raw:
        raise ValueError((proc.stderr or 'Solar no ha respondido').strip()[:400])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError('Solar devolvió una respuesta ilegible') from exc
    if not isinstance(data, dict):
        raise ValueError('Solar devolvió una respuesta ilegible')
    return data


def attach_task(store, cid, text, request_id, task_id):
    """Project a router-queued task into the App expediente without a second queue."""
    root = voice_work.task_root(store)
    existing = store.get_row('SELECT * FROM runs WHERE task_id=?', (task_id,))
    if existing:
        with store.connect_db() as db:
            db.execute('INSERT OR IGNORE INTO app_work_links(run_id,conversation_id,thread_id) VALUES (?,?,?)',
                       (existing['run_id'], cid, existing['thread_id']))
        return existing['run_id']
    if not any((root / state / (task_id + '.md')).is_file()
               for state in ('queued', 'active', 'completed', 'error', 'cancelled')):
        return None
    thread_id = store.create_thread(text[:60])['thread_id']
    run_id = 'run_' + uuid.uuid4().hex[:10]
    run_dir = store.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    store.write_user_input(run_id, text)
    with store.connect_db() as db:
        db.execute(
            "INSERT INTO runs(run_id,request_id,thread_id,status,provider_requested,started_at,task_id) VALUES (?,?,?,'queued',?,?,?)",
            (run_id, request_id, thread_id, 'claude', now_iso(), task_id),
        )
        db.execute(
            "UPDATE threads SET state='queued',active_run_id=?,last_run_id=?,updated_at=? WHERE thread_id=?",
            (run_id, run_id, now_iso(), thread_id),
        )
        db.execute('INSERT OR IGNORE INTO app_work_links(run_id,conversation_id,thread_id) VALUES (?,?,?)',
                   (run_id, cid, thread_id))
    return run_id


def ask(store, cid, text, request_id, *, invoke_fn=invoke):
    response = invoke_fn(store, payload(cid, text, request_id))
    reply = str(response.get('reply_text') or '').strip()
    if response.get('status') != 'success' or not reply:
        raise ValueError(str(response.get('error') or 'Solar no ha respondido')[:400])
    decision = response.get('decision') if isinstance(response.get('decision'), dict) else {}
    task_id = decision.get('task_id')
    if decision.get('kind') == 'async_draft_created' and task_id:
        attach_task(store, cid, text, request_id, str(task_id))
    return reply[:4000]
