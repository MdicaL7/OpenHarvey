"""Shared manifest, provenance and atomic checkpoint helpers."""
import hashlib,json,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def read_json(path):return json.loads(Path(path).read_text())
def manifest(name):return read_json(ROOT/'09_scenarios_OPERATOR_ONLY'/name)
def atomic_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');tmp.chmod(0o600);os.replace(tmp,path)
def pack_digest():
    h=hashlib.sha256()
    for p in sorted(ROOT.rglob('*')):
        rel=p.relative_to(ROOT)
        if not p.is_file() or p.name=='SHA256SUMS' or any(part in {'08_validation','__pycache__','runs','secrets'} for part in rel.parts):continue
        h.update(str(rel).encode()+b'\0'+p.read_bytes()+b'\0')
    return h.hexdigest()
def require_review(execute,reviewed):
    digest=pack_digest()
    if not execute or reviewed!=digest:raise RuntimeError('真实执行需 --execute 及人工审查通过的当前 --reviewed-pack-sha；当前包 '+digest)
    return digest
def input_files():
    entries=read_json(ROOT/'00_start_here/input_manifest_OPERATOR_ONLY.json')
    result={r['input_id']:r for r in entries};result['IDENTITY-MAP']={'input_id':'IDENTITY-MAP','path':'01_history/identity_map.txt'}
    return result
def source_mapping(input_id,document,fixture_path):
    """Match actual parsed blocks. Do not invent block IDs or claim actual read."""
    body=Path(fixture_path).read_bytes();locations=[r for r in manifest('source_locations.json') if r['input_id']==input_id]
    blocks=document.get('segments',[]);result=[]
    for loc in locations:
        exact=loc['text'];matches=[]
        for i,b in enumerate(blocks):
            combined='\n'.join(x.get('text','') for x in blocks[i:])
            # Heading/body may be separate blocks; collect only until this clause ends.
            if exact.split('\n')[0] in b.get('text','') or (not loc.get('clause_number') and exact in combined):
                fragment='';selected=[]
                for bb in blocks[i:]:
                    if selected and loc.get('clause_number') and bb.get('text','').startswith('第') and '条 ' in bb.get('text',''):break
                    fragment+='\n'+bb.get('text','');selected.append(bb['id'])
                    if not loc.get('clause_number') and exact in fragment:break
                if exact.replace('\n','').replace(' ','') in fragment.replace('\n','').replace(' ',''):matches.append(selected)
        result.append({'fixture_input_id':input_id,'fixture_clause_id':loc['anchor'],'fixture_file_sha256':hashlib.sha256(body).hexdigest(),'runtime_document_id':document['id'],'runtime_block_ids':matches[0] if len(matches)==1 else [],'mapping_status':'matched' if len(matches)==1 else 'ambiguous' if matches else 'unmapped','native_read_verified':False})
    return result
