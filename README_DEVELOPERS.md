# Luna's Modloader — Developer README

Compatibility contract for **0.5.1, Windows x64**.

Prefer a ZIP with a root `unified-mod.json` and final deployable payload bytes. Configuration stays in your EXE; the loader owns installation, backups and restoration. The GUI does not contain mod-specific setup questions.

## Required change: loader mode for EXE installers

**Disable your mod's clean-install integrity gates and its requirement for a private clean-game backup when running in Luna loader/export mode.** The selected dummy directory can already contain earlier enabled mods. Do not reject it solely because a resource differs from vanilla, another mod is detected, your installation marker is absent, or your own `.original`/clean backup cannot be found. Luna handles file backups, deployment tracking and restoration for the files it deploys.

This change must be implemented by the mod author. Luna does not rewrite your EXE or automatically bypass its checks. An unchanged EXE that demands a private clean backup or refuses modified input can still fail.

| Existing installer behavior | Required behavior in Luna loader mode |
| --- | --- |
| Reject any non-vanilla resource checksum or detected previous mod | Accept the selected dummy's current resources as inputs, including compatible earlier mods. |
| Require the installer's clean backup, installation marker or previous installation | Generate output without requiring private backup/state files. |
| Restore a private vanilla backup before patching | Edit/export against the staged current input; restoring vanilla would erase earlier mods. |
| Write directly to an auto-detected Steam installation | Honor the explicitly selected dummy directory for all output. |
| Run private uninstall/restore logic during configuration | Produce final files; leave live-game Deploy/Purge to Luna. |

Keep actual file-format validation, bounds checks and checks for formats/builds your editor genuinely supports. Luna's ownership/hash checks do not prove that a binary editor understands a new game version. Remove clean-install policy gates in loader mode while retaining validation needed to edit correctly. If your editor cannot compose with a particular earlier change, report the resource and incompatibility instead of producing invalid output.

Your normal standalone installation mode can keep its original behavior. Implement a switch such as `--loader-mode`, or an explicit export-mode toggle. The switch name is your API, not a built-in Luna feature: Luna passes declared arguments, and your EXE must understand them.

## EXE packaging and entry point

Place `unified-mod.json` at the ZIP root. Put the complete tool distribution under a folder such as `Configurator/`, and include any declared `profile.png`. Native manifests must not be hidden inside an extra wrapping folder. A standard `manifest.json` has a separate one-wrapper allowance, described below.

```json
{
  "schema": 1,
  "id": "org.example.mod",
  "name": "Example mod 1.0",
  "configuration": {
    "executable": "Configurator/Example.exe",
    "arguments": ["--loader-mode", "--game-root", "{dummy}", "--output-directory", "{dummy}"]
  },
  "files": [
    {
      "target": "data/game/example.dl_bin",
      "payload": "payload/example.bin",
      "sha256": "REPLACE_WITH_64_LOWERCASE_HEX_DIGITS",
      "before_sha256": ["REPLACE_WITH_ORIGINAL_SHA256"]
    }
  ]
}
```

Replace the example hashes with actual SHA-256 values. Omit `configuration` for a file-only package. An EXE-only package can omit the native manifest entirely: ZIP the full distribution, and the loader discovers the shallowest primary EXE. A native configuration-only manifest may use an empty `files` list with a declared EXE. Multiple discovered EXEs can be cycled in the GUI. Provide a single public configuration entry point when possible.

Implement the sample switches in your EXE or replace them with switches it supports. For a GUI-only directory picker use `"arguments": []`; the user can paste the directory shown by Luna. A complete configuration-only manifest is:

```json
{
  "schema": 1,
  "id": "org.example.configurator",
  "name": "Example configurator",
  "icon": "profile.png",
  "configuration": {
    "executable": "Configurator/Example.exe",
    "arguments": ["--loader-mode", "--game-root", "{dummy}"]
  },
  "files": []
}
```

`configuration.arguments` is an argument array, never a shell command. Placeholders are `{dummy}` for the staged working game, `{mod}` for the extracted mod directory, and `{game}` for the real installation. Prefer `{dummy}`: `{game}` is provided for explicit read-only tools, not permission to write the real game outside the loader. Arguments are only passed when the user explicitly double-clicks to run the EXE. Import alone never executes it.

The Configure button also launches through this same explicit directory prompt. Do not add shell quotation marks around `{dummy}` inside an argument element: paths containing spaces are passed as one argument. The EXE's working directory is its own directory. Finish all output writes and child helpers before that launched process exits. Exit with zero on success; a nonzero exit does not commit a configuration. Luna tracks the process it launches rather than every possible background descendant.

Support a selected directory and an export/install-to-copy mode. Avoid silently switching to an auto-detected Steam installation. Persist presets beside your EXE or in your own workspace. Keep helper files together in the ZIP. Unknown EXE distributions are treated as configuration tools, so sibling runtime DLLs are not guessed to be game plugins; declare static payloads in the manifest. Do not require code injection just to generate data files when a file export is possible.

