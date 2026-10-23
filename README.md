# Luna's Modloader 0.5.1

Standalone Windows x64 mod manager for Helldivers 2. No Python installation is needed.

## Start

1. Extract this ZIP and run **Luna's Modloader.exe**.
2. Choose the real game folder containing `bin` and `data`.
3. Drop mod ZIP files onto the window, or use Add ZIPs.
4. Enable your mods. Drag their picture/M/E handle to order them: top first, bottom last.
5. Use Configure or double-click a mod. Standard manifests show checkboxes/variants. For an EXE, copy the directory from Luna's prompt and paste it into the mod's game-directory picker. Close the configurator when finished.
6. Close the game, then click Deploy. Use Purge to restore Luna's recorded changes.

Your library, imported archives, staged files, saved configurations and backups are stored under `%LOCALAPPDATA%\lunas_loader`. Replacing the manager EXE does not erase that data. Only import and run mod programs you intend to use; import alone does not run them.

## Configurator compatibility

EXE installers must support writing to the selected staged directory. Some existing tools reject already modified input or demand their own original backup. Their author must add a compatible loader/export mode; Luna cannot automatically disable checks inside an EXE. Give authors **README_DEVELOPERS.md**, which documents the exact packaging and output requirements.

The dummy is a partial working copy, not a running game or full installation. Saved complete-file outputs use the visible order; later complete replacements override earlier ones. Composition requires a configurator that preserves the earlier input changes. Unknown boot/script installers may need an integration.

## Repair controls

- **Refresh dummy:** rebuild staged inputs/outputs, preserving the previous contents in snapshots.
- **Rebuild dummy:** discard unsaved staging changes and refresh the contents, retaining saved EXE outputs/options. Close other configurators first.
- **Reset config:** clear the selected mod's saved output so it can be configured again.
- **Recover:** recover an interrupted Luna file transaction.
- **Reset game files:** review the listed base files, back them up, remove them, clear saved EXE outputs and request Steam verification. Other managers' direct edits to those base files may also be replaced. Wait for Steam to finish, then use Rebuild dummy and reconfigure EXE mods. Luna cannot detect Steam completion.

Luna leaves unrelated Arsenal patches/state in place and manages its own recorded deployment. Finish Arsenal changes before configuring/deploying Luna. Changes to Luna-owned files by another program or a game update still require attention; do not delete the game's `.unifiedmods` backup/journal folder while Luna mods are deployed.

## Release status

This distribution contains the 0.5.1 EXE and updated author documentation. The executable is unchanged from the 0.5.1 lock-fix build. It is unsigned. It passes 90 automated Linux fixture checks, including simulated Windows lock failures, and its Windows executable structure has been checked. Native Windows startup, drag-and-drop, EXE handoff and in-game compatibility still require live validation. This upload package is not a claim of production certification or universal mod compatibility.

Version 0.5.1 keeps the dummy folder in place while refreshing its contents, addressing the reported dummy-to-snapshot access-denied error. A genuinely locked file still stops configuration with its path and attempts rollback. Close programs using that file and retry.

`SHA256SUMS.txt` lists the release-file hashes. Developer guidance is in `README_DEVELOPERS.md`. Retain `LICENSE.txt`, `THIRD-PARTY-NOTICES.txt` and `LICENSES` when redistributing.
