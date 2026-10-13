"""Local operator-only read-only export; credentials never appear in output."""
import argparse,base64,hashlib,json,sqlite3,subprocess,sys,urllib.request,urllib.parse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'openharvey_contract_memory_pack/07_tools'))
from suite_common import atomic_json

def export(app,username,threads,out):
 config=json.loads((app/'runtimes.json').read_text())[username]
 native={};auth='Basic '+base64.b64encode(('opencode:'+config['password']).encode()).decode()
 for t in threads:
  url=config['url']+'/session/'+t['session_id']+'/message?'+urllib.parse.urlencode({'directory':str(Path(config['work_root'])/t['id'])})
  req=urllib.request.Request(url,headers={'Authorization':auth})
  with urllib.request.urlopen(req,timeout=20) as response:native[t['id']]=json.load(response)
 atomic_json(out,{'threads':native})
 return native

def main():
 p=argparse.ArgumentParser();p.add_argument('--app-data',type=Path,required=True);p.add_argument('--username',required=True);p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();state=json.loads(a.checkpoint.read_text());threads=[t for ts in state['threads'].values() for t in ts];native=export(a.app_data,a.username,threads,a.out)
 tools=[p for msgs in native.values() for m in msgs for p in m.get('parts',[]) if p.get('type')=='tool'];print('Native messages exported:',len(native),'sessions;',len(tools),'tool parts')
if __name__=='__main__':main()
