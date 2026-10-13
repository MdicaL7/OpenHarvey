"""Start the already-reviewed local structured bridge without printing private tokens."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'openharvey_contract_memory_pack/07_tools'))
from structured_model import serve
from suite_common import require_review
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--state-root',type=Path,required=True);p.add_argument('--execute',action='store_true');p.add_argument('--reviewed-pack-sha');p.add_argument('--host',default='0.0.0.0');p.add_argument('--port',type=int,default=8766);a=p.parse_args();require_review(a.execute,a.reviewed_pack_sha)
 serve(json.loads((a.state_root/'models.json').read_text()),a.host,a.port,json.loads((a.state_root/'role-tokens.json').read_text()),a.execute)