The dummy contains independent real copies of version witnesses so tools can inspect supported builds. It does not emulate game execution. It is a partial installation containing the game EXE, top-level game resource tables/DLLs and required mod targets, not a full game install. Tools needing additional original assets or runtime APIs need a loader integration; do not bundle copyrighted game inputs to work around this. An export report/native manifest is preferable to guessing undocumented outputs.

## File operations

`files[].target` is below `data`, `mods`, `plugins`, or a DLL directly in `bin`. Supply `before_sha256` for replacements or `before_missing: true` for additions. `build_sha256` may map read-only game witness paths to expected SHA-256 values. `bin/helldivers2.exe` can be a witness, not a replacement. Full hashes are preferred; sampled `before_fingerprints` are supported only for legacy imports. The payload hash checks final bytes, not author trust or gameplay safety.

Targets must be normalized relative paths, at most 220 characters, with portable ASCII components beginning with a letter/digit/underscore and continuing with letters, digits, underscores, spaces, dots or hyphens. Use forward slashes in native manifests. SHA-256 values are lowercase 64-character hexadecimal strings. On Windows, `(Get-FileHash .\payload\example.bin -Algorithm SHA256).Hash.ToLowerInvariant()` calculates a payload digest. Never ship placeholder hashes. Native manifest guards remain enforced even when the EXE uses loader mode.

Keep targets normalized, relative and portable on Windows. ZIP paths cannot escape the archive, be symlinks, duplicate another path with different casing, use device names or trailing spaces/dots. Uncompressed archive totals are bounded to 512 MiB/10,000 members. Larger tool distributions need an explicit limit/packaging change. No arbitrary installer scripts execute during import.

Native payloads are complete file replacements. Within the GUI’s visible load order, later complete outputs override earlier outputs at the same target. Standalone unordered bundle construction still rejects ambiguous overlaps. Recognised Stingray resource claims are inferred from patch tables and checked across archive names. Optional opaque `resource_claims` provide extra exclusive IDs. Mod `id` is not a version/dependency solver.

## Configuration capture and composition

Before launching a tool, the loader prepares the enabled base outputs in the shared dummy area and hashes the staged files. After that EXE closes successfully, it captures changed or added files under supported target directories. Build witnesses (`bin/helldivers2.exe`, `data/game/game.dll`, `data/game/dl_library.dl_typelib`) must remain unchanged, and deleted inputs are rejected. Root-level output files and outputs saved elsewhere are not captured automatically; export/install into the displayed dummy directory at `%LOCALAPPDATA%\lunas_loader\staging\dummy_game`.

The captured output is compared with the original clean baseline for restoration, not with a previously modded live game file. If it includes an earlier mod's bytes at the same target, that earlier owner/hash becomes a dependency. Removing/replacing that base invalidates the configuration and requires reconfiguration. This is controlled sequential composition, not a general semantic merger.

Luna does not bypass the EXE's remaining validation. Implement the loader mode described above so clean-install and private-backup checks do not block this workflow. Unknown boots that mutate extra files on a later game exit need a reviewed data-only adapter so all side effects can be backed up and restored.

## Load order and external managers

The persisted `mods` list is the load order; drag moves update that list atomically. Assembly processes each enabled row’s static payloads and captured configuration together, top first and bottom last. The old configuration timestamp is retained only as historical metadata, not as execution priority. Configurators preview only the prefix ending at their own row, so they cannot accidentally bake a lower-priority/later row into an earlier result. Dependencies are validated against earlier owners.

Raw patch imports retain their archive identifier and bytes but receive free numeric suffixes after existing non-Luna patches. Companion `.stream` and `.gpu_resources` files share that suffix. Internally generated `patch_priority` metadata must match the assigned filename. The transaction reader accepts overlapping resource claims only when both archives have distinct explicit numeric priorities. Authors should not hard-code deployment slots; the GUI chooses them. Whole-file non-archive replacements remain complete replacements, not a semantic merge.

The application invokes the transaction backend in coexistence mode. It skips the historical blanket restriction on other managers’ boot/payload filenames and their state file; it still validates the precise files that Luna will write, and restoration only touches its recorded ownership. 

Luna backs up the pre-Luna state, which can already include Arsenal/other changes; it is not a guaranteed factory-vanilla backup. Finish external-manager deployment before configuring/deploying Luna. Do not change Arsenal's library, state or patch slots from your configurator. Hash/ownership checks do not establish semantic compatibility between mods.

## Standard manifest options and thumbnails

Example mod-root layout: `manifest.json`, `profile.png`, `Common/`, `Variants/Blue/`, and `Variants/Red/`.

