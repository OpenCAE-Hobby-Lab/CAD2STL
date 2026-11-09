# CAD2STL

色付きSTEPの面を色ごとのSTLへ変換する、FreeCAD不要のプログラムです。Open CASCADE Technology（OCCT）を直接利用します。面数・色数は入力から取得し、境界名の既定値は `color_RRGGBB` です。

## Windows版の使い方

配布フォルダ全体を展開し、`CAD2STL.exe` をダブルクリックしてください。ブラウザにローカルWeb画面を開きます。FreeCAD・Pythonの別途インストールは不要です。停止はコンソールのCtrl+Cです。

1. STEPファイルを選び、「色を調べる」を押します。
2. 一覧の色見本、カラーコード、面数を確認し、各色のSTL名を編集します。初期値は `color_RRGGBB` です。
3. 色別の個別ファイル、または1つのSTLファイルを選んで変換します。個別出力では設定した名前に `.stl` が付き、単一出力では設定した名前が `all_regions.stl` 内の各 `solid` 名になります。

`CAD2STL.exe` と `_internal` フォルダは一緒に置いてください。Windows x64向けです。別PCでの実機確認は未実施です。

Webは127.0.0.1でのみ待ち受けます。外部への形状送信機能はありません。入力は25 MiBまで、変換は120秒までです。入力・結果・ログは `%LOCALAPPDATA%/CAD2STL/work/web-jobs/` に残ります。不要になったジョブフォルダは利用者が削除してください。

```powershell
.\CAD2STL.exe serve --port 8765
.\CAD2STL.exe inspect 'D:\CAD-local\model.step' --report 'D:\CAD-local\inspection.json'
.\CAD2STL.exe convert 'D:\CAD-local\model.step' --output 'D:\CAD-local\case01' --scale 0.001
```

実業務の入力・出力はGitリポジトリの外に置いてください。既存の出力フォルダやJSONは上書きしません。inspectの保存先の親フォルダは事前に作成してください。

`--map colors.json` で `example-colors.json` の形式の対応表を指定できます。省略すると検出した全色から名前を生成します。対応表にない色と未着色面は拒否します。部品色を面が継承し、個別の面色があればそれを優先します。色はsRGB各成分を8 bitへ丸めます。

CLIでは `--output-mode separate` で色別ファイル、`--output-mode combined` で単一ファイルを出力します。CLIで省略した場合は従来どおり両方を出力します（`--output-mode both`）。

## 出力と品質確認

- 選択した形式のASCII STL
- 面と色の対応、面積、三角形数、入力・出力ハッシュ、幾何検査結果を含む `report.json`
- OpenFOAM辞書の断片 `geometry.foam` と `refinementSurfaces.foam`

STEPの長さは読込時にmmへ正規化します。`--scale 0.001` はmへの換算です。STL自体に単位情報はありません。三角化設定は `--linear-deflection 0.05`（mm）、`--angular-deflection 0.2`（rad）で変更できます。

辞書断片は選択した出力形式に対応します。両方を出力した場合、辞書断片には色別STLを登録します。色別STLと `all_regions.stl` を同じgeometryへ同時登録すると形状が二重になります。単一出力の `report.json` では、各パッチの `file` と `sha256` が同じ `all_regions.stl` を参照します。

**生成成功はOpenFOAMでの品質合格を意味しません。** `report.json` の幾何問題を確認し、次のような表面検査を行ってください。

```bash
surfaceCheck -checkSelfIntersection all_regions.stl
```

終了コードに加え、自己交差、不正三角形、閉鎖性、領域名、法線をログで確認します。色別パッチ単体は開いた面で構いません。その後、利用するケースでsnappyHexMeshとcheckMeshを確認してください。自動修復・内部接触面の除去・流体側法線の推定は行いません。

## 入力形式

`.step` / `.stp` に対応します。Parasolid `.x_t` / `.x_b` の直接読込は未対応です。SpaceClaim / Solid Edge側で面色を保持したSTEPを書き出してください。FreeCAD非依存化によってParasolid読込機能が追加されるわけではありません。

## ソースから実行・ビルド

Python 3.12 x64を使います。実行用依存は `requirements.txt` に固定しています。

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe cad2stl.py
```

Windows配布フォルダは `Build-Windows.ps1` で作成できます。ビルド時はPyPIから依存を取得します。実行時のインターネット接続は不要です。`dist/CAD2STL/` をフォルダごとコピーします。第三者コンポーネントについては `THIRD_PARTY_NOTICES.md` を参照してください。

公開対象はプログラム、設定例、利用・ビルド手順です。CADデータ、変換結果、テスト、研究報告、エージェントの設定は含めません。
