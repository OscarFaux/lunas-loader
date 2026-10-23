# Luna's Modloader — 0.5.1 preview

## Run

Extract the distribution and launch **Luna's Modloader.exe**. This is a single-file Windows x64 application: no Python installation is required. Windows extracts its bundled runtime to a temporary folder while it runs. The executable is unsigned.

The application window is named **Luna's Modloader**. Its background is a dark pink-to-blue gradient; the application's text is cyan with thin green outlines. Windows-owned file pickers and title-bar text follow your Windows settings.

Luna can run alongside Arsenal. It manages only the mods enabled in its own list and does not require Arsenal’s unrelated patches to be removed.

## Use

1. Click **Choose game** once and select the real Helldivers 2 folder containing `bin` and `data`.
2. Drag one or more **ZIP files** onto the window. **Add ZIPs** also works. Each complete archive is copied and extracted after path/link/size checks under `%LOCALAPPDATA%\lunas_loader`.
3. Enable the mods you want with the square beside each mod. Drag the **E / M icon** beside a mod to reorder it: **top loads first, bottom loads last**. Release at the cyan insertion line. Order is saved immediately; click Deploy to apply it to the game. For a file-based mod, no configuration step is necessary.
4. Click the row’s **Configure** button or double-click its name/icon. A standard mod opens its manifest-defined checkboxes and single-choice variants. Save those choices before Deploy. An EXE-based mod first opens an on-screen directory prompt showing the full dummy path; click **Copy path** or **Copy and launch**, then paste it into the mod’s directory picker.
5. Close the configuration EXE when finished. The loader captures changed output files from the dummy area. While an EXE is open, importing/deployment is blocked.
6. Click **Deploy**. The loader combines enabled file payloads and saved configured outputs into an internal single package, verifies it against clean copies, saves verified backups, then deploys to the real game with the game closed.
7. Click **Purge** to restore the files the loader replaced and remove files it added. Imported ZIPs, extracted tools, presets, configured outputs and backups remain available.

Disable or remove a mod and click Deploy to update the game selection. Deploy first preflights the new selection, then restores the old deployment and installs the new one. If the new installation fails normally, it attempts to put the previous selection back. If you disable every mod, use Purge.

Standard ZIP options are generated from their manifest rather than hard-coded for individual mods. Each mod’s own EXE still owns its executable configuration options. If a package has more than one EXE, select its row and use **Choose EXE** to cycle through the candidates; the activity area shows the selected path. Double-click runs that selected EXE. The main EXE is chosen automatically by folder depth unless the author declares one in the native manifest.

## The dummy directory

The fixed copyable path is:

```
%LOCALAPPDATA%\lunas_loader\staging\dummy_game
```

The staging folder is created automatically. Choosing the real game prepares independent copies of its `bin/helldivers2.exe`, top-level `data/game` resource tables, type library and DLLs, plus targets required by enabled file mods. This version uses a real executable **copy as a validation marker**, rather than an empty EXE, so configuration tools checking build hashes can inspect it. Never launch the copied game. This is a partial game-shaped working directory, not a complete game installation or a running dummy process.

When a configurator opens, enabled rows above it and that row’s own outputs are applied only to those copies. Rows below it are excluded until their later turn. Refresh dummy and Deploy prepare the entire enabled list in visible order. Changed final outputs are captured after the configuration process closes. Existing dummy contents are copied into `snapshots` before staging is updated; configuration tool data beside the extracted EXE is preserved. **Refresh dummy** rebuilds copied inputs and selected outputs without deploying anything to the real game.

A staged directory is not an OS security sandbox. An EXE can still auto-detect the real Steam installation or use its own stored paths. The loader cannot automatically redirect every program's filesystem operations. Explicitly choose the displayed dummy directory if the mod asks where to install. A process that starts another background helper and exits early may require the helper to finish before the output is captured; this preview tracks the EXE it launches, not every possible descendant process.

**Rebuild dummy** clears/replaces the contents of the dummy directory after its replacement has been successfully assembled, while keeping the top-level folder in place. It discards unsaved tool output in that directory, preserves saved EXE outputs and options, and does not change the real game. Refresh dummy preserves the previous contents in `snapshots`; Rebuild dummy uses a temporary rollback copy, removed after success. Close configurators before either operation. Old snapshots are retained.

Version 0.5.1 addresses the reported `[WinError 5] Access is denied: dummy_game → snapshots/...` failure before EXE configuration starts. Staging no longer renames or deletes its top-level directory. Files are backed up and verified, then individual changed files are replaced atomically. A file-level lock still stops preparation, reports the affected path and attempts to restore the old contents; the EXE is not started. If rollback is also blocked, the error names the preserved backup. Close any other mod configurators/editors using the dummy files before retrying. No elevation or permissions changes to the real game are needed for this fix. The folder name remains copyable and unchanged.

