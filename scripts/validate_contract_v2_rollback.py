"""Restore the real pre-v2 backup in isolated ports/volumes; never touch live mounts."""
import argparse,hashlib,json,os,shutil,signal,sqlite3,subprocess,sys,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'openharvey_contract_memory_pack/07_tools'))
from suite_common import atomic_json,require_review
from run_suite import Api,StopRun
PORTS={'app':18081,'core':18430,'proxy':18106}
NAMES={'core':'tdai-rollback-core','proxy':'tdai-rollback-proxy'}

def run(args,**kw):return subprocess.run(args,check=True,**kw)
def sql_inventory(app,core):
    result={}
    for label,path in [('app',app/'app.sqlite'),('contract',next(core.rglob('contract.sqlite')))]:
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
            tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            result[label]={}
            for table in (['users','workspaces','threads','tdai_workspaces','teams','memory_identities','artifacts'] if label=='app' else ['raw','atoms','candidates','entries','revisions','audit','tombstones']):
                if table not in tables:continue
                db.row_factory=sqlite3.Row;rows=[dict(r) for r in db.execute('SELECT * FROM '+table)]
                # Identity/config relocation is expected; business records and version data are not.
                if label=='app':rows=[{k:v for k,v in r.items() if k in {'id','username','workspace_id','document_id','session_id','task_id','version','status','content_hash','source_hash','team_id','agent_id'}} for r in rows]
                canonical=json.dumps(sorted(rows,key=lambda r:json.dumps(r,sort_keys=True)),sort_keys=True,ensure_ascii=False)
                result[label][table]={'count':len(rows),'sha256':hashlib.sha256(canonical.encode()).hexdigest()}
    return result

def health(port):
    for _ in range(80):
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/health',timeout=2) as r:
                if r.status==200:return
        except Exception:pass
        time.sleep(.5)
    raise RuntimeError('Isolated health failed on '+str(port))

