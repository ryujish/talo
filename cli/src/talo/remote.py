"""Optional cloud record sync and outbound remote execution. No inbound port."""
from __future__ import annotations
import argparse
import concurrent.futures
import json
import os
import socket
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from talo import paths
from talo.application.service import create_app_context
from talo.application.web import handle, snapshot
from talo.sanitize import redact_text


class DeviceRevoked(ValueError):
    pass


def endpoint(url):
    p = urlsplit(url)
    if p.username or p.password or p.query or p.fragment or p.path not in ('', '/'):
        raise ValueError('서버 기본 주소만 입력하세요.')
    if p.scheme != 'https' and not (p.scheme == 'http' and p.hostname in ('127.0.0.1', 'localhost')):
        raise ValueError('HTTPS가 필요합니다. HTTP는 로컬 테스트만 허용합니다.')
    return url.rstrip('/') + '/api/remote'


def call(url, action, token=None, **body):
    headers = {'x-talo-device': '1'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
        r = client.post(endpoint(url), json={'action': action, **body}, headers=headers)
        data = r.json()
        if r.status_code == 401 and token:
            raise DeviceRevoked('서버에서 기기 연결이 해제됐습니다. 동기화를 종료합니다.')
        if r.status_code != 200:
            raise ValueError(data.get('error', '서버 연결 실패'))
        return data['result']


def private_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix('.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, ensure_ascii=False); f.flush(); os.fsync(f.fileno())
        os.replace(temp, path); os.chmod(path, 0o600)
    finally:
        temp.unlink(missing_ok=True)


def state_path(pid):
    return paths.artifacts_dir(pid) / 'remote-connection.json'


def public_snapshot(raw):
    """Whitelist metadata; never upload raw Run rows, credentials or file bodies."""
    def rows(key, fields):
        return [{k: row.get(k) for k in fields if k in row} for row in raw.get(key, [])]
    result = {
        'project': {k: raw['project'][k] for k in ('id', 'name', 'branch')},
        'revision': raw['revision'], 'updated_at': raw['updated_at'],
        'sessions': rows('sessions', ('id', 'title', 'updated_at')),
        'runs': rows('runs', ('id', 'session_id', 'state', 'mode', 'created_at', 'updated_at')),
        'messages': rows('messages', ('id', 'session_id', 'run_id', 'role', 'text', 'created_at')),
        'tasks': rows('tasks', ('id', 'title', 'status', 'evidence')),
        'memories': rows('memories', ('id', 'content', 'status', 'version', 'source_refs', 'created_at', 'updated_at')),
        'verifications': rows('verifications', ('id', 'result', 'evidence_ref', 'created_at')),
        'connections': rows('connections', ('id', 'model', 'provider', 'status')),
        'changes': [{**{k: c.get(k) for k in ('id','state','patch_hash','created_at','updated_at','session_id','run_id')},
                     'manifest': {'match_method': c['manifest']['match_method'], 'files': [{'path': f['path']} for f in c['manifest']['files']]}} for c in raw['changes']],
    }
    def scrub(value):
        if isinstance(value, str): return redact_text(value, max_len=len(value))
        if isinstance(value, list): return [scrub(v) for v in value]
        if isinstance(value, dict): return {k:scrub(v) for k,v in value.items()}
        return value
    return scrub(result)


def merge_notes(root, notes):
    ctx = create_app_context(root)
    db = ctx.repository.conn
    try:
        db.execute('BEGIN IMMEDIATE')
        for note in notes:
            mid = 'cloud_' + note['id']
            old = db.execute('SELECT * FROM memories WHERE id=? AND project_id=?', (mid, ctx.project_id)).fetchone()
            if old:
                if old['content'] != note['content'] or (old['status'] != note['status'] and note['status'] == 'confirmed'):
                    resolution = next((n for n in notes if n.get('previousId') == note['id'] and 'localVersion' in n), None)
                    resolved = resolution and db.execute('SELECT id FROM memories WHERE id=?', ('cloud_'+resolution['id'],)).fetchone()
                    reviewed = resolution and resolution['localVersion'] == old['version'] and resolution.get('localContent') == old['content']
                    if not (note['status'] == 'superseded' and (reviewed or resolved)):
                        raise ValueError('동기화 충돌: 로컬에서 변경한 결정이 있습니다. 웹과 로컬 기록을 비교하세요.')
                if old['status'] != note['status']:
                    db.execute("UPDATE memories SET status=?,version=version+1,updated_at=? WHERE id=?", (note['status'], time.time(),mid))
                continue
            target = note.get('memoryId')
            resolution = next((n for n in notes if n.get('previousId') == note['id'] and 'localVersion' in n), None)
            if target and not (note['status'] == 'superseded' and resolution):
                base = db.execute('SELECT * FROM memories WHERE id=? AND project_id=?', (target,ctx.project_id)).fetchone()
                if not base or base['version'] != note.get('memoryVersion') or base['status'] != 'confirmed':
                    raise ValueError('동기화 충돌: 수정 대상 결정의 로컬 버전이 달라졌습니다.')
                db.execute("UPDATE memories SET status='superseded',version=version+1,updated_at=? WHERE id=?", (time.time(),target))
            refs = ['cloud:user-confirmed']
            if target: refs.append(target)
            if note.get('previousId'): refs.append('cloud_'+note['previousId'])
            db.execute('INSERT INTO memories(id,project_id,kind,status,content,version,source_refs,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                       (mid,ctx.project_id,'decision',note['status'],note['content'],1,json.dumps(refs),note['createdAt']/1000,time.time()))
        db.commit()
    except Exception:
        db.rollback(); raise
    finally: ctx.close()


def execute(root, pid, command, config):
    if command['projectId'] != pid or command['expires'] < time.time()*1000:
        raise ValueError('만료됐거나 다른 프로젝트의 요청입니다.')
    if not config['allowRun']: raise ValueError('원격 실행이 허용되지 않았습니다.')
    if command['method'] not in ('run','diff','apply','undo','cancel','recover'): raise ValueError('지원하지 않는 요청')
    if command['method'] != 'run' and not config['allowCode']: raise ValueError('diff 공유가 꺼져 있습니다.')
    params = command.get('params') or {}
    if command['method'] == 'run' and params.get('mode') not in ('plan', 'dev'): raise ValueError('작업 모드 오류')
    result = handle({'id': command['id'], 'project_id': pid, 'method': command['method'], 'params': params})
    if command['method'] == 'diff':
        result['change']['manifest']['files'] = [{'path': f['path']} for f in result['change']['manifest']['files']]
    # No automatic replay after timeout/crash. Local core request ledger remains authoritative.
    def safe(value):
        if isinstance(value, dict): return {k:safe(v) for k,v in value.items() if k not in ('before','after','credential_ref')}
        if isinstance(value, list): return [safe(v) for v in value]
        if isinstance(value, str): return redact_text(value,max_len=len(value))
        return value
    return safe(result)


def snapshot_batches(snap, limit=1000000):
    keys=('sessions','runs','messages','tasks','memories','verifications','changes')
    base={k:v for k,v in snap.items() if k not in keys}
    batch={**base,**{k:[] for k in keys}}; size=len(json.dumps(base).encode())
    for key in keys:
        for row in snap[key]:
            length=len(json.dumps(row,ensure_ascii=False).encode())
            if length>limit//2: raise ValueError('하나의 기록이 동기화 크기 상한을 초과했습니다. 기록을 보존한 채 동기화를 중단합니다.')
            if size+length>limit:
                yield batch;batch={**base,**{k:[] for k in keys}};size=len(json.dumps(base).encode())
            batch[key].append(row);size+=length
    yield batch


def worker(root, pid, config):
    token, url = config['token'], config['server']
    ledger = state_path(pid).with_name('remote-results.sqlite')
    db = sqlite3.connect(ledger)
    os.chmod(ledger, 0o600)
    db.execute('CREATE TABLE IF NOT EXISTS results(id TEXT PRIMARY KEY, state TEXT, body TEXT)'); db.commit()
    def upload_results():
        for rid, body in db.execute("SELECT id,body FROM results WHERE state='ready'").fetchall():
            result = json.loads(body)
            call(url,'device.result',token,id=rid,**result)
            db.execute("UPDATE results SET state='sent' WHERE id=?",(rid,));db.commit()
    # Interrupted work is reported as uncertain, never repeated.
    db.execute("UPDATE results SET state='ready',body=? WHERE state='started'", (json.dumps({'error':'기기가 중단되어 결과가 미확정입니다. 로컬 작업 기록을 확인하세요.'}),));db.commit()
    future = None; command = None; revision = 0; sync_error = ""; sent_revision = None
    def sync(snap):
        nonlocal sent_revision
        common=dict(projectId=pid,allowRun=config['allowRun'],allowCode=config['allowCode'],notesRevision=revision,syncError=sync_error)
        if sent_revision==snap['revision']:
            return call(url,'device.heartbeat',token,**common)
        result=None
        for batch in snapshot_batches(snap):result=call(url,'device.sync',token,snapshot=batch,**common)
        sent_revision=snap['revision']
        return result
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        while True:
            try:
                current = json.loads(state_path(pid).read_text())
                if current['token'] != token: break
                config = current
                upload_results()
                if future is None:
                    for delivered in call(url,'device.pending',token):
                        if not db.execute('SELECT id FROM results WHERE id=?',(delivered['id'],)).fetchone():
                            db.execute('INSERT INTO results VALUES(?,?,?)',(delivered['id'],'ready',json.dumps({'error':'요청 전달 응답이 유실되어 로컬 실행을 시작하지 않았습니다. 새 요청 전에 기록을 확인하세요.'})));db.commit()
                    upload_results()
                if future and future.done():
                    try: result = {'result': future.result()}
                    except Exception as exc: result = {'error': redact_text(str(exc),2000)}
                    db.execute("UPDATE results SET state='ready',body=? WHERE id=?", (json.dumps(result,default=str),command['id']));db.commit()
                    future = None
                    upload_results()
                ctx = create_app_context(root)
                try: snap = public_snapshot(snapshot(ctx, full=True))
                finally: ctx.close()
                synced = sync(snap)
                if config.get('cloudProjectId') != synced['projectId']:
                    config['cloudProjectId'] = synced['projectId']; private_write(state_path(pid), config)
                if not future:
                    try:
                        merge_notes(root,synced['notes']); revision = synced['revision']; sync_error = ''
                    except ValueError as exc:
                        sync_error = str(exc)
                        sync(snap)
                        raise
                    # Acknowledge applied notes before accepting an execution that depends on them.
                    ctx=create_app_context(root)
                    try:snap=public_snapshot(snapshot(ctx, full=True))
                    finally:ctx.close()
                    sync(snap)
                    got=call(url,'device.poll',token)
                    command=got.get('command')
                    if command:
                        prior=db.execute('SELECT state FROM results WHERE id=?',(command['id'],)).fetchone()
                        if prior: raise ValueError('이미 전달된 실행 요청입니다. 자동 재실행하지 않습니다.')
                        db.execute('INSERT INTO results VALUES(?,?,NULL)',(command['id'],'started'));db.commit()
                        future=pool.submit(execute,root,pid,command,dict(config))
            except DeviceRevoked as exc:
                state_path(pid).unlink(missing_ok=True)
                print(str(exc), file=sys.stderr, flush=True)
                break
            except (ValueError,httpx.HTTPError,OSError) as exc:
                print(redact_text(str(exc),300), file=sys.stderr, flush=True)
                if not state_path(pid).exists(): break
            time.sleep(3)
    db.close()


def command(args):
    root = Path.cwd().resolve(); ctx=create_app_context(root)
    try: pid=ctx.project_id
    finally: ctx.close()
    dest=state_path(pid)
    if args.remote_action == 'pair':
        if not args.sync_records: raise ValueError('대화·결정·작업 기록의 서버 저장에 동의하려면 --sync-records를 지정하세요.')
        endpoint(args.server)
        if dest.exists(): raise ValueError('이미 연결된 프로젝트입니다. disconnect 후 다시 연결하세요.')
        data=call(args.server,'pair.start',name=args.name or socket.gethostname())
        print(f"웹 {args.server}/projects?source=cloud 에서 연결 코드 {data['code']}를 승인하세요.", flush=True)
        end=time.time()+300
        while time.time()<end:
            result=call(args.server,'pair.claim',claim=data['claim'])
            if not result.get('pending'):
                private_write(dest,{'server':args.server,'token':result['token'],'deviceId':result['device']['id'],'allowRun':args.allow_run,'allowCode':args.share_diff,'projectId':pid})
                print('연결 완료. talo remote start로 동기화를 시작하세요.');return 0
            time.sleep(3)
        raise ValueError('연결 코드가 만료됐습니다.')
    if not dest.exists(): raise ValueError('먼저 talo remote pair로 연결하세요.')
    config=json.loads(dest.read_text())
    if args.remote_action == 'status':
        print(json.dumps({k:v for k,v in config.items() if k!='token'},ensure_ascii=False));return 0
    if args.remote_action == 'disconnect':
        try: call(config['server'],'device.disconnect',config['token'])
        finally: dest.unlink(missing_ok=True)
        print('로컬 연결을 해제했습니다. 서버 사본 삭제는 웹 설정에서 별도로 수행하세요.');return 0
    if args.remote_action in ('install','uninstall'):
        if sys.platform != 'darwin': raise ValueError('자동 시작 등록은 현재 macOS에서 지원합니다. 다른 OS는 remote start를 서비스로 등록하세요.')
        import plistlib, subprocess
        label='kr.ai.think-along.talo.'+pid
        plist=Path.home()/'Library'/'LaunchAgents'/(label+'.plist')
        domain='gui/'+str(os.getuid())
        if args.remote_action=='uninstall':
            subprocess.run(['launchctl','bootout',domain,str(plist)],check=False,capture_output=True)
            plist.unlink(missing_ok=True);print('자동 시작을 해제했습니다.');return 0
        plist.parent.mkdir(parents=True,exist_ok=True)
        if plist.exists(): raise ValueError('이미 등록된 서비스입니다. uninstall 후 다시 등록하세요.')
        with plist.open('wb') as f:
            plistlib.dump({'Label':label,'ProgramArguments':[sys.executable,'-m','talo','remote','start'],'WorkingDirectory':str(root),'RunAtLoad':True,'KeepAlive':{'SuccessfulExit':False},'ThrottleInterval':10,'StandardOutPath':str(dest.with_suffix('.log')),'StandardErrorPath':str(dest.with_suffix('.log')),'EnvironmentVariables':{'TALO_HOME':str(paths.registry_db_path().parent)}},f)
        os.chmod(plist,0o600)
        subprocess.run(['launchctl','bootstrap',domain,str(plist)],check=True)
        print('로그인 시 자동 시작과 백그라운드 동기화를 등록했습니다.');return 0
    if args.remote_action == 'start':
        import fcntl
        with dest.with_suffix('.lock').open('a') as lock:
            try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: raise ValueError('이 프로젝트의 동기화가 이미 실행 중입니다.')
            worker(root,pid,config)
        return 0
    raise ValueError('지원하지 않는 remote 명령')
