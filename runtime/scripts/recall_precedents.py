#!/usr/bin/env python3
"""Current-session, read-only historical disposition lookup. No Memory writes."""
import argparse,json,urllib.request,urllib.error
from pathlib import Path
from urllib.parse import urlsplit

def main():
 p=argparse.ArgumentParser();p.add_argument('--risk-id',required=True);p.add_argument('--artifact-id');p.add_argument('--document-id');p.add_argument('--blocks');a=p.parse_args()
 root=Path.cwd();context=json.loads((root/'context.json').read_text());info=context.get('historical_dispositions')
 if not info:raise ValueError('本会话未配置历史处置查询')
 endpoint=info['endpoint'];save=context['save_url']
 if urlsplit(endpoint).netloc!=urlsplit(save).netloc or not endpoint.endswith('/internal/contract-memory/precedents'):raise ValueError('查询地址不属于当前工作台')
 body={'risk_id':a.risk_id}
 if a.artifact_id:body['artifact_id']=a.artifact_id
 else:body.update(document_id=a.document_id,block_ids=(a.blocks or '').split(','))
 req=urllib.request.Request(endpoint,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+(root/'.publish-token').read_text().strip()})
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 with opener.open(req,timeout=240) as r:print(r.read().decode())
if __name__=='__main__':
 try:main()
 except Exception:print(json.dumps({'available':False,'error':'历史处置查询失败；请核对当前合同、权限和服务状态'},ensure_ascii=False));raise SystemExit(1)