Known resource backup/state helpers (`.original`, `.bak`, `.backup`, `.MikerPairs.original`, `.MikerPairs.json` appended to a resource name under `data/game`) remain private to staging instead of being deployed. Previously captured helpers are also excluded without deleting their saved records. This addresses the reported `Unknown original/game update/other mod` conflict on `generated_stratagem_settings.dl_bin.MikerPairs.json`; genuine game-resource conflicts still stop deployment. Saved configured target paths now participate in baseline copying.

## Reset game files through Steam

Click **Reset game files** to review the exact paths first. This includes `bin/helldivers2.exe`, the game DLL/type-library build witnesses, and existing base resource files targeted by imported/configured mods or Luna's deployment record. It excludes newly added mod files and numbered Arsenal patches. Reset is a repair action: another manager's direct edits to the selected base files will also be replaced.

After confirmation, Luna verifies backup copies under `%LOCALAPPDATA%\lunas_loader\backups\steam-reset`, saves the previous mod/deployment state there, removes the listed files, clears saved EXE outputs, and opens `steam://validate/553850`. Imported ZIPs, manifest options, icons and order are retained. Numbered patches and unrelated mod files remain in place; this is not a complete uninstall. Steam verification may replace additional modified base files.

Wait until **Steam finishes verifying/downloading**, then click **Rebuild dummy**, confirm completion and reconfigure EXE mods before deploying. Luna checks that removed paths have reappeared; it cannot independently verify Steam's completion or that the restored bytes are vanilla. It blocks staging/deployment while repair is pending. If a reset is interrupted, click Reset game files again to resume from its durable backup journal; changed files are protected. If Steam does not open, use Steam → Helldivers 2 → Properties → Installed Files → Verify integrity of game files, then Rebuild dummy. Clicking Reset game files again while waiting retries only the Steam request.

Protocol reference: https://developer.valvesoftware.com/wiki/Steam_browser_protocol . Manual verification: https://help.steampowered.com/en/faqs/view/0C48-FCBD-DA71-93EB . Steam handoff is a request, not an assertion that repair has completed.

## Backups and Purge

Before live replacement, the loader writes verified original bytes plus a plan under `backups` in its application folder. The deployment backend also keeps the authoritative transaction backups and journal in the real game's `.unifiedmods` folder. A copy of that metadata is retained under AppData after deployment/restoration.

Purge restores exact originals only if the currently installed files still match what the loader wrote. It refuses unknown changes from another tool or a game update. Newly created files are removed, and empty directories may remain. Do not delete game-side `.unifiedmods` until you have purged successfully. AppData copies are retained for recovery; automatic reconstruction from a deleted game-side state folder is not implemented.

Use **Recover** after a process termination or interrupted file transaction. It rolls back the pending transaction and protects files changed externally. Arsenal’s existing patch files and installer-state files do not block Refresh dummy or EXE configuration. Purge restores/removes only files recorded in Luna’s own deployment journal; it does not purge Arsenal’s library or unrelated game patches.

## Supported packages and limits

- Native `unified-mod.json` ZIP packages.
- The supplied Stay Put / Jump Pack HD2FM1 packages and NoFOMO payload version.
- The supplied SG97 projectile 1.1 package; its previously unguarded payload is bound to your selected local baseline before deployment.
- Ordinary file trees under `data/`, `mods/`, `plugins/`, or DLLs directly under `bin/`.
- Bare game patch files, or patch files in conventional `Install` / `Addon` folders, excluding unknown boot-script installers.
- EXE configurator packages with their complete sibling runtime/assets preserved. Unknown EXE packages are treated as tools; their sibling DLLs are not automatically deployed as game plugins. Declare any static payloads in a native manifest.

Whole-file outputs are applied from top to bottom; the last enabled row writing a target wins. This selects a complete replacement rather than merging individual binary edits. Recognised patch archives and their stream/GPU companions receive increasing `.patch_N` slots after the highest existing external slot. Arsenal’s existing archives are not renamed or overwritten. Resource overlap between explicitly ordered Luna patch archives is allowed and logged; unordered resource conflicts are still rejected.

Configured outputs can include an earlier mod's changes when the configuration tool understands that baseline. Such an output records the base mod's exact identity/hash. If you disable, replace, or move that required base below its dependent configuration, the loader stops rather than silently stripping or retaining unknown changes. Select the configured mod, use **Reset config**, and configure it again against your intended selection. Reset config removes its saved output from the active profile; archived bytes and the EXE's own presets remain.

The loader does not inject into a running process or provide an anti-cheat bypass. Deploying a plugin DLL as a file does not invent a game loading mechanism for it. Unknown boot scripts need adapters so their later side effects can be included in backup/restoration. Tools needing additional assets, root-level configuration, changes to game executables, a running game, or custom installation APIs may need an integration.

## Storage

All library state lives under `%LOCALAPPDATA%\lunas_loader`:

