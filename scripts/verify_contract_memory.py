#!/usr/bin/env python3
"""Live local API acceptance; creates synthetic team/member only in the lab."""
import argparse,json,secrets,sys,time
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from contract_web.store import Store
from contract_web.settings import Settings
from contract_web.model_settings import Models

def main():
 p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);p.add_argument('--origin',default='http://127.0.0.1:8081');a=p.parse_args()
 store=Store(a.data);models=Models(Settings(store,ROOT/'runtime/skills'));headers={'X-Workbench-Request':'1'};checks=[]
 def check(name,value):
  assert value,name;checks.append({'name':name,'passed':True});print(name+': PASS')
 def post(c,path,body):
  r=c.post(path,json=body,headers=headers);r.raise_for_status();return r.json()
 with httpx.Client(base_url=a.origin,timeout=30) as admin:
  admin.get('/api/me').raise_for_status();teams=admin.get('/api/contract-memory/teams').json();tid=teams['selected'];personal=admin.get('/api/contract-memory/list',params={'team_id':tid}).json()['items'];shared=admin.get('/api/contract-memory/list',params={'team_id':tid,'scope':'team'}).json()['items'];check('confirmed personal and published team memories',len(personal)>=2 and len(shared)>=1)
  team2=post(admin,'/api/contract-memory/teams',{'name':'合成验收团队 B'})
  check('same user different team has no inherited personal memory',admin.get('/api/contract-memory/list',params={'team_id':team2['id']}).json()['items']==[])
  check('same user different team has no inherited team memory',admin.get('/api/contract-memory/list',params={'team_id':team2['id'],'scope':'team'}).json()['items']==[])
  password=secrets.token_urlsafe(24);username='contract-colleague-'+secrets.token_hex(3);uid=store.add_user(username,password);store.execute("UPDATE users SET org_id='default',role='member' WHERE id=?",(uid,))
  posturl=f'/api/contract-memory/teams/{tid}/members/{uid}';admin.put(posturl,headers=headers,json={'role':'member','active':True}).raise_for_status()
  with httpx.Client(base_url=a.origin,timeout=30) as member:
   post(member,'/api/login',{'username':username,'password':password})
   check('another member cannot see personal memory',member.get('/api/contract-memory/list',params={'team_id':tid}).json()['items']==[])
   check('another member can see approved team summary',len(member.get('/api/contract-memory/list',params={'team_id':tid,'scope':'team'}).json()['items'])==len(shared))
   check('another member cannot open source contract',member.get('/api/workspaces/'+admin.get('/api/workspaces').json()[0]['id']).status_code==404)
   check('team source stays restricted',all(s['restricted'] for s in member.get('/api/contract-memory/detail/'+shared[0]['id'],params={'team_id':tid}).json()['sources']))
   check('member cannot approve shared proposal',member.post('/api/contract-memory/review',headers=headers,json={'team_id':tid,'id':'invalid','approved':True,'operation_id':'test'}).status_code==403)
   i=store.one('SELECT * FROM memory_identities WHERE user_id=?',(uid,));t=store.one('SELECT * FROM teams WHERE id=?',(tid,));owner=store.one('SELECT * FROM memory_identities WHERE user_id=?',(t['owner_id'],));binding=json.loads(i['binding']);kh={'x-tdai-service-id':'default','x-tdai-user-key':models.decrypt(i['secret']),'Authorization':'Bearer local'};body={'team_id':t['tdai_team_id'],'agent_id':t['agent_id'],'user_id':owner['tdai_user_id']}
   check('Core rejects forged user even with valid member key',httpx.post(binding['core_url']+'/v3/atomic/query',headers=kh,json=body).status_code==403)
   body['user_id']=i['tdai_user_id'];body['content']='attempt to bypass';body['path']='fake'
   check('Core denies legacy write bypass',httpx.post(binding['core_url']+'/v3/scenario/write',headers=kh,json=body).status_code==403)
   admin.put(posturl,headers=headers,json={'role':'member','active':False}).raise_for_status()
   check('membership removal revokes application memory access',member.get('/api/contract-memory/list',params={'team_id':tid}).status_code==403)
   check('membership removal revokes direct Core recall',httpx.post(binding['core_url']+'/v3/core/read',headers=kh,json=body).status_code==403)
   admin.patch('/api/admin/users/'+uid,headers=headers,json={'active':False}).raise_for_status()
   check('account disable revokes upstream user key',httpx.post(binding['core_url']+'/v3/contract-memory/list',headers=kh,json=body).status_code==401)
  # Same operation ID returns the same entry, then delete it with version check.
  data={'kind':'preference','title':'合成幂等测试','content':'仅用于验证，不是业务标准','topic':'测试','conditions':[],'exceptions':[],'source_ids':[]};req={'team_id':tid,'operation_id':secrets.token_hex(12),'data':data}
  e=post(admin,'/api/contract-memory/create',req);e2=post(admin,'/api/contract-memory/create',req);check('repeat create is idempotent',e['id']==e2['id'])
  changed=post(admin,'/api/contract-memory/update',{'team_id':tid,'id':e['id'],'version':e['version'],'operation_id':secrets.token_hex(12),'data':{**data,'content':'人工修订'}})
  check('stale edit is rejected',admin.post('/api/contract-memory/update',headers=headers,json={'team_id':tid,'id':e['id'],'version':1,'operation_id':secrets.token_hex(12),'data':data}).status_code==409)
  post(admin,'/api/contract-memory/delete',{'team_id':tid,'id':e['id'],'version':changed['version'],'operation_id':secrets.token_hex(12)})
  check('deleted entry disappears immediately',all(x['id']!=e['id'] for x in admin.get('/api/contract-memory/list',params={'team_id':tid}).json()['items']))
  result={'recorded':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'origin':a.origin,'checks':checks,'team_ids':[tid,team2['id']],'model':'deepseek-flash'}
  (ROOT/'docs/evidence/contract-memory/api-acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':main()
