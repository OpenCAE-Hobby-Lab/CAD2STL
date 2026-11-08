"""Local-only Web entry point. Uses the standalone CAD2STL worker."""
from __future__ import annotations
import argparse
import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import json
from pathlib import Path
import os
import webbrowser
import secrets
import socket
import subprocess
import sys
import uuid
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'CAD2STL'
LIMIT = 36 * 1024 * 1024

PAGE = '''<!doctype html><html lang="ja"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CAD → STL | 面色で境界を分ける</title>
<style>body{font:16px Meiryo,sans-serif;color:#171717;background:#f3f7fa;margin:0}main{max-width:850px;margin:36px auto;padding:32px;background:white;border:1px solid #d5e5ff;border-radius:12px}h1{font-size:27px;color:#245a81}label{display:block;margin:20px 0 8px}input,textarea,button{font:inherit;padding:10px;border:1px solid #9eb2c2;border-radius:5px;box-sizing:border-box}textarea{width:100%;font-family:Consolas,monospace}button{background:#245a81;color:white;cursor:pointer;margin:18px 8px 0 0}button:disabled{opacity:.5}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#edf4fa;padding:16px;max-height:400px;overflow:auto}.note{color:#53636f;font-size:14px}a{color:#245a81}</style>
<main><p class="note">ローカル変換 · 試作版 0.3 · FreeCAD不要</p><h1>面の色を、OpenFOAMの境界へ</h1>
<p>色付きSTEPから、境界ごとのSTLと変換記録をまとめたZIPを作成します。</p>
<label for="file">1. STEPファイル（.step / .stp、25 MiB以下）</label><input type="file" id="file" accept=".step,.stp">
<p class="note">Parasolidの直接読込は未対応です。SpaceClaim / Solid Edgeで色を保持したSTEPを書き出せるか確認してください。</p>
<button id="inspect">色を調べる</button>
<label for="mapping">2. 色と境界名の対応（RGB 16進表記 → 半角英数字の名前）</label>
<textarea id="mapping" rows="6" placeholder="空欄なら color_RRGGBB を自動設定。色を調べると対応表が入ります。"></textarea>
<label for="scale">3. mmから出力座標への倍率</label><input id="scale" type="number" value="0.001" step="any" min="0">
<p class="note">0.001でm単位。STEPの長さ単位は読込時にmmへ正規化されます。色が消えた入力や、対応表にない色は変換を停止します。</p>
<details><summary>三角化の設定</summary><label for="linear">長さの近似誤差（mm）</label><input id="linear" type="number" value="0.05" min="0" step="any"><label for="angular">角度の近似誤差（rad）</label><input id="angular" type="number" value="0.2" min="0" max="3.14159" step="any"><p class="note">細かくしても入力形状の不整合や自己交差が解消するとは限りません。</p></details>
<button id="convert">STLを作成してZIPを取得</button><a id="download" hidden>ZIPを保存</a>
<p id="status" role="status">ファイルを選択してください。</p><pre id="detail" hidden></pre>
<p class="note">出力には色別STL、確認用all_regions.stl、境界対応とハッシュ、OpenFOAM辞書の断片が含まれます。実ケースでsurfaceCheckとメッシュ品質を確認してください。</p>
</main><script>
const token='__TOKEN__';let previousUrl;
async function run(action){const status=document.querySelector('#status'),detail=document.querySelector('#detail');const buttons=[...document.querySelectorAll('button')];
try{const file=document.querySelector('#file').files[0];if(!file)throw Error('STEPファイルを選択してください。');if(file.size>25*1024*1024)throw Error('25 MiB以下にしてください。');
const text=document.querySelector('#mapping').value.trim();const map=text?JSON.parse(text):null;const scale=Number(document.querySelector('#scale').value);if(!Number.isFinite(scale)||scale<=0)throw Error('正の倍率を入力してください。');
const linear=Number(document.querySelector('#linear').value),angular=Number(document.querySelector('#angular').value);if(!Number.isFinite(linear)||linear<=0||!Number.isFinite(angular)||angular<=0||angular>Math.PI)throw Error('三角化の設定を確認してください。');
buttons.forEach(x=>x.disabled=true);document.querySelector('#download').hidden=true;detail.hidden=true;status.textContent='処理中です…';
const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
const res=await fetch('/api/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-CAD2STL-Token':token},body:JSON.stringify({filename:file.name,data:btoa(binary),map,scale,linear,angular})});
if(!res.ok)throw Error(await res.text());
if(action==='inspect'){const data=await res.json();document.querySelector('#mapping').value=JSON.stringify(data.suggested_color_map,null,2);status.textContent=data.geometry_issues.length?'入力の詳細幾何検査で問題を検出しました。下の詳細を確認してください。':'色の一覧と自動設定された境界名を確認してください。';detail.textContent=JSON.stringify({colors:data.colors,geometry_issues:data.geometry_issues,faces:data.faces},null,2);detail.hidden=false;}
else{const issues=Number(res.headers.get('X-CAD2STL-Geometry-Issues')||0);if(previousUrl)URL.revokeObjectURL(previousUrl);previousUrl=URL.createObjectURL(await res.blob());const link=document.querySelector('#download');link.href=previousUrl;link.download='cad2stl.zip';link.hidden=false;link.click();status.textContent=issues?'STLを生成しましたが入力幾何に問題があります。report.jsonとsurfaceCheckで確認が必要です。':'STLを生成しました。OpenFOAMのsurfaceCheckで品質を確認してください。';}}
catch(err){status.textContent=err.message;}finally{buttons.forEach(x=>x.disabled=false);}}
document.querySelector('#inspect').onclick=()=>run('inspect');document.querySelector('#convert').onclick=()=>run('convert');
</script></html>'''


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def reply(self, code, data, content_type='text/plain; charset=utf-8', headers=None):
        if isinstance(data, str):
            data = data.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Connection', 'close')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.connection.settimeout(120)
        for offset in range(0, len(data), 65536):
            self.wfile.write(data[offset:offset+65536])
        self.wfile.flush()
        self.close_connection = True
        # Finish the response direction gracefully before closing the socket.
        # Large ZIP downloads otherwise reset on some Windows TCP stacks.
        try:
            self.connection.shutdown(socket.SHUT_WR)
        except OSError:
            pass

    def valid_host(self):
        return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}

    def do_GET(self):
        if not self.valid_host():
            return self.reply(403, 'Invalid Host')
        if self.path != '/':
            return self.reply(404, 'Not found')
        self.reply(200, PAGE.replace('__TOKEN__', self.server.token), 'text/html; charset=utf-8')

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length <= 0 or length > LIMIT:
                return self.reply(413, 'Request size limit exceeded')
            # Drain a bounded request before replying, so Windows does not reset
            # the socket with unread request data and hide the error response.
            body = self.rfile.read(length)
            if not self.valid_host() or self.headers.get('X-CAD2STL-Token') != self.server.token:
                return self.reply(403, 'Invalid request token or Host')
            if self.path not in {'/api/inspect', '/api/convert'}:
                return self.reply(404, 'Not found')
            request = json.loads(body)
            suffix = Path(request['filename']).suffix.lower()
            if suffix not in {'.step', '.stp'}:
                raise ValueError('Only STEP supported; Parasolid direct import is not implemented')
            data = base64.b64decode(request['data'], validate=True)
            if len(data) > 25*1024*1024:
                return self.reply(413, 'Input limit: 25 MiB')
            job = self.server.jobs / uuid.uuid4().hex
            job.mkdir(parents=True, exist_ok=False)
            source = job / ('input'+suffix)
            source.write_bytes(data)
            action = self.path.rsplit('/', 1)[-1]
            command = [sys.executable]
            if not getattr(sys, 'frozen', False):
                command.append(str(HERE/'cad2stl.py'))
            command += [action, str(source)]
            if action == 'inspect':
                command += ['--report', str(job/'inspection.json')]
            else:
                if request.get('map') is not None:
                    mapping = job/'colors.json'
                    mapping.write_text(json.dumps(request['map'], allow_nan=False), encoding='utf-8')
                    command += ['--map', str(mapping)]
                scale = request['scale']
                if isinstance(scale, bool) or not isinstance(scale, (int, float)):
                    raise ValueError('scale must be a positive number')
                command += ['--scale', str(scale), '--output', str(job/'output')]
                for key, flag, default in [('linear', '--linear-deflection', .05), ('angular', '--angular-deflection', .2)]:
                    value = request.get(key, default)
                    if isinstance(value, bool) or not isinstance(value, (int,float)):
                        raise ValueError(f'{key} must be a positive number')
                    command += [flag, str(value)]
            with (job/'worker.log').open('w', encoding='utf-8') as log:
                result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=120,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode:
                return self.reply(422, (job/'worker.log').read_text(encoding='utf-8')[-6000:])
            if action == 'inspect':
                self.reply(200, (job/'inspection.json').read_bytes(), 'application/json')
            else:
                archive = io.BytesIO()
                with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
                    for path in sorted((job/'output').iterdir()):
                        z.write(path, path.name)
                report = json.loads((job/'output/report.json').read_text(encoding='utf-8'))
                self.reply(200, archive.getvalue(), 'application/zip',
                           {'X-CAD2STL-Geometry-Issues': str(len(report['geometry_issues']))})
        except subprocess.TimeoutExpired:
            self.reply(504, 'Conversion timed out after 120 seconds; worker stopped')
        except (ValueError, KeyError, TypeError) as exc:
            self.reply(400, str(exc))
        except Exception as exc:
            self.reply(500, str(exc))


def create_server(port=8765, jobs=None):
    server = HTTPServer(('127.0.0.1', port), Handler)
    server.token = secrets.token_urlsafe(32)
    server.jobs = Path(jobs or ROOT/'work'/'web-jobs').resolve()
    return server


def main(argv=None, open_browser=False):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true', help='Do not open a browser automatically')
    args = parser.parse_args(argv)
    server = create_server(args.port)
    print(f'Open http://127.0.0.1:{server.server_port} (Ctrl+C to stop)', flush=True)
    if open_browser and not args.no_browser:
        webbrowser.open(f'http://127.0.0.1:{server.server_port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
