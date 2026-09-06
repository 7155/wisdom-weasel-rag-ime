#!/usr/bin/env python3
"""Export one real Lab policy candidate as an independent, stdlib-only Web App.

No new model call. The exported runtime uses the same policy implementation
as the frozen host verifier; expected answers and PAW imports stay outside it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rag_ime.agent_lab_micro import POLICY_APP, canonical, decode, verify_policy


SERVER = r'''import argparse, json, math, pathlib, runpy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = pathlib.Path(__file__).resolve().parent
decide = runpy.run_path(str(ROOT / 'policy.py'), run_name='exported_policy')['decide']
config = json.loads((ROOT / 'config.json').read_text())
class Handler(BaseHTTPRequestHandler):
    def reply(self, status, body, content_type='application/json; charset=utf-8'):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/':
            self.reply(200, (ROOT / 'index.html').read_bytes(), 'text/html; charset=utf-8')
        elif path == '/api/policy':
            self.reply(200, config)
        else:
            self.reply(404, {'error': 'not_found'})
    def do_POST(self):
        if self.path != '/api/decide':
            return self.reply(404, {'error': 'not_found'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 1024: raise ValueError('body size')
            expense = json.loads(self.rfile.read(size))
            if not isinstance(expense, dict) or set(expense) != {'amount','currency','receipt'}: raise ValueError('fields')
            amount = expense['amount']
            if type(amount) not in (int,float) or not math.isfinite(amount) or amount < 0: raise ValueError('amount')
            if type(expense['receipt']) is not bool or not isinstance(expense['currency'], str) or not 1 <= len(expense['currency']) <= 8: raise ValueError('type')
            self.reply(200, {'decision': decide(config, expense)})
        except (ValueError, TypeError, KeyError):
            self.reply(400, {'error': 'invalid_expense'})
    def log_message(self, *_args):
        pass
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8769)
    args = parser.parse_args()
    with ThreadingHTTPServer(('127.0.0.1', args.port), Handler) as server:
        print(json.dumps({'url': f'http://127.0.0.1:{server.server_port}/'}), flush=True)
        server.serve_forever()
'''

HTML = r'''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>费用规则 · PAW Lab 导出</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f4f5f2;color:#1e2925;font:16px/1.6 system-ui,sans-serif}
main{max-width:620px;margin:8vh auto;padding:32px;background:white;border:1px solid #dce2dc;border-radius:16px}
small{color:#52675e}h1{font-size:30px;margin:10px 0}p{margin:10px 0 24px}label{display:block;margin-top:16px}
input[type=number],select{display:block;width:100%;padding:11px;margin-top:5px;border:1px solid #9aa99f;border-radius:8px;font:inherit}
.receipt{display:flex;gap:9px;align-items:center}button{margin-top:24px;background:#215e47;color:white;border:0;border-radius:8px;padding:12px 22px;font:inherit;cursor:pointer}
button:disabled{opacity:.6}output{display:block;margin-top:24px;min-height:48px;padding:12px;background:#eef3ef;border-radius:8px}
footer{font-size:13px;color:#65726b;margin-top:28px}@media(max-width:650px){main{margin:20px 12px;padding:24px}}
</style>
<main><small>PAW LAB · 规则配置 v2</small><h1>费用审核</h1>
<p id="policy">正在读取导出配置…</p>
<form id="expense"><label for="amount">金额</label><input id="amount" type="number" min="0" step="0.01" value="600" required>
<label for="currency">币种</label><select id="currency"><option value="CNY">人民币 CNY</option><option value="USD">美元 USD</option></select>
<label class="receipt" for="receipt"><input id="receipt" type="checkbox" checked>已提供票据</label>
<button type="submit" id="submit">检查费用</button></form>
<output id="result" role="status" aria-live="polite">填写费用后开始检查。</output>
<footer>合成政策样例。此 App 读取随包交付的规则，在本机完成计算。</footer></main>
<script>
const form=document.querySelector('#expense'), result=document.querySelector('#result'), button=document.querySelector('#submit');
fetch('/api/policy').then(r=>{if(!r.ok)throw Error();return r.json()}).then(p=>{document.querySelector('#policy').textContent=`当前规则：${p.currency} 上限 ${p.limit}，${p.receiptRequired?'需要':'不要求'}票据。其他币种转人工审核。`}).catch(()=>{document.querySelector('#policy').textContent='配置读取失败，请重新启动 App。';button.disabled=true});
form.addEventListener('submit',async event=>{event.preventDefault();button.disabled=true;result.textContent='检查中…';try{const response=await fetch('/api/decide',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({amount:Number(document.querySelector('#amount').value),currency:document.querySelector('#currency').value,receipt:document.querySelector('#receipt').checked})});if(!response.ok)throw Error();const data=await response.json();const labels={approved:'通过',rejected:'不通过',manual:'转人工审核'};result.textContent=labels[data.decision]+' · '+data.decision;result.dataset.decision=data.decision}catch{result.textContent='未得到检查结果，请核对输入和本机服务。';delete result.dataset.decision}finally{button.disabled=false}});
</script></html>
'''


def export_app(config, archive, *, provenance):
    if not verify_policy(config)["allPassed"]:
        raise ValueError("candidate quality gate failed")
    manifest = {"schemaVersion": "paw.policy-app-export.v1", "kind": "standalone_web_app",
                "configSha256": hashlib.sha256(canonical(config).encode()).hexdigest(),
                "requires": ["Python 3 standard library", "web browser"], "providerCallsAtRuntime": 0,
                "source": provenance, "syntheticBusinessPolicy": True}
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as zipped:
        for name, body in {"policy.py": POLICY_APP, "server.py": SERVER, "index.html": HTML,
                           "config.json": canonical(config), "export.json": canonical(manifest),
                           "README.txt": "费用规则 App（合成样例）\n解压后运行：python3 -I -S server.py\n打开 http://127.0.0.1:8769/\n只需 Python 标准库与浏览器，不需要 PAW、Node、API key 或网络依赖。\n使用 --port 其他端口 可避免占用冲突；Ctrl+C 停止。\n"}.items():
            zipped.writestr(name, body)
    return manifest


def request_json(url, payload=None):
    request = urllib.request.Request(url, data=None if payload is None else canonical(payload).encode(),
                                    headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


def verify_app(archive, config, *, repeats=3):
    before = verify_policy(config)
    observations = []
    for ordinal in range(repeats):
        with tempfile.TemporaryDirectory(prefix="paw-policy-clean-") as temporary:
            clean = Path(temporary).resolve()
            with zipfile.ZipFile(archive) as zipped:
                if any(not (clean / name).resolve().is_relative_to(clean) for name in zipped.namelist()):
                    raise ValueError("unsafe archive path")
                zipped.extractall(clean)
            started = time.monotonic()
            process = subprocess.Popen([sys.executable, "-I", "-S", str(clean / "server.py"), "--port", "0"],
                cwd=clean, env={"HOME":str(clean),"PATH":"/usr/bin:/bin","LANG":"en_US.UTF-8"},
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                import selectors
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    if not selector.select(timeout=8):
                        raise RuntimeError("exported server did not start")
                url = json.loads(process.stdout.readline())["url"]
                with urllib.request.urlopen(url, timeout=5) as response:
                    page = response.read().decode()
                startup_ms = round((time.monotonic()-started)*1000,3)
                loaded = request_json(url+"api/policy")
                rows=[]
                for case in before["cases"]:
                    actual = request_json(url+"api/decide", case["input"])["decision"]
                    rows.append({**case,"actual":actual,"passed":actual==case["expected"]})
                observations.append({"run":ordinal+1,"startupPassed":"费用审核" in page and loaded==config,
                    "startupMs":startup_ms,"cases":rows,"businessPasses":sum(row["passed"] for row in rows)})
            finally:
                process.terminate()
                try:process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill();process.communicate()
    return {"schemaVersion":"paw.policy-app-acceptance.v1","startupAttempts":repeats,
            "startupPasses":sum(row["startupPassed"] for row in observations),"uniqueBusinessCases":4,
            "businessObservations":4*repeats,"businessPasses":sum(row["businessPasses"] for row in observations),
            "parity":all(case["actual"]==original["actual"] for row in observations for case,original in zip(row["cases"],before["cases"],strict=True)),
            "stdlibOnly":True,"processCommand":"python -I -S server.py --port 0","homeAndWorkingDirectoryIsolated":True,
            "providerCalls":0,"observations":observations,"archiveSha256":hashlib.sha256(Path(archive).read_bytes()).hexdigest(),
            "browserUiAcceptance":"unmeasured","newPhysicalMachine":False}


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run",type=Path,required=True)
    parser.add_argument("--output-root",type=Path,required=True)
    args=parser.parse_args()
    output=args.output_root.expanduser().resolve()
    if output.exists() or output.is_relative_to(ROOT):parser.error("new output directory outside checkout required")
    job_path=args.source_run/"optimization-job.json"
    job=json.loads(job_path.read_text())
    if job["state"]!="completed" or job["result"]["qualityVerdict"]!="keep":raise ValueError("source Lab quality did not pass")
    key=job["result"]["artifactKey"]
    if len(key)!=64 or any(c not in "0123456789abcdef" for c in key):raise ValueError("invalid artifact identity")
    call_path=args.source_run/"trials"/key/"call-3.json"
    call=json.loads(call_path.read_text())
    if call["receipt"]["requestId"]!=job["jobId"]+":candidate":raise ValueError("candidate receipt mismatch")
    config=decode(call["text"])
    output.mkdir(mode=0o700)
    archive=output/"expense-policy-web-app.zip"
    manifest=export_app(config,archive,provenance={"labJobId":job["jobId"],"jobReceiptSha256":hashlib.sha256(job_path.read_bytes()).hexdigest(),
        "candidateReceiptSha256":hashlib.sha256(call_path.read_bytes()).hexdigest(),"qualityVerdict":"keep","costVerdict":"no_improvement"})
    report=verify_app(archive,config)
    report["manifest"]=manifest
    (output/"acceptance.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    with zipfile.ZipFile(archive) as zipped:zipped.extractall(output/"app")
    print(canonical({k:v for k,v in report.items() if k not in {"observations","manifest"}}))
    return 0 if report["startupPasses"]==3 and report["businessPasses"]==12 and report["parity"] else 1


if __name__=="__main__":raise SystemExit(main())
