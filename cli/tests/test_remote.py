import time
import pytest
from talo.remote import endpoint, merge_notes, public_snapshot, execute
from talo.application.service import create_app_context
from talo.application.web import snapshot
from talo.changes.manager import for_context

@pytest.fixture
def project(tmp_path,monkeypatch):
 monkeypatch.setenv('TALO_HOME',str(tmp_path/'home'))
 root=tmp_path/'repo';root.mkdir();(root/'file.txt').write_text('before\n')
 ctx=create_app_context(root);pid=ctx.project_id;ctx.close()
 return root,pid

def test_remote_url_rejects_credentials_and_non_tls():
 assert endpoint('https://think-along.ai.kr')=='https://think-along.ai.kr/api/remote'
 for url in ('http://example.com','https://u:p@example.com','https://example.com/path','https://example.com?token=x'):
  with pytest.raises(ValueError):endpoint(url)

def test_cloud_decision_import_preserves_prior_and_fails_on_local_edit(project):
 root,pid=project
 first={'id':'first','content':'A','status':'confirmed','createdAt':1000}
 merge_notes(root,[first]);merge_notes(root,[first])
 second={'id':'second','content':'B','status':'confirmed','previousId':'first','createdAt':2000}
 merge_notes(root,[{**first,'status':'superseded'},second])
 ctx=create_app_context(root)
 try:
  rows=ctx.repository.conn.execute('SELECT * FROM memories WHERE project_id=?',(pid,)).fetchall()
  assert len(rows)==2;assert next(r for r in rows if r['id']=='cloud_first')['status']=='superseded'
  ctx.repository.conn.execute("UPDATE memories SET content='Local modification' WHERE id='cloud_second'");ctx.repository.conn.commit()
 finally:ctx.close()
 with pytest.raises(ValueError,match='충돌'):merge_notes(root,[{**first,'status':'superseded'},second])

def test_remote_execute_checks_project_expiry_optin_and_real_undo(project):
 root,pid=project;ctx=create_app_context(root)
 try:change=for_context(ctx).propose([{'path':'file.txt','content':'after\n'}])
 finally:ctx.close()
 cmd={'id':'remote-apply','projectId':pid,'method':'apply','params':{'change_id':change['id'],'patch_hash':change['patch_hash']},'expires':time.time()*1000+10000}
 config={'allowRun':True,'allowCode':True}
 with pytest.raises(ValueError):execute(root,pid,{**cmd,'projectId':'other'},config)
 with pytest.raises(ValueError):execute(root,pid,{**cmd,'expires':0},config)
 with pytest.raises(ValueError):execute(root,pid,cmd,{**config,'allowRun':False})
 execute(root,pid,cmd,config);execute(root,pid,cmd,config)
 assert (root/'file.txt').read_text()=='after\n'
 execute(root,pid,{**cmd,'id':'remote-undo','method':'undo'},config)
 assert (root/'file.txt').read_text()=='before\n'

def test_sync_snapshot_excludes_file_bodies_and_credentials(project):
 root,_=project;ctx=create_app_context(root)
 try:
  for_context(ctx).propose([{'path':'file.txt','content':'private code'}])
  raw=snapshot(ctx);raw['secret']='do not upload';raw['runs']=[{'id':'run','credential_ref':'bad','state':'completed'}]
  result=public_snapshot(raw)
  assert 'secret' not in result
  assert 'credential_ref' not in result['runs'][0]
  assert result['changes'][0]['manifest']['files']==[{'path':'file.txt'}]
 finally:ctx.close()