def main():
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['restore','boot-old','upgrade','cleanup']);p.add_argument('--execute',action='store_true');p.add_argument('--reviewed-pack-sha');p.add_argument('--backup',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();require_review(a.execute,a.reviewed_pack_sha)
    os.umask(0o077);a.out.mkdir(parents=True,exist_ok=True);source=a.out/'app-source';app=a.out/'app-data';state=a.out/'state';core=a.out/'core-data';proxy=a.out/'proxy-data';manifest=json.loads((a.backup/'manifest.json').read_text())
    if a.phase=='restore':
        if app.exists():raise RuntimeError('Restore destination already exists; inspect before retrying')
        for src,dst in [('app-data',app),('component-state',state),('tdai-contract-core-data',core),('tdai-contract-proxy-data',proxy)]:shutil.copytree(a.backup/src,dst,symlinks=True)
        source.mkdir();archive=a.out/'app-source.tar'
        with archive.open('wb') as f:run(['git','archive',manifest['app_commit']],cwd=ROOT,stdout=f)
        run(['tar','-xf',str(archive),'-C',str(source)])
        atomic_json(a.out/'backup-inventory.json',sql_inventory(a.backup/'app-data',a.backup/'tdai-contract-core-data'))
        # Repoint copied application mappings, never modify production DB.
        with sqlite3.connect(app/'app.sqlite') as db:
            db.execute("UPDATE tdai_users SET core_url=?,proxy_url=?",('http://127.0.0.1:18430','http://127.0.0.1:18106/opencode/default/v1'))
            for uid,binding in db.execute('SELECT user_id,binding FROM memory_identities').fetchall():
                b=json.loads(binding);b.update(core_url='http://127.0.0.1:18430',proxy_url='http://127.0.0.1:18106/opencode/default/v1');db.execute('UPDATE memory_identities SET binding=? WHERE user_id=?',(json.dumps(b),uid))
            db.execute("UPDATE providers SET base_url='http://127.0.0.1:18106/opencode/default/v1' WHERE id='tencentdb-memory'")
        rt=json.loads((app/'runtimes.json').read_text())
        for n,(user,cfg) in enumerate(rt.items()):
            for k in ['source_root','work_root']:cfg[k]=str(app/Path(cfg[k]).relative_to(Path(manifest['app_data'])))
            cfg.update(url='http://127.0.0.1:'+str(18090+n),save_url='http://127.0.0.1:18081/internal/artifacts',skill_root=str(source/'runtime'))
        atomic_json(app/'runtimes.json',rt)
        import yaml
        cfg=yaml.safe_load((state/'proxy.yaml').read_text());cfg['tdai']['endpoint']='http://tdai-rollback-core:8420'
        for key in ['coreSkill','coreMemory','sessionInit']:
            if isinstance(cfg.get(key),dict) and 'endpoint'in cfg[key]:cfg[key]['endpoint']='http://tdai-rollback-core:8420'
        (state/'proxy.yaml').write_text(yaml.safe_dump(cfg,allow_unicode=True,sort_keys=False))
    if a.phase in {'restore','boot-old'}:
        import yaml
        # Docker Desktop internal networks do not expose published ports to the host.
        # Keep a normal dedicated bridge but explicitly blackhole model transports.
        def isolate(v):
            if isinstance(v,dict):return {k:isolate(x) for k,x in v.items()}
            if isinstance(v,list):return [isolate(x) for x in v]
            if isinstance(v,str) and 'http://tdai-contract-core:8420' in v:return v.replace('tdai-contract-core','tdai-rollback-core')
            if isinstance(v,str) and v.startswith(('http://','https://')) and 'tdai-rollback-core' not in v:return 'http://127.0.0.1:1'
            return v
        for name in ['core.yaml','proxy.yaml']:
            path=state/name;path.write_text(yaml.safe_dump(isolate(yaml.safe_load(path.read_text())),allow_unicode=True,sort_keys=False))
        run(['docker','network','create','tdai-rollback-stack'],stdout=subprocess.DEVNULL)
    if a.phase in {'restore','boot-old','upgrade'}:
        if a.phase=='upgrade':
            for name in NAMES.values():run(['docker','rm','-f',name],stdout=subprocess.DEVNULL)
            pid=int((a.out/'app.pid').read_text());os.kill(pid,signal.SIGTERM);time.sleep(1)
            source=a.out/'app-source-v2';source.mkdir()
            archive=a.out/'app-source-v2.tar'
            with archive.open('wb') as f:run(['git','archive','HEAD'],cwd=ROOT,stdout=f)
            run(['tar','-xf',str(archive),'-C',str(source)])
            rt=json.loads((app/'runtimes.json').read_text())
            for config in rt.values():config['skill_root']=str(source/'runtime')
            atomic_json(app/'runtimes.json',rt)
            # Same deployed v2 model config, separate copied credential file.
            component=Path('/Users/dicam/CodeDir/TencentDB-Agent-Memory-contract/deploy/contract-memory/state')
            for name in ['core.env','contract-model.json']:shutil.copy2(component/name,state/name)
        images={}
        for kind in ['core','proxy']:
            image=manifest['old_images']['/tdai-contract-'+kind] if a.phase!='upgrade' else json.loads(subprocess.check_output(['docker','inspect','tdai-contract-'+kind]))[0]['Image']
            images[kind]=image
            configdest='/data/config/tdai-gateway.yaml' if kind=='core' else '/data/config.yaml';datadest='/data/tdai-memory' if kind=='core' else '/data/tdai-memory-proxy';data=core if kind=='core' else proxy
            extra=['--env-file',str(state/'core.env'),'-e','STORE_MODE=sqlite','-e','TDAI_METADATA_BACKEND=sqlite','-e','TDAI_METADATA_SQLITE_PATH=/data/tdai-memory/metadata.sqlite'] if kind=='core' else []
            if kind=='core' and a.phase=='upgrade':extra+=['-v',str(state/'contract-model.json')+':/data/config/contract-model.json:ro']
            run(['docker','run','-d','--name',NAMES[kind],'--network','tdai-rollback-stack','-p',f'127.0.0.1:{PORTS[kind]}:{8420 if kind=="core" else 8096}','-v',str(state/(kind+'.yaml'))+':'+configdest+':ro','-v',str(data)+':'+datadest,*extra,image],stdout=subprocess.DEVNULL)
            health(PORTS[kind])
        # Boot the restored source, without sending an Agent message.
        isolated_binary=Path.home()/'CodeDir/TencentDB-Agent-Memory/deploy/local-deployment/state/opencode/node_modules/.bin'
        env={**os.environ,'PATH':str(isolated_binary)+os.pathsep+os.environ.get('PATH',''),'CW_DATA_DIR':str(app),'CW_SANDBOX_BACKEND':'local','CW_LOCAL_DEV_USER':'','CW_SECURE_COOKIE':'0','CW_PUBLIC_ORIGIN':'http://127.0.0.1:18081','CW_TDAI_ADMIN_KEY_FILE':str(state/'admin.key'),'CW_TDAI_CONTROL_KEY_FILE':str(state/'control.key'),'PYTHONPATH':str(source)}
        log=(a.out/(a.phase+'-app.log')).open('ab');proc=subprocess.Popen([str(ROOT/'.venv/bin/python'),'-m','uvicorn','contract_web.app:create_app','--factory','--host','127.0.0.1','--port','18081'],cwd=source,env=env,stdout=log,stderr=log,start_new_session=True);log.close();(a.out/'app.pid').write_text(str(proc.pid));health(18081)
        c=Api('http://127.0.0.1:18081');c.call('POST','/api/login',body=json.loads((app/'login.json').read_text()));me=c.call('GET','/api/me');teams=c.call('GET','/api/contract-memory/teams');records=[]
        with sqlite3.connect(app/'app.sqlite') as db:
            rows=db.execute('SELECT id FROM workspaces WHERE deleted_at IS NULL AND user_id=?',(me['id'],)).fetchall()
        conversations=[]
        for (wid,) in rows:
            w=c.call('GET','/api/workspaces/'+wid);records.append(w)
            if w.get('threads'):
                for attempt in range(30):
                    try:
                        conversations.append(c.call('GET','/api/threads/'+w['threads'][0]['id']));break
                    except StopRun as e:
                        if '返回 503' not in str(e):raise
                        if attempt==29:raise
                        time.sleep(.5)
        after=sql_inventory(app,core);before=json.loads((a.out/'backup-inventory.json').read_text());assert before==after,'Business/version inventory changed in isolated restore'
        atomic_json(a.out/(a.phase+'-checks.json'),{'status':'pass','ports':PORTS,'app_commit':manifest['app_commit'] if a.phase!='upgrade' else subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'images':images,'inventory':after,'account':{'id':me['id'],'username':me['username']},'teams':teams,'workspaces':records,'conversations':conversations,'model_transport':'blackholed explicitly; no model calls in rollback drill'})
    else:
        if (a.out/'app.pid').exists():
            pid=int((a.out/'app.pid').read_text())
            try:os.kill(pid,signal.SIGTERM)
            except ProcessLookupError:pass
        for port in range(18090,18094):
            listeners=subprocess.run(['lsof','-nP','-tiTCP:'+str(port),'-sTCP:LISTEN'],capture_output=True,text=True)
            for candidate in listeners.stdout.split():
                cmd=subprocess.run(['ps','-p',candidate,'-o','command='],capture_output=True,text=True).stdout
                if 'opencode' in cmd and str(port) in cmd:os.kill(int(candidate),signal.SIGTERM)
        for name in NAMES.values():run(['docker','rm','-f',name],stdout=subprocess.DEVNULL)
        run(['docker','network','rm','tdai-rollback-stack'],stdout=subprocess.DEVNULL)
        atomic_json(a.out/'cleanup.json',{'containers_removed':list(NAMES.values()),'data_retained':str(a.out)})
    print(a.phase,'completed',flush=True)
if __name__=='__main__':main()
