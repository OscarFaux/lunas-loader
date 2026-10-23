$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root
py -3.12 -m venv .build-venv
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is required only for building from source.' }
$Python = Join-Path $Root '.build-venv\Scripts\python.exe'
& $Python -m pip install 'pyinstaller==6.20.0'
if ($LASTEXITCODE -ne 0) { throw 'Build dependencies failed.' }
& $Python -c "import struct, tkinter; assert struct.calcsize('P') == 8, 'Use Python x64'; print('Tk', tkinter.TkVersion)"
if ($LASTEXITCODE -ne 0) { throw 'Python x64 with Tcl/Tk is required.' }
& $Python -m pip freeze --all | Set-Content -Encoding UTF8 'build-dependencies.txt'
& $Python -c "import sys, platform; print(sys.version); print(platform.platform())" | Set-Content -Encoding UTF8 'build-environment.txt'
& $Python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
& $Python -m PyInstaller --noconfirm --clean --onefile --windowed --noupx --optimize 1 --name "Luna's Modloader" --hidden-import tkinter.font --hidden-import tkinter.messagebox --icon luna.ico --add-data 'manager.py:.' --add-data 'luna.ico:.' --add-data 'README.md:.' --add-data 'docs:docs' --add-data 'LICENSE.txt:.' --add-data 'LICENSES:LICENSES' --add-data 'THIRD-PARTY-NOTICES.txt:.' gui.py
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
Write-Host "Created: $(Join-Path $Root "dist\Luna's Modloader.exe")"