def test_explicit_conflict_resolution_preserves_local_version(project):
 root,pid=project
 first={'id':'first','content':'Cloud version','status':'confirmed','createdAt':1000}
 merge_notes(root,[first])
 ctx=create_app_context(root)
 try:
  ctx.repository.conn.execute("UPDATE memories SET content='Local version',version=2 WHERE id='cloud_first'");ctx.repository.conn.commit()
 finally:ctx.close()
 resolution={'id':'resolved','content':'Local version','status':'confirmed','previousId':'first','localContent':'Local version','localVersion':2,'createdAt':2000}
 notes=[{**first,'status':'superseded'},resolution]
 merge_notes(root,notes);merge_notes(root,notes)
 ctx=create_app_context(root)
 try:
  old=ctx.repository.conn.execute("SELECT * FROM memories WHERE id='cloud_first'").fetchone()
  new=ctx.repository.conn.execute("SELECT * FROM memories WHERE id='cloud_resolved'").fetchone()
  assert old['content']=='Local version' and old['status']=='superseded'
  assert new['content']=='Local version' and new['status']=='confirmed'
 finally:ctx.close()

def test_snapshot_keeps_text_content_blocks(project):
 import json
 from talo.application.service import start_session
 root,_=project;ctx=create_app_context(root)
 try:
  sid=start_session(ctx,'Content block test')
  rid=ctx.repository.create_run(sid,'request','plan','completed')
  ctx.repository.append_message(rid,'assistant',json.dumps([{'type':'text','text':'First'},{'type':'text','text':'Second'}]))
  snap=snapshot(ctx)
  assert snap['messages'][0]['text']=='First\nSecond'
 finally:ctx.close()

def test_macos_service_registration_uses_no_token_in_arguments(project,tmp_path,monkeypatch):
 from argparse import Namespace
 import plistlib
 import subprocess
 from pathlib import Path
 from talo.remote import command,private_write,state_path
 root,pid=project;monkeypatch.chdir(root)
 home=tmp_path/'user';home.mkdir()
 monkeypatch.setattr(Path,'home',classmethod(lambda cls:home))
 monkeypatch.setattr('sys.platform','darwin')
 calls=[];original_run=subprocess.run
 def run(args,**kw):
  if args[0]=='launchctl':calls.append(args);return subprocess.CompletedProcess(args,0)
  return original_run(args,**kw)
 monkeypatch.setattr(subprocess,'run',run)
 private_write(state_path(pid),{'token':'private-token','server':'https://example.test','allowRun':True,'allowCode':False})
 assert command(Namespace(remote_action='install'))==0
 plist=next((home/'Library'/'LaunchAgents').glob('*.plist'))
 data=plistlib.loads(plist.read_bytes())
 assert data['WorkingDirectory']==str(root)
 assert data['ProgramArguments'][-3:]==['talo','remote','start']
 assert 'private-token' not in str(data)
 assert calls[0][1]=='bootstrap'
 assert command(Namespace(remote_action='uninstall'))==0
 assert not plist.exists()

def test_full_sync_includes_history_outside_ui_window(project):
 import json
 from talo.application.service import start_session
 root,_=project;ctx=create_app_context(root)
 try:
  sid=start_session(ctx,'History');rid=ctx.repository.create_run(sid,'history-request','plan','completed')
  for i in range(510):ctx.repository.append_message(rid,'user',json.dumps({'text':str(i)}))
  assert len(snapshot(ctx)['messages'])==500
  assert len(snapshot(ctx,full=True)['messages'])==510
 finally:ctx.close()

def test_snapshot_batches_preserve_every_record_and_fail_explicitly_if_too_large():
 from talo.remote import snapshot_batches
 snap={'project':{'id':'p'},'revision':'r','connections':[],**{k:[] for k in ('sessions','runs','messages','tasks','memories','verifications','changes')}}
 snap['messages']=[{'id':str(i),'text':'x'*50} for i in range(100)]
 batches=list(snapshot_batches(snap,limit=1000))
 assert len(batches)>1
 assert [r for b in batches for r in b['messages']]==snap['messages']
 snap['messages']=[{'id':'large','text':'x'*1000}]
 with pytest.raises(ValueError,match='상한'):list(snapshot_batches(snap,limit=1000))
