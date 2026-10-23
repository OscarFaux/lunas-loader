# Luna's Modloader 0.5.1 — source review package

This is the **original readable Python build source**, not a decompiler's reconstruction. Original source is available, so no recovered listing is presented as an authentic original. For inspection of the EXE itself, `review-evidence/*.dis.txt` contains recursive bytecode disassembly extracted from the shipped binary. Disassembly is not decompiled Python source.

All five application modules were recompiled and their marshal bytes matched the corresponding code embedded in the shipped 0.5.1 EXE exactly. See `review-evidence/SOURCE-TO-EXE.json` and the repeatable verification script. This check reads archive data and never launches the executable.

## Contents

| File | Review purpose |
| --- | --- |
| `gui.py` | Canvas UI, Windows drops, configuration prompts and background tasks |
| `luna_core.py` | ZIP library, EXE launch/capture, staging, ordering, deployment and Steam repair |
| `manager.py` | Payload parsing, guards, backup transactions and restoration |
| `mod_options.py` | Manifest options and selected-file mapping |
| `mod_images.py` | Bounded Windows/Tk thumbnail decoding |
| `BUILD.md` | Windows build steps and source-to-EXE verification |
| `tools/` | Independent build script, original assembler and inspection tool |
| `tests/` | 90 automated fixture checks |
| `review-evidence/` | Source/code comparison, EXE inventory, bytecode disassembly and build-input hashes |
| `docs/DEVELOPERS.md` | Mod author packaging/export-mode contract |
| `LICENSE.txt`, `LICENSES/`, `THIRD-PARTY-NOTICES.txt` | Original-code and runtime licensing |

There are no prebuilt executables, game binaries, mod payload ZIPs, virtual environments, user configurations or credentials in this ZIP. `luna.ico` is a build asset. `SHA256SUMS.txt` covers all included files except itself. The manifest/fixture tests use synthetic data; they do not run mod executables.

For a reviewer evaluating side effects, start with `Store.launch`, `Store.capture`, `Store.deploy`, `Store.reset_game_files` in `luna_core.py`, and `apply`/`transact` in `manager.py`. The real-game reset is user-confirmed; it backs up eligible files before removal and requests `steam://validate/553850`. Configurators are external programs explicitly launched by the user and are not OS-sandboxed by a dummy directory. Imports do not execute ZIP scripts.

This archive is prepared to support source review; it does not assert approval by Nexus Mods or replace their review process. The shipped EXE is unsigned. The 90 tests and structural/source-code checks were performed on Linux; native Windows startup, launch handoff and in-game behavior remain unverified here.
