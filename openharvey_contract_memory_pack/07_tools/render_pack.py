#!/usr/bin/env python3
"""Render all final DOCX with the selected bundled runtime; keep QA intermediates outside the pack."""
import argparse,concurrent.futures,json,os,subprocess
from pathlib import Path
from suite_common import ROOT,atomic_json
def main():
    p=argparse.ArgumentParser();p.add_argument('--python',required=True);p.add_argument('--renderer',type=Path,required=True);p.add_argument('--bundled-font-dir',type=Path,required=True);p.add_argument('--font-dir',type=Path);p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    dirs=[a.bundled_font_dir]
    if a.font_dir:dirs.append(a.font_dir)
    for path in ['/System/Library/Fonts','/System/Library/Fonts/Supplemental']:
        if Path(path).is_dir():dirs.append(Path(path))
    import html
    fonts=a.out/'fonts.conf';fonts.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig>'+''.join('<dir>'+html.escape(str(d))+'</dir>' for d in dirs)+'<cachedir>'+html.escape(str(a.out/'font-cache'))+'</cachedir></fontconfig>')
    env={**os.environ,'FONTCONFIG_FILE':str(fonts.resolve())}
    def render(m):
        out=a.out/m['doc_id'];result=subprocess.run([a.python,str(a.renderer),str(ROOT/m['docx_path']),'--output_dir',str(out),'--emit_pdf'],capture_output=True,text=True,env=env)
        (a.out/(m['doc_id']+'.log')).write_text(result.stdout+result.stderr)
        return {'doc_id':m['doc_id'],'docx_sha256':m['docx_sha256'],'exit_code':result.returncode,'pages':len(list(out.glob('page-*.png')))}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(render,json.loads((ROOT/'00_start_here/contract_manifest.json').read_text())))
    atomic_json(a.out/'render_summary.json',{'documents':results,'visual_review':'pending','real_models_executed':False})
    print(json.dumps(results,ensure_ascii=False));assert all(r['exit_code']==0 and r['pages'] for r in results)
if __name__=='__main__':main()
