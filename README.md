# CAD2STL

色付きSTEPの面を色ごとに分け，OpenFOAMの境界領域に対応するSTLへ変換します．面数・色数は入力から取得します．CLIとローカルWeb画面を使用できます．

## 必要な環境

WindowsとFreeCAD 1.0.2の同梱Pythonで動作を確認しています．追加のpipパッケージは不要です．他のFreeCAD版・OSについては未検証です．

## Web画面

このリポジトリのフォルダでPowerShellを開き，次を実行します．

```powershell
.\Start-Web.ps1
```

ブラウザで `http://127.0.0.1:8765` を開き，STEPを選択して「色を調べる」から変換を進めます．境界名の既定値は `color_RRGGBB` です．停止はターミナルでCtrl+Cです．

FreeCADの場所が異なる場合は指定します．

```powershell
.\Start-Web.ps1 -FreeCADPython 'D:\FreeCAD\bin\python.exe'
```

Web画面は127.0.0.1でのみ待ち受けます．アップロードは25 MiBまで，処理は120秒までです．ファイルを外部へ送信する機能はありません．入力と生成物はローカルの `work/web-jobs/` に保存されます．

## CLI

実業務の入力と出力は，Gitリポジトリの外に置いてください．以下は配置例です．

```powershell
$cadPython = 'C:\Program Files\FreeCAD 1.0\bin\python.exe'
& $cadPython experiments/freecad/cad2stl.py inspect 'D:\CAD2STL-local\input\model.step' --report 'D:\CAD2STL-local\inspection.json'
& $cadPython experiments/freecad/cad2stl.py convert 'D:\CAD2STL-local\input\model.step' --output 'D:\CAD2STL-local\output\case01' --scale 0.001
```

inspectの保存先の親フォルダは事前に作成してください．既存の出力フォルダやJSONは上書きしません．

境界名を指定する場合は，`experiments/freecad/example-colors.json` の形式で色対応表を作成します．

```powershell
& $cadPython experiments/freecad/cad2stl.py convert 'D:\CAD2STL-local\input\model.step' --map 'D:\CAD2STL-local\colors.json' --output 'D:\CAD2STL-local\output\case02' --scale 0.001 --linear-deflection 0.05 --angular-deflection 0.2
```

対応表を指定した場合，未定義色を含む入力は拒否します．省略した場合は検出した全色から名前を生成します．長さの近似誤差はmm，角度はradです．

## 出力と品質確認

- 色別のASCII STLと，全色を含む `all_regions.stl`
- 面と色の対応，面積，三角形数，入力・出力のハッシュ，幾何検査の問題を記録する `report.json`
- OpenFOAMの設定に組み込む `geometry.foam` と `refinementSurfaces.foam` の断片

STEPの長さは読込時にmmへ正規化され，指定倍率で出力されます．`--scale 0.001` はmへの換算です．STL自体に単位情報は含まれません．

色別STLと `all_regions.stl` を同時に同じgeometryへ登録しないでください．形状が二重になります．辞書断片は完全な計算ケースや物理境界条件ではありません．

**STLの生成成功は，OpenFOAMでの表面品質合格を意味しません．** `report.json` の幾何問題を確認し，次のような独立した検査を行ってください．

```bash
surfaceCheck -checkSelfIntersection all_regions.stl
```

終了コードだけでなく，自己交差，不正三角形，閉鎖性，領域名，法線の一貫性をログで確認します．色別パッチ単体は開いた面で構いません．その後，利用するケースでsnappyHexMeshとcheckMeshを確認してください．細分化だけで幾何不整合が解消するとは限りません．

## 制約

入力は `.step` / `.stp` です．Parasolidの `.x_t` / `.x_b` の直接読込は未対応です．面色を保持したSTEPの書出しは元CAD側で確認してください．

RGBは各成分8 bitへ丸めます．色の欠落を検出するため `#01FE02` を予約しており，この色を含む入力は拒否します．自動修復，内部接触面の削除，流体側の法線の推定は行いません．

## データをコミットしない運用

このリポジトリにはプログラムと利用手順のみを配置します．CAD，STL，出力ZIP，ログ，試験結果はGitの外で管理してください．`.gitignore` にはそれらの除外設定を含めていますが，`git add -f` で回避できるため，コミット前にステージ内容を確認してください．
