# Build and inspect Luna's Modloader 0.5.1

## Recommended: independent Windows build

Requirements: Windows x64, CPython 3.12 x64 with Tcl/Tk and the `py` launcher, and internet access to install the build tool. The application itself uses the standard library; PyInstaller is a build dependency. Close Helldivers 2 before running the fixture suite. Tests exercise links: enable Windows Developer Mode for unprivileged symlink creation if required by your Windows configuration.

1. Extract this source ZIP and open PowerShell in its `Lunas-Modloader-0.5.1-Source-Review` directory.
2. Confirm Python/Tk are present:

   ```powershell
   py -3.12 -c "import struct, tkinter; print(struct.calcsize('P') * 8); print(tkinter.TkVersion)"
   ```

   The architecture result must be `64`. Install the Python Tcl/Tk component if the import fails.

3. Build:

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\Build-Windows.ps1
   ```

   This execution-policy override applies only to that PowerShell process. Read the script before running it. It creates `.build-venv`, installs `pyinstaller==6.20.0`, runs the tests and bundles the app. The script does not download or execute any mod, and does not need the ArmorWorkbench archive. Pip downloads PyInstaller and its build dependencies.

4. The result is **`dist\Luna's Modloader.exe`**. It is unsigned. Launch it normally to test the UI; a game folder is needed only when testing staging/deployment. Keep licenses/notices with the redistributed app.

The review copy of the PowerShell build script adds explicit license/data inclusion, optimization level 1, Tk hidden imports, and `--noupx`. These are packaging improvements; the five application source modules match the shipped EXE. Build logs/dependency versions are retained locally in `build-dependencies.txt` and `build-environment.txt`.

For manual inspection without packaging:

```powershell
py -3.12 -m unittest discover -s tests -v
py -3.12 gui.py
```

The build command and switches follow PyInstaller's usage documentation: https://pyinstaller.org/en/v6.20.0/usage.html . Python can be obtained from https://www.python.org/downloads/windows/ . Build Windows executables on Windows; the fixture checks recorded here were run on Linux, not through a Windows cross-compiler.

## Verify the source against the distributed EXE

The EXE is not included in this source-only ZIP. Use the separately supplied 0.5.1 EXE, then run:

```powershell
py -3.12 .\tools\verify_source_against_exe.py "C:\path\Lunas-Modloader-0.5.1.exe" --output .\fresh-review-evidence
```

This tool reads the PyInstaller archive without starting the EXE. It compiles `gui.py`, `luna_core.py`, `manager.py`, `mod_options.py` and `mod_images.py` using the same filenames and optimization setting as the shipped build, then compares their serialized Python code objects byte for byte. It also writes recursive disassembly and an archive inventory. Use CPython 3.12; the recorded inspection used 3.12.14. If another Python patch release changes compiler/marshal output, investigate a mismatch rather than assuming equivalent behavior. The verifier's archive helpers specifically target the shipped runtime-based layout; an independent normal PyInstaller rebuild has different entry names and is not this verifier's target.

`review-evidence/SOURCE-TO-EXE.json` records a successful match for all five application modules, plus the exact shipped EXE SHA-256. This demonstrates application source/code correspondence for that artifact. It does not audit the bundled Python runtime, native DLLs, bootloader, or prove that the program is safe or universally compatible. Their entries are listed in `archive-inventory.json` for further review.

## Original runtime-based assembly route

The shipped 0.5.1 EXE was assembled from a PyInstaller bootloader and redistributable CPython/Tcl/Tk runtime from the separately supplied `ArmorWorkbench-0.10.1-Standalone.zip`; its original application modules were excluded. The original assembly script is included unchanged as `tools/build_standalone.py`. It requires CPython 3.12 with Tk available and that external archive:

```powershell
py -3.12 .\tools\build_standalone.py "C:\path\ArmorWorkbench-0.10.1-Standalone.zip" --output ".\dist\Luna's Modloader.exe"
```

The archive's SHA-256 is recorded in `review-evidence/BUILD-INPUTS.json`. It is not included or needed for the recommended independent build. Inspect `THIRD-PARTY-NOTICES.txt` and `LICENSES` for runtime licensing.

Neither build route promises a bit-for-bit identical EXE: Python patch versions, bootloader/runtime bytes, packaging inputs and embedded documentation can differ. Documentation and licensing text were updated after the shipped 0.5.1 build; application code is unchanged. A normal independent PyInstaller build is useful for reviewing the source without trusting the prebuilt runtime.
