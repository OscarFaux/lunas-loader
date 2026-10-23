# Validation — 2026-10-23

**90 automated checks passed** with Python 3.12 on Linux.

The suite covers guarded replacement/restoration, new-file removal, interruption recovery, ordinary-failure rollback, external-change protection, backup corruption checks, file links and unsafe ZIP paths, cross-process locking, target/resource conflicts, static extraction and staging composition. New checks cover persistent Unicode ZIP imports, remove/reimport, generic EXE discovery without execution, exclusion of a tool's sibling runtime DLLs from game deployment, configuration dependencies and read-only witnesses, AppData backup creation, and repeated Deploy/Purge transitions between selections.

Three GUI drawing checks use a recording canvas to verify the cyan/green text passes, dark gradient, generic controls, and non-overlapping controls at the minimum supported window size. They do not execute Tk against a real display or exercise native Windows events.

All five supplied archives were copied/extracted through the new import flow in an isolated temporary library. The supplied configurator's EXE was found with its sibling assets preserved; all four known file-mod targets were identified. `INPUT-INSPECTION.json` records these checks. No supplied mod EXE or script was run.

The final executable is a Windows x64 PE GUI image. Its PyInstaller CArchive is decoded after building; every compressed entry and Python code object in its PYZ is decoded, including the new application code. The custom lunar icon replaces the original bootloader icon resources. The bundle includes its own Windows Python 3.12, Tcl/Tk, dependent runtime DLLs and application modules, so users do not need Python installed. `BUILD-REPORT.json` records assembly details and excluded non-standard-library modules.

**Not tested here:** Windows startup, WM_DROPFILES behavior, native file dialogs, configuration UAC handoff, actual display rendering, real game-file deployment, anti-cheat acceptance and gameplay. No Windows/Wine runtime or clean game installation was available. The executable is assembled and structurally verified; it is not represented as Windows execution-tested.

Reproduce source tests with `python -m unittest discover -s tests -v`. Use `tools/Build-Windows.ps1` for a conventional Windows/PyInstaller rebuild, or the documented runtime-based assembler with the original runtime archive as a build input.

## Drop regression checks in 0.2.1

Seven tests check deferred UI delivery after the native callback returns, Unicode/multiple-file paths, preservation of 64-bit handle/result values, release of drop handles on read errors, callback exception containment, subclass removal at window destruction, and idempotent shutdown while retaining the native callback reference. Native Windows APIs are simulated in these tests; the user's original crash was not reproduced on Windows in this environment.

## Arsenal/order regression checks in 0.3

Seven further checks exercise dummy preparation and Deploy/Purge with unrelated external boot patches and a nonempty installer-state file, byte-for-byte preservation of those external files, bottom-row full-file precedence and persistent reordering, numbered patch deployment/companions above an external slot including re-deploy and Purge, configurator prefix staging, icon drag/release ordering, and click-without-drag behavior. These tests use disposable filesystem fixtures and a recording canvas. Live Arsenal and in-game behavior remain untested here.

An upgrade fixture also verifies that a pre-existing Arsenal patch restored from an older Luna deployment keeps its numbered slot; the new Luna patch is allocated a different slot.

## Manifest/options/image checks in 0.4

Sixteen additional tests cover selection filtering, variant persistence, separate archive slots for selected components, disabled-parent behavior, invalid-choice rejection without profile mutation, unsafe include rejection, wrapped/native icon paths, invalid-icon fallback, migration of existing mod records, thumbnail dimensions/alpha blending, EXE prompt content, manifest dialog controls/descriptions, bitmap caching and row substitution, decoder-error fallback, and standard-vs-EXE Configure routing without starting a process.

Recorded-canvas layouts for both popups were rendered for internal visual inspection. All five original ZIP imports are inspected separately. Actual Windows GDI+ decoding, live Tk modals, and EXE handoff still require Windows verification; these tests are not represented as live Windows tests.

## Helper capture and repair checks in 0.5

Fifteen checks cover the reported helper-file collision against a pre-existing game-side JSON, exclusion of both MikerPairs sidecars and previously saved helper records, copying saved target paths into baseline, dummy replacement with saved settings retained, failed rebuild preservation, link rejection, verified reset backups and own deployment record removal, Arsenal patch preservation, staging blocked until repair acknowledgement, missing Steam-restored paths, backup-write failure before deletion, interruption/restart, protection against changes during retry, failed protocol handoff/manual verification, exact Steam validation URI, and confirmation/cancellation of both UI actions, and target-set changes after review. They use fixture files, simulated deletion failures, and mocked Steam/UI calls; no game EXE was run or game file removed on a real installation.

Steam protocol and manual integrity-check references are recorded in README.md. Steam validation and reset on native Windows remain untested here. The UI accurately reports verification as requested and requires the user to confirm completion; checking restored paths is not a validation of vanilla hashes.

## Dummy directory lock regression in 0.5.1

Nine further fixture checks simulate denial of the exact dummy-to-snapshot rename, verify configuration launch without any root rename, preserve the directory identity through Refresh/Rebuild, preserve unsaved files in snapshots, stop EXE launch on individual file/backup failures, roll back partially changed staging, retain/report the snapshot if rollback also fails, replace staged hardlinks without writing to their external targets, and update both changed and unchanged read-only files. Unchanged hardlinks are also broken before configurators can write through them. These simulate Windows-style failures; actual Windows open-handle/ACL behavior and native EXE launch are still not exercised in this environment.
