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
<style>
body{font:16px Meiryo,sans-serif;color:#171717;background:#f3f7fa;margin:0}
main{max-width:850px;margin:36px auto;padding:32px;background:white;border:1px solid #d5e5ff;border-radius:12px}
h1{font-size:27px;color:#245a81}h2{font-size:18px;margin:24px 0 8px}
label{display:block;margin:20px 0 8px}
input,select,button{font:inherit;padding:10px;border:1px solid #9eb2c2;border-radius:5px;box-sizing:border-box;max-width:100%}
button{background:#245a81;color:white;cursor:pointer;margin:18px 8px 0 0}button:disabled{opacity:.5;cursor:default}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:8px;border-bottom:1px solid #d5e5ff}
td:last-child input{width:100%}.swatch{display:inline-block;width:1em;height:1em;border:1px solid #53636f;border-radius:3px;vertical-align:middle;margin-right:8px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#edf4fa;padding:16px;max-height:400px;overflow:auto}
.note{color:#53636f;font-size:14px}a{color:#245a81}
</style>
<main><p class="note">ローカル変換 · 試作版 0.4 · FreeCAD不要</p><h1>面の色を、OpenFOAMの境界へ</h1>
<p>色付きSTEPから、STLと変換記録をまとめたZIPを作成します。</p>
<label for="file">1. STEPファイル（.step / .stp、25 MiB以下）</label><input type="file" id="file" accept=".step,.stp">
<p class="note">Parasolidの直接読込は未対応です。SpaceClaim / Solid Edgeで色を保持したSTEPを書き出せるか確認してください。</p>
<button id="inspect" disabled>色を調べる</button>
<h2 id="mapping-title">2. 色ごとのSTL名</h2>
<p class="note" id="mapping-help">色を調べると一覧が表示されます。名前は半角英字で始め、半角英数字とアンダースコアで指定します。</p>
<table id="mapping" aria-labelledby="mapping-title" aria-describedby="mapping-help" hidden>
<thead><tr><th scope="col">面の色</th><th scope="col">面数</th><th scope="col">STL名</th></tr></thead>
<tbody id="colors"></tbody></table>
<label for="output-mode">3. STLの出力形式</label>
<select id="output-mode">
<option value="separate">色ごとに個別のSTLファイル</option>
<option value="combined">1つのSTLファイルにまとめる</option>
</select>
<p class="note">個別出力では設定した名前がファイル名になります。単一出力では all_regions.stl 内の領域名になります。</p>
<label for="scale">4. mmから出力座標への倍率</label><input id="scale" type="number" value="0.001" step="any" min="0">
<p class="note">0.001でm単位。STEPの長さ単位は読込時にmmへ正規化されます。色が消えた入力や、対応表にない色は変換を停止します。</p>
<details><summary>三角化の設定</summary><label for="linear">長さの近似誤差（mm）</label><input id="linear" type="number" value="0.05" min="0" step="any"><label for="angular">角度の近似誤差（rad）</label><input id="angular" type="number" value="0.2" min="0" max="3.14159" step="any"><p class="note">細かくしても入力形状の不整合や自己交差が解消するとは限りません。</p></details>
<button id="convert" disabled>STLを作成してZIPを取得</button><a id="download" hidden>ZIPを保存</a>
<p id="status" role="status">ファイルを選択してください。</p><pre id="detail" hidden></pre>
<p class="note">ZIPには選択した形式のSTL、変換記録、OpenFOAM辞書の断片が含まれます。実ケースでsurfaceCheckとメッシュ品質を確認してください。</p>
</main><script>
const token = '__TOKEN__';
const fileInput = document.querySelector('#file');
const inspectButton = document.querySelector('#inspect');
const convertButton = document.querySelector('#convert');
const status = document.querySelector('#status');
const detail = document.querySelector('#detail');
const table = document.querySelector('#mapping');
const colorRows = document.querySelector('#colors');
const download = document.querySelector('#download');
let inspection, previousUrl;

function clearDownload() {
    if (previousUrl) URL.revokeObjectURL(previousUrl);
    previousUrl = undefined;
    download.hidden = true;
}

function showColors(data) {
    const previousNames = new Map([...colorRows.querySelectorAll('input')]
        .map(input => [input.dataset.color, input.value]));
    colorRows.replaceChildren();
    for (const [color, count] of Object.entries(data.colors)) {
        const row = colorRows.insertRow();
        const colorCell = row.insertCell();
        const suggested = data.suggested_color_map[color];
        if (suggested) {
            const swatch = document.createElement('span');
            swatch.className = 'swatch';
            swatch.style.backgroundColor = color;
            swatch.setAttribute('aria-hidden', 'true');
            colorCell.append(swatch, color);
        } else {
            colorCell.textContent = '未着色';
        }
        row.insertCell().textContent = count;
        const nameCell = row.insertCell();
        if (suggested) {
            const input = document.createElement('input');
            input.type = 'text';
            input.maxLength = 64;
            input.dataset.color = color;
            input.setAttribute('aria-label', color + ' のSTL名');
            input.value = previousNames.get(color) ?? suggested;
            nameCell.append(input);
        } else {
            nameCell.textContent = 'STEPで色を設定してください';
        }
    }
    table.hidden = false;
}

function conversionOptions() {
    const map = {};
    const names = new Set();
    for (const input of colorRows.querySelectorAll('input')) {
        const name = input.value.trim();
        if (!/^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(name)) {
            throw Error(input.dataset.color + ' のSTL名を半角英字で始め、半角英数字とアンダースコアで入力してください。');
        }
        const key = name.toLowerCase();
        if (names.has(key)) throw Error('STL名が重複しています。色ごとに異なる名前を入力してください。');
        names.add(key);
        map[input.dataset.color] = name;
    }
    const scale = Number(document.querySelector('#scale').value);
    const linear = Number(document.querySelector('#linear').value);
    const angular = Number(document.querySelector('#angular').value);
    if (!Number.isFinite(scale) || scale <= 0) throw Error('正の倍率を入力してください。');
    if (!Number.isFinite(linear) || linear <= 0 || !Number.isFinite(angular) || angular <= 0 || angular > Math.PI) {
        throw Error('三角化の設定を確認してください。');
    }
    return {map, scale, linear, angular, output_mode: document.querySelector('#output-mode').value};
}

async function run(action) {
    fileInput.disabled = inspectButton.disabled = convertButton.disabled = true;
    clearDownload();
    try {
        const file = fileInput.files[0];
        if (!file) throw Error('STEPファイルを選択してください。');
        if (file.size > 25 * 1024 * 1024) throw Error('25 MiB以下にしてください。');
        const options = action === 'convert' ? conversionOptions() : {};
        status.textContent = '処理中です…';
        const bytes = new Uint8Array(await file.arrayBuffer());
        let binary = '';
        for (let i = 0; i < bytes.length; i += 8192) {
            binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
        }
        const res = await fetch('/api/' + action, {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CAD2STL-Token': token},
            body: JSON.stringify({filename: file.name, data: btoa(binary), ...options}),
        });
        if (!res.ok) throw Error(await res.text());
        if (action === 'inspect') {
            inspection = await res.json();
            showColors(inspection);
            const issues = inspection.geometry_issues;
            detail.textContent = JSON.stringify(issues, null, 2);
            detail.hidden = !issues.length;
            if (inspection.colors[inspection.missing_color_sentinel]) {
                status.textContent = '未着色の面があります。元のCADで色を設定してから再度読み込んでください。';
            } else {
                status.textContent = issues.length
                    ? '入力の幾何検査で問題を検出しました。詳細を確認してください。'
                    : '色ごとのSTL名と出力形式を指定してください。';
            }
        } else {
            const issues = Number(res.headers.get('X-CAD2STL-Geometry-Issues') || 0);
            previousUrl = URL.createObjectURL(await res.blob());
            download.href = previousUrl;
            download.download = 'cad2stl.zip';
            download.hidden = false;
            download.click();
            status.textContent = issues
                ? 'STLを生成しましたが入力幾何に問題があります。report.jsonとsurfaceCheckで確認してください。'
                : 'STLを生成しました。OpenFOAMのsurfaceCheckで品質を確認してください。';
        }
    } catch (err) {
        status.textContent = err.message;
    } finally {
        fileInput.disabled = false;
        inspectButton.disabled = !fileInput.files.length;
        convertButton.disabled = !inspection || Boolean(inspection.colors[inspection.missing_color_sentinel]);
    }
}

fileInput.onchange = () => {
    inspection = undefined;
    colorRows.replaceChildren();
    table.hidden = detail.hidden = convertButton.disabled = true;
    inspectButton.disabled = !fileInput.files.length;
    clearDownload();
    status.textContent = fileInput.files.length ? '「色を調べる」を押してください。' : 'ファイルを選択してください。';
};
inspectButton.onclick = () => run('inspect');
convertButton.onclick = () => run('convert');
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
                output_mode = request.get('output_mode', 'both')
                if output_mode not in ('separate', 'combined', 'both'):
                    raise ValueError('Output mode must be separate, combined or both')
                command += ['--output-mode', output_mode]
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
