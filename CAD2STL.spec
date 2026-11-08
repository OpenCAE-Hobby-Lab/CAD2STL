# Windows x64 portable folder. Build with Python 3.12 and requirements-build.txt.
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = collect_all('OCP', include_py_files=False)
datas += [('README.md', '.'), ('THIRD_PARTY_NOTICES.md', '.'), ('licenses', 'licenses')]
a = Analysis(['cad2stl.py'], pathex=[], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports + ['web_app'], hookspath=[],
             runtime_hooks=[], excludes=['tkinter', 'pytest', 'numpy', 'FreeCAD', 'FreeCADGui'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='CAD2STL',
          debug=False, bootloader_ignore_signals=False, strip=False,
          upx=False, console=True, disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='CAD2STL')
