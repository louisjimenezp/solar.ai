"""Bounded, read-only artifact browser and durable change observations."""
from pathlib import Path
import os
import threading
import time
from interface_store import now_iso

TEXT = {'.md', '.txt', '.csv', '.json', '.py', '.js', '.ts', '.css', '.html', '.yaml', '.yml', '.sql'}
MEDIA = {'.png':'image/png', '.jpg':'image/jpeg', '.jpeg':'image/jpeg', '.webp':'image/webp', '.pdf':'application/pdf'}
SKIP = {'node_modules', '__pycache__', 'venv', 'dist', 'build', 'runtime', 'backups'}
_lock = threading.Lock()
_last = {}


def resolve(store, relative):
    p = Path(relative)
    if p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0] not in ('sun','planets') or any(x.startswith('.') for x in p.parts):
        raise ValueError('File is outside the artifact browser')
    target = (store.workspace / p).resolve()
    if not target.is_relative_to(store.workspace) or target.suffix.lower() not in TEXT | MEDIA.keys():
        raise ValueError('Unsupported file')
    # Runtime previews are limited to actual run results, not logs or authority files.
    if 'runtime' in p.parts:
        if target.name != 'output.md' or target.parent.parent != store.runs_dir.resolve():
            raise ValueError('Runtime file is not a work result')
    return target


def read(store, relative):
    target = resolve(store, relative)
    with target.open('rb') as f:
        raw = f.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError('Preview limited to 4 MB')
    return raw, MEDIA.get(target.suffix.lower(), 'text/plain; charset=utf-8')


def scan(store):
    key = str(store.workspace)
    with _lock:
        if time.monotonic() - _last.get(key, 0) < 10:
            return
        files = {}
        complete = True
        for base in ('sun', 'planets'):
            for folder, dirs, names in os.walk(store.workspace / base, followlinks=False):
                dirs[:] = sorted(d for d in dirs if not d.startswith('.') and d not in SKIP and not (Path(folder)/d).is_symlink())
                for name in sorted(names):
                    p = Path(folder)/name
                    if name.startswith('.') or p.is_symlink() or p.suffix.lower() not in TEXT | MEDIA.keys():
                        continue
                    try:
                        s = p.stat()
                        files[str(p.relative_to(store.workspace))] = (s.st_size, s.st_mtime_ns)
                    except OSError:
                        complete = False
                    if len(files) >= 15000:
                        complete = False
                        break
                if not complete and len(files) >= 15000:
                    break
        prior = {r['path']:r for r in store.list_rows('SELECT * FROM app_file_snapshot')}
        with store.connect_db() as db:
            for path, (size, modified) in files.items():
                old = prior.get(path)
                action = 'created' if not old or not old['present'] else 'modified' if old['size'] != size or old['modified'] != modified else None
                if action and prior:
                    db.execute('INSERT INTO app_file_events(path,action,created_at) VALUES (?,?,?)', (path,action,now_iso()))
                db.execute('INSERT OR REPLACE INTO app_file_snapshot VALUES (?,?,?,1)', (path,size,modified))
            if complete:
                for path, old in prior.items():
                    if old['present'] and path not in files:
                        db.execute('UPDATE app_file_snapshot SET present=0 WHERE path=?', (path,))
                        db.execute('INSERT INTO app_file_events(path,action,created_at) VALUES (?,?,?)', (path,'deleted',now_iso()))
        _last[key] = time.monotonic()


def listing(store, query='', planet=''):
    rows = store.list_rows('SELECT * FROM app_file_snapshot WHERE present=1 ORDER BY modified DESC')
    rows = [r for r in rows if query.casefold() in r['path'].casefold() and (not planet or r['path'].startswith('planets/'+planet+'/'))]
    return {'files':rows[:250], 'total':len(rows), 'events':store.list_rows('SELECT * FROM app_file_events ORDER BY id DESC LIMIT 80'),
            'planets': sorted({r['path'].split('/')[1] for r in store.list_rows("SELECT path FROM app_file_snapshot WHERE path LIKE 'planets/%'") if len(r['path'].split('/'))>2})}
