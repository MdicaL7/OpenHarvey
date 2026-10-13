#!/usr/bin/env python3
"""Operator-only bounded SELECTs. Never instantiates/migrates an application Store."""
import argparse,hashlib,json,re,sqlite3,subprocess
from pathlib import Path
from suite_common import atomic_json
def scope_from_app(app_data,team_id,username):
    path=Path(app_data).resolve()/'app.sqlite'
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        row=db.execute('SELECT t.tdai_team_id AS team,t.agent_id AS agent,i.tdai_user_id AS user,i.binding FROM teams t JOIN team_members m ON m.team_id=t.id JOIN users u ON u.id=m.user_id JOIN memory_identities i ON i.user_id=u.id WHERE t.id=? AND u.username=? AND m.active=1 AND u.active=1 AND t.org_id=u.org_id',(team_id,username)).fetchone()
        if not row:raise RuntimeError('诊断范围不属于当前有效测试成员')
        value=dict(row);binding=json.loads(value.pop('binding'));value['instance']=binding['service_id'];return value
def snapshot(config,team_id,username,run=subprocess.run):
    scope=scope_from_app(config['app_data'],team_id,username);filename=hashlib.sha256(json.dumps(scope['instance'],ensure_ascii=False).encode()).hexdigest()[:24]
    dbpath='/data/tdai-memory/contract-memory/'+filename+'/contract.sqlite'
    code="""import {DatabaseSync} from 'node:sqlite';
const [path,scope]=process.argv.slice(1);const c=JSON.parse(scope);
const db=new DatabaseSync(path,{readOnly:true});
const out={scope:c};
for(const table of ['raw','atoms','jobs','candidates','entries','proposals','audit','tombstones']){
 const where='instance=? AND team=? AND agent=? AND '+(table==='entries'?"(user=? OR scope='team')":"user=?");
 out[table]=db.prepare('SELECT * FROM '+table+' WHERE '+where).all(c.instance,c.team,c.agent,c.user).map(r=>{if(r.data)r.data=JSON.parse(r.data);return r;});
}
const extraTables=new Set(db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all().map(r=>r.name));
for(const table of ['review_events','review_cases','preference_statements'])out[table]=extraTables.has(table)?db.prepare('SELECT * FROM '+table+' WHERE instance=? AND team=? AND agent=? AND user=?').all(c.instance,c.team,c.agent,c.user).map(r=>({...r,data:JSON.parse(r.data)})):[];
const ids=out.entries.filter(e=>e.user===c.user).map(e=>e.id);
out.revisions=ids.flatMap(id=>db.prepare('SELECT * FROM revisions WHERE id=? ORDER BY version').all(id).map(r=>({...r,data:JSON.parse(r.data)})));
const tables=new Set(db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all().map(r=>r.name));
out.extraction_runs=tables.has('extraction_runs')?db.prepare('SELECT e.job,e.data FROM extraction_runs e JOIN jobs j ON j.id=e.job WHERE j.instance=? AND j.team=? AND j.agent=? AND j.user=?').all(c.instance,c.team,c.agent,c.user).map(r=>({...r,data:JSON.parse(r.data)})):[];
const owned=new Set([...out.raw,...out.atoms,...out.review_events,...out.preference_statements,...out.review_cases.flatMap(c=>[c,{id:c.id+'@'+c.version}]),...out.entries.filter(e=>e.user===c.user)].map(r=>r.id));
out.llm_runs=tables.has('llm_runs')?db.prepare('SELECT id,data FROM llm_runs').all().map(r=>({...r,data:JSON.parse(r.data)})).filter(r=>{const input=r.data.input;const refs=Array.isArray(input)?input:['messages','review_events','cases','preferences','confirmed_experiences','reuse_instructions','existing'].flatMap(k=>input?.[k]||[]);if(!Array.isArray(refs)||!refs.length)return false;return refs.every(x=>owned.has(x.id||x.source_id));}):[];
db.close();console.log(JSON.stringify(out));"""
    if config.get('sqlite_path'):
        # Local fixtures / offline operator copy; parameterized, same scope constraints.
        with sqlite3.connect(Path(config['sqlite_path']).resolve().as_uri()+'?mode=ro',uri=True) as db:
            db.row_factory=sqlite3.Row;out={'scope':scope}
            for table in ['raw','atoms','jobs','candidates','entries','proposals','audit','tombstones']:
                where='instance=? AND team=? AND agent=? AND '+("(user=? OR scope='team')" if table=='entries' else 'user=?')
                result=[dict(r) for r in db.execute('SELECT * FROM '+table+' WHERE '+where,tuple(scope[k] for k in ['instance','team','agent','user']))]
                for row in result:
                    if row.get('data'):row['data']=json.loads(row['data'])
                out[table]=result
            out['revisions']=[dict(r) for e in out['entries'] if e['user']==scope['user'] for r in db.execute('SELECT * FROM revisions WHERE id=? ORDER BY version',(e['id'],))]
            for r in out['revisions']:r['data']=json.loads(r['data'])
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ['review_events','review_cases','preference_statements']:
                values=[dict(r) for r in db.execute('SELECT * FROM '+table+' WHERE instance=? AND team=? AND agent=? AND user=?',tuple(scope[k] for k in ['instance','team','agent','user']))] if table in tables else []
                for r in values:r['data']=json.loads(r['data'])
                out[table]=values
            out['extraction_runs']=[{'job':r[0],'data':json.loads(r[1])} for r in db.execute('SELECT e.job,e.data FROM extraction_runs e JOIN jobs j ON j.id=e.job WHERE j.instance=? AND j.team=? AND j.agent=? AND j.user=?',tuple(scope[k] for k in ['instance','team','agent','user']))] if 'extraction_runs' in tables else []
            owned={r['id'] for name in ['raw','atoms','entries'] for r in out[name] if name!='entries' or r['user']==scope['user']}
            owned.update(r['id'] for name in ['review_events','review_cases','preference_statements'] for r in out[name]);owned.update(r['id']+'@'+str(r['version']) for r in out['review_cases'])
            out['llm_runs']=[]
            if 'llm_runs' in tables:
                for row in db.execute('SELECT id,data FROM llm_runs'):
                    data=json.loads(row[1]);value=data.get('input');refs=value if isinstance(value,list) else [r for k in ['messages','review_events','cases','preferences','confirmed_experiences','reuse_instructions','existing'] for r in value.get(k,[])] if isinstance(value,dict) else []
                    if refs and all((x.get('id') or x.get('source_id')) in owned for x in refs):out['llm_runs'].append({'id':row[0],'data':data})
            return out
    container=config.get('container','tdai-contract-core')
    if not re.fullmatch(r'[a-zA-Z0-9_.-]+',container):raise RuntimeError('Invalid diagnostic container')
    r=run(['docker','exec',container,'node','--input-type=module','-e',code,dbpath,json.dumps(scope)],capture_output=True,text=True,timeout=30)
    if r.returncode:raise RuntimeError('只读 Core 快照失败；确认诊断路径及服务，不把缺失证据当通过')
    return json.loads(r.stdout)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--team-id',required=True);p.add_argument('--username',required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    atomic_json(a.out,snapshot(json.loads(a.config.read_text())['diagnostics'],a.team_id,a.username))