```json
{
  "Version": 1,
  "Guid": "cf4cb994-0d29-4c33-985d-a5450d299d7f",
  "Name": "Example model replacement",
  "Description": "A configurable replacement",
  "IconPath": "profile.png",
  "Options": [
    {
      "Name": "Model",
      "Description": "Enable the replacement",
      "Include": ["Common"],
      "SubOptions": [
        {"Name": "Blue", "Description": "Blue material", "Include": ["Variants/Blue"]},
        {"Name": "Red", "Description": "Red material", "Include": ["Variants/Red"]}
      ]
    }
  ]
}
```

The parser supports root or one-folder-wrapped manifests. Checkboxes default on, with the first variant selected; subsequent saved choices take priority. A disabled parent includes none of its folders/variants. Paths normalize Windows separators and reject absolute or parent-traversal includes. Common files outside every option include remain available. Selected folders can contain direct patch files or game-relative `data/`, `mods/`, `plugins/` trees. Labels and descriptions are shown in the configuration dialog. Per-option `Image` preview artwork is not rendered by this release; the mod-level `IconPath` is the row thumbnail.

Every Include path must exist and is relative to the manifest directory. Put a game-relative tree inside each Include folder: for example `Variants/Blue/data/<archive>.patch_0` maps to `data/<archive>.patch_0`. A selected single-file include uses its parent as the mapping base. This supports the v1 fields shown here, not every extension another manager might implement. Avoid combining option folders and an explicit native files list unless that exact combination has been tested.

The mod-manager v1 schema reference is https://github.com/teutinsa/Helldivers2ModManager/blob/master/mod_manifest_v1-schema.json . The native format may instead declare `"icon": "assets/profile.png"` at the root of `unified-mod.json`. Thumbnail paths are checked relative to the appropriate mod root and are never executed or fetched remotely. An unusable thumbnail falls back to the generic icon without preventing mod import/deployment.

PNG is recommended; Windows codecs can also handle common JPEG/GIF/BMP images. The mod image replaces M/E beside the name and remains a draggable load-order handle. If both manifest formats exist, the standard manifest supplies options/thumbnail while root `unified-mod.json` declares the configurator/static payloads.

Images have a 16 MiB file limit and a 32-megapixel dimension limit. Thumbnail size and aspect ratio are handled by the loader; an unusable image falls back to M/E.

## Configurator helper files and repair

Store reusable configurator state beside your EXE or in your own application-data directory. Game-resource backup/state sidecars under `data/game` with suffixes `.original`, `.bak`, `.backup`, `.MikerPairs.original` or `.MikerPairs.json` are not deployable outputs. These rules apply only when the suffix follows a `.dl_bin`, `.dl_typelib` or `.dll` resource filename; other mod configuration JSON files remain eligible. This also filters old saved helper outputs. Build witnesses including `bin/helldivers2.exe` remain read-only during EXE capture.

Rebuild dummy refreshes only Luna's staged working contents and reapplies saved outputs. Reset game files is a separate, user-confirmed Steam repair: it backs up and removes eligible base game files, clears saved EXE outputs, and requests validation for app 553850. It preserves imported archives and manifest selections. Do not rely on game-side backup helper files surviving a reset; configure again after Steam verification. Steam validation does not manage arbitrary mod patches or prove their mutual compatibility.

In 0.5.1 the dummy folder itself remains in place; its contents are backed up and updated without a top-level rename. Individual file locks still stop preparation before an EXE starts. Do not hold the dummy open in background tools after configuration completes. A staged directory is not a security sandbox: honoring the selected path is your configurator's responsibility.

## Developer publication checklist

- Package your own tool/runtime files and final payloads, not a game installation, personal presets or local backups.
- Test first-time configuration without your own clean backup or installation marker.
- Test with a compatible earlier mod already present in the staged input; verify its changes survive your export.
- Test the dummy path with spaces, configuration twice, options/variants, dependency reordering and Deploy → Purge. Confirm that configuration writes nothing to the real game before Deploy.
- Test Reset config → configure again, and reconfiguration after Steam repair. Check image display and every Include path.
- Publish supported game versions and known incompatibilities. Imported ZIPs are identified by archive SHA-256; a manifest id is not a semantic version/update solver.
- Root `unified-mod.json` must contain real hashes where payloads are declared. The manifest can be configuration-only with `files: []`; the EXE must implement every declared argument.
- Unknown scripts, runtime injection requirements and undocumented extra side effects need an integration; merely importing a ZIP does not execute its scripts or invent a loading mechanism.

For integration reports, include Luna/mod versions, options, load order and the exact error. Diagnostics are in `%LOCALAPPDATA%\lunas_loader\loader.log` and, for native faults, `native-crash.log`; logs can contain local filenames.

The 0.5.1 executable passes 90 automated Linux fixture checks, including simulated Windows lock failures. Native Windows startup, configurator handoff and in-game behavior still require live validation; this document does not claim universal compatibility.