| Folder | Contents |
| --- | --- |
| `mods/<archive SHA-256>` | Original ZIP, extracted files, mod record and captured outputs |
| `staging/baseline` | Clean copied inputs, reconstructed from this loader's originals if currently deployed |
| `staging/dummy_game` | Current copyable configurator target |
| `snapshots` | Prior dummy working directories |
| `packages` | Internally built combined runnable packages |
| `backups` | Verified pre-deploy originals and copied transaction metadata |

Removing a mod from the list keeps its folder and presets. Dropping the same ZIP again restores its record. Snapshot and package retention is conservative in this preview and can consume disk space; after a successful Purge and with all configurators closed, obsolete snapshots/packages can be removed manually. Keep the library's active records and any backups you still need.

Normal Windows permissions apply. Run the loader normally so Explorer drag-and-drop works. Windows may block drops from a normal Explorer window into an elevated program. If the game folder is not writable, deployment reports the access failure without bypassing permissions.

## Verification

Backend fixture tests cover library persistence, import/extraction, configuration capture/dependencies, pre-deploy backups, repeated Deploy/Purge and the earlier transactional protections. The assembled Windows executable is checked structurally and all embedded Python code archives are decoded during validation. Windows execution, native drag-and-drop and in-game behavior have not been tested in this Linux environment.

Source and `tools/Build-Windows.ps1` are included for a normal Windows/PyInstaller rebuild. The supplied EXE was assembled using the redistributable Python/Tcl/Tk runtime and PyInstaller bootloader from your uploaded standalone application, with its application code and other third-party modules excluded. See `THIRD-PARTY-NOTICES.txt` and `docs/BUILD-REPORT.json`.

## Prior drop-handler repair (retained in 0.3.0)

The Windows file-drop bridge now uses SetWindowSubclass/DefSubclassProc instead of replacing Tk's window procedure directly. The native callback only reads paths, releases the drop handle and enqueues a plain event. A normal GUI timer delivers that event; no Tk API or importer runs inside the native callback. Subclass shutdown and pointer-width argument declarations are explicit.

Replace the previous EXE with this build. Existing `%LOCALAPPDATA%\lunas_loader` files, imported ZIPs, presets and game-side backups are retained. A native fault writes diagnostic information to `native-crash.log` in that application folder; Python/UI errors go to `loader.log`. Both logs may contain local filenames. The repair was exercised with simulated Windows API calls and structurally verified in the rebuilt EXE; Windows execution remains untested here.

The 0.2.1 heading and window title are **Luna's Modloader**; the old secondary tagline has been removed. The executable is now named **Luna's Modloader.exe**. Your existing `lunas_loader` storage path is unchanged.

## Arsenal coexistence and order

The former blanket “Remove legacy boot/payload patches” check is not used by the GUI’s dummy preparation or deployment path. Genuine target/build mismatches, changed Luna-owned files, damaged backups and configuration dependencies are still checked. A copied baseline can include edits already present from another manager; Purge returns Luna’s replaced files to that prior state, not necessarily factory stock.

Arsenal’s own library and order are not imported or changed. The visible order controls Luna’s rows. For optional raw patch imports, Luna allocates increasing free patch numbers above external files and excludes its own existing deployment from that calculation, so repeated Deploy does not continually increase the numbers. Stream and GPU sidecars keep the same assigned number.

Finish changing/deploying Arsenal before deploying Luna. If Arsenal later removes or changes Luna-owned files, Luna reports that actual state difference rather than silently overwriting it. Both tools can affect the same game resources, so semantic compatibility and in-game precedence still need game testing. Unknown boot-script packages still require a reviewed adapter when imported into Luna; merely having another manager’s boot/payload files in the game folder no longer blocks configuration.

## Standard mod configuration and pictures in 0.4

Every row has a Configure button. HD2/Arsenal-style manifest v1 `Options` are independent checkboxes; each option’s `SubOptions` is a single-choice group. Option and variant names/descriptions come from the ZIP. The selected `Include` folders/files, plus assets outside all option folders, determine the actual staged/deployed output. Selections survive restarts. Multiple selected components using the same archive name receive separate patch slots and keep their sidecars, so one component does not silently discard another.

If a package has no declared options, the dialog explains that its normal contents are used; the loader cannot invent options for a flat model-replacement archive. The EXE prompt appears before launching, includes Copy path / Copy and launch / Cancel, and does not run the configurator if canceled.

A manifest’s `IconPath` supplies the thumbnail beside its mod name. Native `unified-mod.json` packages may use `icon`. Paths are local to that mod’s root; remote or escaping paths are ignored. PNG, JPEG, GIF and BMP are supported through Windows’ built-in image support where decodable, with native Tk fallback for PNG/GIF. Missing, oversized, invalid or unsupported images keep the E/M fallback. The picture remains the drag handle for load order. Your app styling is retained in both configuration dialogs.
