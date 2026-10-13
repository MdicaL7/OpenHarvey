"""Live business-API scope/publication checks. Requires explicit execution and a private config.
Manual entry creation here tests user management, never extraction quality.
"""
import argparse,json,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'openharvey_contract_memory_pack/07_tools'))
from run_suite import Api,scrub
from suite_common import atomic_json,require_review

def main():
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');p.add_argument('--reviewed-pack-sha');p.add_argument('--config',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();require_review(a.execute,a.reviewed_pack_sha)
 if a.out.exists():raise SystemExit('Use a new evidence file for each independent run')
 cfg=json.loads(a.config.read_text());clients={};users={};evidence={'run_id':uuid.uuid4().hex,'method':'real business APIs; manually authored entry management only','checks':[]}
 def record(name,value):evidence['checks'].append({'name':name,'status':'pass','evidence':scrub(value)});atomic_json(a.out,evidence)
 for actor,account in cfg['accounts'].items():
  c=clients[actor]=Api(account.get('origin',cfg['origin']));c.call('POST','/api/login',body=json.loads(Path(account['login_file']).read_text()));users[actor]=c.call('GET','/api/me')
 owner,member,outsider=(clients[x] for x in ['owner','member','outsider'])
 def mutate(client,action,team,**kw):return client.call('POST','/api/contract-memory/'+action,body={'team_id':team,'operation_id':uuid.uuid4().hex,**kw})
 try:
  teams=[owner.call('POST','/api/contract-memory/teams',body={'name':'v2 权限 '+tag+' '+evidence['run_id'][:8]}) for tag in ['A','B']];ta,tb=[t['id'] for t in teams];evidence['teams']=teams;atomic_json(a.out,evidence)
  record('same_user_new_team_empty',owner.call('GET','/api/contract-memory/list?team_id='+tb))
  owner.call('PUT',f'/api/contract-memory/teams/{ta}/members/{users["member"]["id"]}',body={'role':'member','active':True})
  data={'kind':'experience','title':'验收异议处理方法','topic':'验收','content':'先核对验收标准与具体异议，再约定整改和复验期限。','conditions':['有书面异议和可验证的交付记录'],'exceptions':['不直接推定验收通过'],'source_ids':[]}
  private=mutate(owner,'create',ta,data=data);evidence['private_entry']=private;record('manual_entry_saved',private)
  assert not member.call('GET','/api/contract-memory/list?team_id='+ta)['items']
  record('member_cannot_read_private',member.call('GET',f'/api/contract-memory/detail/{private["id"]}?team_id={ta}',expected=404))
  record('other_team_cannot_read_private',owner.call('GET',f'/api/contract-memory/detail/{private["id"]}?team_id={tb}',expected=404))
  record('outsider_denied',outsider.call('GET','/api/contract-memory/list?team_id='+ta,expected=403))
  record('identity_forgery_rejected',owner.call('POST','/api/contract-memory/create',body={'team_id':ta,'user_id':users['member']['id'],'data':data,'operation_id':uuid.uuid4().hex},expected=422))
  proposed=mutate(owner,'propose',ta,id=private['id'],version=private['version'],operation='share',data=data)
  assert not member.call('GET','/api/contract-memory/list?team_id='+ta+'&scope=team')['items'];record('before_approval_private',proposed)
  record('member_approval_denied',member.call('POST','/api/contract-memory/review',body={'team_id':ta,'id':proposed['id'],'approved':True,'operation_id':uuid.uuid4().hex},expected=403))
  approval=mutate(owner,'review',ta,id=proposed['id'],approved=True);shared=member.call('GET','/api/contract-memory/list?team_id='+ta+'&scope=team')['items'];assert len(shared)==1
  detail=member.call('GET',f'/api/contract-memory/detail/{shared[0]["id"]}?team_id={ta}');assert all(src.get('restricted') is True and set(src)<={'restricted','label'} for src in detail['sources']);record('published_copy_without_private_sources',{'approval':approval,'detail':detail})
  changed={**private['data'],'content':'先核对客观验收标准、具体异议与交付记录，再明确整改和复验期限。'}
  body={'team_id':ta,'id':private['id'],'version':private['version'],'data':changed,'operation_id':uuid.uuid4().hex}
  edited=owner.call('POST','/api/contract-memory/update',body=body);again=owner.call('POST','/api/contract-memory/update',body=body);assert again==edited;record('idempotent_edit',edited)
  record('stale_version_rejected',owner.call('POST','/api/contract-memory/update',body={**body,'operation_id':uuid.uuid4().hex},expected=409))
  assert member.call('GET','/api/contract-memory/list?team_id='+ta+'&scope=team')['items'][0]['data']['content']==data['content'];record('personal_edit_does_not_overwrite_team',{'team_entry_id':shared[0]['id']})
  owner.call('PUT',f'/api/contract-memory/teams/{ta}/members/{users["member"]["id"]}',body={'role':'member','active':False})
  record('revoked_member_denied',member.call('GET','/api/contract-memory/list?team_id='+ta+'&scope=team',expected=403))
  record('revoked_member_mutation_denied',member.call('POST','/api/contract-memory/create',body={'team_id':ta,'data':data,'operation_id':uuid.uuid4().hex},expected=403))
  deleted=mutate(owner,'delete',ta,id=edited['id'],version=edited['version']);assert not owner.call('GET','/api/contract-memory/list?team_id='+ta)['items'];record('deletion_exits_personal_list',deleted)
  evidence['status']='pass';atomic_json(a.out,evidence)
 except Exception as e:
  evidence['status']='failed';evidence['error']=str(e);atomic_json(a.out,evidence);raise
 print(json.dumps({'status':evidence['status'],'checks':len(evidence['checks']),'evidence':str(a.out)},ensure_ascii=False))
if __name__=='__main__':main()
