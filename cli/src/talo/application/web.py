"""Local web adapter. Project state is owned by Talo SQLite, never a JSON mirror."""
import asyncio
import hashlib
import json
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from talo import paths
from talo.application.service import create_app_context, run_request, start_session
from talo.changes.manager import for_context
from talo.continuity import tasks


def projects():
    if not paths.registry_db_path().exists():
        return []
    with sqlite3.connect(f"file:{paths.registry_db_path()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute('SELECT * FROM projects ORDER BY created_at DESC')]


def snapshot(ctx, full=False):
    repo = ctx.repository
    sessions = [dict(x) for x in (repo.conn.execute('SELECT * FROM sessions WHERE workspace_id=? ORDER BY updated_at DESC', (ctx.workspace_id,)).fetchall() if full else repo.list_sessions(ctx.workspace_id, 100))]
    runs, messages, verifications = [], [], []
    for session in sessions:
        for row in repo.list_runs(session['id']):
            run = dict(row)
            runs.append(run)
            for m in repo.list_messages(run['id']):
                if m['role'] not in ('user', 'assistant'):
                    continue
                data = json.loads(m['content_json'])
                text = (data.get('text') or data.get('content') or '') if isinstance(data, dict) else data
                if isinstance(data, list):
                    text = '\n'.join(b.get('text','') for b in data if isinstance(b,dict) and isinstance(b.get('text'),str))
                if isinstance(text, str):
                    messages.append({'id': m['id'], 'session_id': session['id'], 'run_id': run['id'],
                                     'role': m['role'], 'text': text, 'created_at': m['created_at']})
            verifications.extend(dict(v) for v in repo.conn.execute('SELECT * FROM verifications WHERE run_id=?', (run['id'],)))
    memories = [dict(m) for m in repo.list_memories(ctx.project_id)]
    for m in memories:
        m['source_refs'] = json.loads(m.get('source_refs') or '[]')
    result = {'project': {'id': ctx.project_id, 'name': ctx.repo_info.root.name, 'path': str(ctx.repo_info.root), 'branch': ctx.repo_info.branch or '브랜치 없음'},
              'sessions': sessions, 'runs': sorted(runs, key=lambda r: r['created_at']) if full else sorted(runs, key=lambda r: r['created_at'])[-200:],
              'messages': messages if full else messages[-500:], 'tasks': tasks(repo, ctx.workspace_id),
              'changes': for_context(ctx).list(), 'memories': memories, 'verifications': verifications if full else verifications[-100:],
              'connections': [{'id': c.connection_id, 'model': ctx.config.selected_model_id(c) or c.model_id,
                               'provider': c.provider_id, 'status': 'unverified'} for c in ctx.config.connections.values()]}
    connection_file = paths.artifacts_dir(ctx.project_id) / 'remote-connection.json'
    if connection_file.exists():
        try:
            connection = json.loads(connection_file.read_text())
            if connection.get('cloudProjectId'):
                result['remote'] = {'server': connection['server'], 'projectId': connection['cloudProjectId']}
        except (OSError, ValueError, KeyError):
            pass
    result['revision'] = hashlib.sha256(json.dumps(result, sort_keys=True, default=str).encode()).hexdigest()
    result['updated_at'] = time.time()
    return result


def handle(req):
    method = req.get('method')
    known = projects()
    if method == 'projects':
        return known
    project = next((p for p in known if p['id'] == req.get('project_id')), None)
    if not project or not Path(project['canonical_path']).is_dir():
        raise ValueError('등록된 프로젝트를 찾을 수 없습니다. 해당 폴더에서 Talo를 먼저 실행하세요.')
    ctx = create_app_context(Path(project['canonical_path']))
    try:
        if ctx.project_id != project['id']:
            raise ValueError('프로젝트 경로가 바뀌었습니다. CLI에서 다시 확인하세요.')
        params = req.get('params') or {}
        manager = for_context(ctx)
        if method == 'snapshot':
            return snapshot(ctx)
        if method == 'diff':
            return {'change': manager.get(params['change_id']), 'diff': manager.diff(params['change_id'])}
        if method not in ('apply', 'undo', 'cancel', 'recover', 'run', 'decision'):
            raise ValueError('지원하지 않는 요청')
        request_id = req.get('id')
        if not isinstance(request_id, str) or not 8 <= len(request_id) <= 128:
            raise ValueError('유효한 요청 ID가 필요합니다')
        key = 'web:' + request_id
        body_hash = hashlib.sha256(json.dumps(req, sort_keys=True).encode()).hexdigest()
        db = ctx.repository.conn
        db.execute('BEGIN IMMEDIATE')
        prior = db.execute('SELECT * FROM core_requests WHERE workspace_id=? AND request_id=?', (ctx.workspace_id, key)).fetchone()
        if prior:
            db.rollback()
            if prior['body_hash'] != body_hash:
                raise ValueError('같은 요청 ID의 내용이 다릅니다')
            if prior['state'] != 'complete':
                raise ValueError('이전 요청 결과가 미확정입니다. 기록을 먼저 확인하세요.')
            return json.loads(prior['result_json'])
        db.execute('INSERT INTO core_requests VALUES(?,?,?,?,?,?)', (ctx.workspace_id, key, body_hash, 'started', None, time.time()))
        db.commit()
        if method == 'apply':
            result = manager.apply(params['change_id'], params['patch_hash'])
        elif method == 'undo':
            result = manager.undo(params['change_id'])
        elif method == 'cancel':
            result = manager.cancel(params['change_id'])
        elif method == 'recover':
            result = manager.recover(params['change_id'])
        elif method == 'decision':
            content = str(params.get('content', '')).strip()
            if not content or len(content) > 10000:
                raise ValueError('결정문은 1~10000자여야 합니다')
            db.execute('BEGIN IMMEDIATE')
            old = None
            if params.get('memory_id'):
                old = db.execute('SELECT * FROM memories WHERE id=? AND project_id=?', (params['memory_id'], ctx.project_id)).fetchone()
                if not old or old['version'] != params.get('version') or old['status'] != 'confirmed':
                    db.rollback()
                    raise ValueError('결정이 변경됐습니다. 새로고침 후 다시 검토하세요.')
                db.execute("UPDATE memories SET status='superseded',version=version+1,updated_at=? WHERE id=?", (time.time(), old['id']))
            mid = 'mem_' + uuid.uuid4().hex[:12]
            refs = (json.loads(old['source_refs'] or '[]') + [old['id']]) if old else ['web:user-confirmed']
            db.execute('INSERT INTO memories(id,project_id,kind,status,content,version,source_refs,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                       (mid, ctx.project_id, 'decision', 'confirmed', content, 1, json.dumps(refs), time.time(), time.time()))
            result = {'memory_id': mid}
        else:
            prompt = str(params.get('request', '')).strip()
            if not prompt or len(prompt) > 20000:
                raise ValueError('요청은 1~20000자여야 합니다')
            mode = params.get('mode', 'plan')
            if mode not in ('plan', 'dev'):
                raise ValueError('지원하지 않는 작업 방식')
            sid = params.get('session_id')
            if sid:
                session = ctx.repository.get_session(sid)
                if not session or session['workspace_id'] != ctx.workspace_id:
                    raise ValueError('다른 프로젝트의 세션입니다')
            else:
                sid = start_session(ctx, prompt[:70])
            connection = params.get('connection_id')
            if connection and connection not in ctx.config.connections:
                raise ValueError('등록되지 않은 AI 연결입니다')
            outcome = asyncio.run(run_request(ctx, prompt, session_id=sid, mode=mode,
                    permission='read_only' if mode == 'plan' else 'project_edit', connection_id=connection))
            result = {'session_id': sid, 'run_id': outcome.run_id, 'state': outcome.state.value,
                      'exit_code': int(outcome.exit_code), 'summary': outcome.summary}
        db.execute("UPDATE core_requests SET state='complete',result_json=? WHERE workspace_id=? AND request_id=?",
                   (json.dumps(result, ensure_ascii=False), ctx.workspace_id, key))
        db.commit()
        return result
    finally:
        ctx.close()


if __name__ == '__main__':
    try:
        result = handle(json.loads(sys.stdin.readline(1024 * 1024)))
        print(json.dumps({'ok': True, 'result': result}, ensure_ascii=False, default=str))
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': str(exc), 'code': getattr(exc, 'code', 'REQUEST_ERROR')}, ensure_ascii=False))
        sys.exit(1)
