#!/usr/bin/env python3
"""Unified Mods: declarative file packages, never executable ZIP contents."""
import argparse
import contextlib
import csv
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import struct
import subprocess
import sys
import tempfile
import zipfile

VERSION = 1
LIMIT = 512 * 1024 * 1024
BOOT_HASH = 'a2d3f616d2f28913aec508638d5fbc4edbae8cf9363b9575ab1ae5398187790f'
ARMOR_HASH = 'a63ac55c04673893df777e2fc1753bce3da12a9da92676ca3e5ac8f761650285'
BUILD_HASHES = {
    'bin/helldivers2.exe': '0acc07debe04714ae04281e1a66bd2eb9d3d85232953e32a93c8a3dd0874eabe',
    'data/game/game.dll': '6d1d4d3bc6fc84801d9f8f1b310e13a603d07409f3d9495d74b42e1d0bb1c08f',
    'data/game/dl_library.dl_typelib': '6cc78f1a8323d82cc319ba3f378b0dbf692f8ede3703cd0873f7e212ce11a18a',
}

class ModError(Exception):
    pass

def need(ok, message):
    if not ok:
        raise ModError(message)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def fingerprint(b):
    mid = len(b) // 2
    return str(len(b)) + ':' + (b[:32] + b[mid:mid+32] + b[-32:]).hex().upper()

def target_name(s):
    need(isinstance(s, str) and s and len(s) <= 220, 'Invalid game-relative target')
    p = PurePosixPath(s)
    need(not p.is_absolute() and p.as_posix() == s and len(p.parts) >= 2
         and p.parts[0] in ('data', 'mods', 'plugins', 'bin'),
         'Targets must be below data/, mods/, plugins/ or bin/: ' + s)
    for part in p.parts:
        need(re.fullmatch(r'[a-zA-Z0-9_][a-zA-Z0-9_. -]*', part)
             and not part.endswith(('.', ' ')) and part.split('.')[0].upper() not in
             {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(10)],*[f'LPT{i}' for i in range(10)]},
             'Unsafe target component: ' + part)
    need(p.parts[0] != 'bin' or (len(p.parts) == 2 and p.suffix.lower() == '.dll'),
         'Only DLL mod files can be deployed below bin/')
    return s


def file_bytes(path):
    return path.read_bytes() if path.exists() else None


def optional_hash(data):
    return sha(data) if data is not None else None


def apply_bytes(path, data):
    if data is None:
        path.unlink(missing_ok=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(path, data)

def digest(s):
    need(isinstance(s, str) and re.fullmatch('[0-9a-f]{64}', s), 'Invalid SHA-256')
    return s

def read_zip(path):
    z = zipfile.ZipFile(path)
    try:
        names = set()
        total = 0
        for i in z.infolist():
            p = PurePosixPath(i.filename)
            need(not p.is_absolute() and '..' not in p.parts and '\\' not in i.filename
                 and ':' not in i.filename, 'Unsafe archive path: ' + i.filename)
            key = i.filename.casefold()
            need(key not in names, 'Duplicate archive path: ' + i.filename)
            names.add(key)
            need((i.external_attr >> 16) & 0o170000 != 0o120000, 'Archive links are unsupported')
            total += i.file_size
            need(total <= LIMIT and len(names) <= 10000, 'Archive exceeds size/member limit')
        return z
    except BaseException:
        z.close()
        raise

def validate_operation(op, payload):
    target_name(op['target'])
    need(sha(payload) == digest(op['sha256']), 'Payload SHA-256 mismatch')
    need(op.get('before_sha256') or op.get('before_fingerprints') or op.get('before_missing') is True, 'Missing original-file guards')
    for h in op.get('before_sha256', []):
        digest(h)
    for f in op.get('before_fingerprints', []):
        need(re.fullmatch(r'[0-9]+:[0-9A-F]{192}', f), 'Invalid legacy fingerprint')
    for p, h in op.get('build_sha256', {}).items():
        need(p in BUILD_HASHES or target_name(p), 'Unsupported build guard path: ' + p)
        digest(h)
    inferred = resource_claims(op['target'], payload)
    op['resource_claims'] = sorted(set(op.get('resource_claims', [])) | set(inferred))
    if 'patch_priority' in op:
        need(type(op['patch_priority']) is int and op['patch_priority'] >= 0 and
             re.fullmatch(r'data/[0-9a-fA-F]+\.patch_'+str(op['patch_priority'])+r'(?:\.(?:stream|gpu_resources))?',op['target']), 'Invalid ordered patch target')
    for claim in op.get('resource_claims', []):
        need(isinstance(claim, str) and claim and len(claim) < 200, 'Invalid resource claim')

def legacy_payload(b):
    need(len(b) >= 184 and struct.unpack_from('<I', b)[0] == 0xf0000011,
         'Not a supported Stingray archive')
    types, files = struct.unpack_from('<II', b, 4)
    need(types == 1 and files == 1, 'Expected a single HD2FM1 resource')
    off = struct.unpack_from('<Q', b, 120)[0]
    need(off >= 184 and off + 18 <= len(b), 'Invalid resource offset')
    length, kind = struct.unpack_from('<II', b, off)
    body = b[off+8:off+8+length]
    need(len(body) == length and kind == 2 and body[:6] == b'HD2FM1', 'Unsupported payload resource')
    n = struct.unpack_from('<I', body, 6)[0]
    need(0 < n <= 65536 and n+10 <= len(body), 'Invalid payload header size')
    header = {}
    for line in body[10:10+n].decode('utf-8').splitlines():
        k, v = line.split('=', 1)
        header.setdefault(k, []).append(v)
    def one(k):
        need(len(header.get(k, [])) == 1, 'Missing/duplicate header: ' + k)
        return header[k][0]
    payload = body[10+n:]
    need(len(payload) == int(one('size')), 'Payload size mismatch')
    need(fingerprint(payload) in header.get('mod', []), 'Legacy payload fingerprint mismatch')
    op = dict(name=one('name'), target=target_name(one('target')), sha256=sha(payload),
              before_fingerprints=header.get('stock', []), before_sha256=[], build_sha256={})
    validate_operation(op, payload)
    return op, payload

def import_archive(path, selected_members=None):
    with read_zip(path) as z:
        names = z.namelist()
        if selected_members is not None:
            chosen=set(selected_members);names=[n for n in names if n in chosen]
        if 'unified-mod.json' in names:
            spec = json.loads(z.read('unified-mod.json'))
            need(spec['schema'] == 1 and isinstance(spec['id'], str) and spec['id'], 'Unsupported manifest')
            out = []
            for op in spec['files']:
                op = dict(op, name=spec['name'], mod_id=spec['id'])
                payload = z.read(op.pop('payload'))
                validate_operation(op, payload)
                out.append((op, payload))
            need(out, 'Empty mod')
            return out
        boot_candidates = [n for n in names if n.endswith('/9ba626afa44a3aa3.patch_0')]
        for n in boot_candidates:
            boot = z.read(n)
            if sha(boot) != '53e9d78b318ddb15a5a252d5a50429f6d644f24c9446e3a7209924ec80d5c2c2':
                continue
            # Reviewed SG97 1.1 adapter: decode one literal; never interpret Lua.
            match = re.search(rb'local CANDIDATE = "((?:\\[0-9]{3})+)"', boot)
            need(match is not None, 'SG97 literal payload is missing')
            values = [int(v) for v in re.findall(rb'\\([0-9]{3})', match[1])]
            need(values and max(values) <= 255, 'Invalid SG97 literal byte')
            payload = bytes(values)
            return [(dict(name='SG97 projectile modification 1.1', mod_id='sg97-1.1',
                          target='data/game/generated_projectile_settings.dl_bin', sha256=sha(payload),
                          baseline_required=True), payload)]
        patches = [n for n in names if re.fullmatch(r'Install/b5b0c0ffee5b5b[0-9a-f]{2}\.patch_0', n)]
        if patches:
            need(sha(z.read('Install/9ba626afa44a3aa3.patch_0')) == BOOT_HASH,
                 'Unknown boot installer; adapter review required')
            allowed = {'Install/9ba626afa44a3aa3.patch_0', *patches}
            for n in names:
                if n.startswith('Install/') and not n.endswith('/') and n not in allowed:
                    need(n.endswith(('.stream', '.gpu_resources')) and z.getinfo(n).file_size == 0,
                         'Unrecognised Install component: ' + n)
            out = []
            for n in sorted(patches):
                op, payload = legacy_payload(z.read(n))
                op['mod_id'] = 'legacy-' + sha(op['target'].encode())[:16]
                out.append((op, payload))
            return out
        armor = [n for n in names if n.endswith('/Extras/Source/PackageData/CosmeticsPayload.bin')]
        need(len(armor) == 1, 'No compatible declarative mod found; executable-only mods need an adapter')
        payload = z.read(armor[0])
        need(sha(payload) == ARMOR_HASH, 'Unknown cosmetics version; adapter review required')
        return [(dict(name='NoMoFOMO + Hidden Content Unlocker 0.1.1', mod_id='nofomo-26088801',
                      target='data/game/generated_customization_armor_sets.dl_bin', sha256=ARMOR_HASH,
                      before_sha256=['4739b50c6e6c105c59b705eef1213e3080caabef7c6d918496c335906732d9db'],
                      build_sha256=BUILD_HASHES), payload)]

def bind_operation(op, payload, game_root):
    op = dict(op)
    if op.pop('baseline_required', False):
        need(game_root, 'This mod supplies no original/build guards. Select a clean game folder or pass build --game-root to bind its output to your local baseline.')
        root = Path(game_root).absolute()
        need(root.is_dir() and root == root.resolve(), 'Use the real baseline folder')
        closed()
        before = safe_path(root, target_name(op['target'])).read_bytes()
        op['before_sha256'] = [sha(before)]
        op['build_sha256'] = {rel:sha(safe_path(root, rel).read_bytes()) for rel in BUILD_HASHES}
        print('Binding previously unguarded payload to local files:', op['target'])
        print('NOTE: exact baseline binding protects later deployment; it does not prove this mod supports the selected game build.')
    validate_operation(op, payload)
    return op


def build(inputs, output, game_root=None):
    operations, blobs, targets, claims = [], {}, {}, {}
    for path in inputs:
        print('Importing:', path, flush=True)
        for op, payload in import_archive(path):
            op = bind_operation(op, payload, game_root)
            key = op['target'].casefold()
            if key in targets:
                previous = targets[key]
                need(all(previous.get(k) == op.get(k) for k in ('sha256','before_sha256','before_fingerprints','before_missing','build_sha256')),
                     'Target conflict: ' + op['target'] + '. Select one mod or configure them sequentially in staging.')
                print('Deduplicating identical shared file:', op['target'])
                continue
            targets[key] = op
            for claim in op.get('resource_claims', []):
                need(claim not in claims, 'Resource conflict: ' + claim + ' in ' + op['target'])
                claims[claim] = op['target']
            op['payload'] = 'payloads/' + op['sha256']
            blobs[op['payload']] = payload
            operations.append(op)
    need(operations, 'No mods selected')
    output = Path(output).absolute()
    need(not output.exists(), 'Output already exists; choose a new filename')
    if Path(__file__).is_file():
        source = Path(__file__).read_bytes()
    else:
        with zipfile.ZipFile(Path(__file__).parent) as own_archive:
            source = own_archive.read('__main__.py')
    manifest = dict(schema=1, name='Unified Mods', files=sorted(operations, key=lambda x:x['target']))
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=output.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('__main__.py', source)
            z.writestr('package.json', json.dumps(manifest, indent=2))
            for n, b in sorted(blobs.items()):
                z.writestr(n, b)
        os.replace(tmp, output)
    finally:
        Path(tmp).unlink(missing_ok=True)
    print('Built:', output, '\nFiles:', len(operations))

def package(path):
    with read_zip(path) as z:
        spec = json.loads(z.read('package.json'))
        need(spec['schema'] == 1 and spec['files'], 'Unsupported/empty bundle')
        result, seen, claims = [], set(), {}
        for op in spec['files']:
            b = z.read(op['payload'])
            validate_operation(op, b)
            need(op['target'].casefold() not in seen, 'Duplicate target in bundle')
            seen.add(op['target'].casefold())
            for claim in op.get('resource_claims', []):
                previous=claims.get(claim)
                need(previous is None or (op.get('patch_priority') is not None and previous.get('patch_priority') is not None and op['patch_priority']!=previous['patch_priority']), 'Resource conflict in bundle: ' + claim)
                claims[claim]=op
            result.append((op, b))
        return result

def safe_path(root, relative):
    p = PurePosixPath(relative)
    need(not p.is_absolute() and '..' not in p.parts and '\\' not in relative and ':' not in relative,
         'Unsafe relative path')
    current = root
    for part in p.parts:
        current = current / part
        need(not current.is_symlink() and not (hasattr(current, 'is_junction') and current.is_junction()),
             'Links/junctions are unsupported: ' + str(current))
    need(current.resolve().is_relative_to(root.resolve()), 'Path escapes game root')
    return current

def closed():
    if os.name == 'nt':
        r = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], check=True, capture_output=True, text=True, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        need(not any(row and row[0].casefold() == 'helldivers2.exe' for row in csv.reader(io.StringIO(r.stdout))),
             'Close Helldivers 2 completely before proceeding')
    else:
        # Linux fixture support; also detect a Wine-hosted game where /proc exposes its name.
        for p in Path('/proc').glob('[0-9]*/comm'):
            try:
                need(not p.read_text().strip().casefold().startswith('helldivers2'), 'Close the game first')
            except (FileNotFoundError, PermissionError):
                pass

def write_atomic(path, b):
    fd, tmp = tempfile.mkstemp(prefix='.unified-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(b)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)

def save_json(path, value):
    write_atomic(path, json.dumps(value, indent=2).encode())

@contextlib.contextmanager
def locked(root):
    state = safe_path(root, '.unifiedmods')
    state.mkdir(exist_ok=True)
    lock = safe_path(root, '.unifiedmods/lock')
    with lock.open('a+b') as f:
        if f.tell() == 0:
            f.write(b'0'); f.flush()
        f.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            raise ModError('Another manager operation is running') from e
        yield state

def legacy_check(root):
    data = safe_path(root, 'data')
    for prefix in ['9ba626afa44a3aa3', 'b5b0c0ffee5b5b']:
        need(not any(data.glob(prefix + '*.patch_*')), 'Remove legacy boot/payload patches using the old manager first')
    st = safe_path(root, 'HD2FileMods.state')
    need(not st.exists() or not st.read_text().strip(), 'Restore old file mods using their original installer first')

def records(root, state):
    s = state / 'installed.json'
    if not s.exists():
        return []
    info = json.loads(s.read_text())
    need(info['schema'] == 1 and info['root'] == str(root), 'Installed state belongs to another game root')
    return info['files']

def original(root, r):
    target_name(r['target'])
    if r['original_sha256'] is None:
        return None
    b = safe_path(root, '.unifiedmods/backups/' + digest(r['original_sha256'])).read_bytes()
    need(sha(b) == r['original_sha256'], 'Original backup is damaged')
    return b

def recover(root, state):
    j = state / 'pending.json'
    if not j.exists():
        print('No interrupted transaction.'); return
    info = json.loads(j.read_text())
    need(info['root'] == str(root), 'Journal belongs to another root')
    todo = []
    for r in info['files']:
        p = safe_path(root, target_name(r['target']))
        b = (safe_path(root, '.unifiedmods/transactions/' + digest(r['before'])).read_bytes()
             if r['before'] is not None else None)
        need(optional_hash(b) == r['before'], 'Transaction backup damaged')
        current = optional_hash(file_bytes(p))
        need(current in [r['before'], r['after']], 'File changed externally; recovery stopped: ' + r['target'])
        todo.append((p, b, current, r['before']))
    for p, b, current, before in reversed(todo):
        closed()
        need(optional_hash(file_bytes(p)) in [before, current], 'File changed during recovery')
        apply_bytes(p, b)
    if info['previous_state'] is None:
        (state / 'installed.json').unlink(missing_ok=True)
    else:
        save_json(state / 'installed.json', info['previous_state'])
    j.unlink()
    print('Interrupted transaction rolled back. Retry your intended operation.')

def transact(root, state, changes, next_records):
    txdir = safe_path(root, '.unifiedmods/transactions')
    txdir.mkdir(exist_ok=True)
    journal = dict(root=str(root), files=[], previous_state=(
        json.loads((state/'installed.json').read_text()) if (state/'installed.json').exists() else None))
    for p, before, after in changes:
        h = optional_hash(before)
        if before is not None:
            stash = safe_path(root, '.unifiedmods/transactions/' + h)
            write_atomic(stash, before)
        journal['files'].append(dict(target=p.relative_to(root).as_posix(), before=h, after=optional_hash(after)))
    save_json(state / 'pending.json', journal)
    try:
        for p, before, after in changes:
            closed()
            need(optional_hash(file_bytes(p)) == optional_hash(before), 'File changed after preflight: ' + str(p))
            print('Writing:', p.relative_to(root), flush=True)
            apply_bytes(p, after)
            need(optional_hash(file_bytes(p)) == optional_hash(after), 'Post-write verification failed')
        save_json(state / 'installed.json', dict(schema=1, root=str(root), files=next_records))
        (state / 'pending.json').unlink()
    except Exception:
        print('Operation interrupted; attempting rollback.', file=sys.stderr)
        recover(root, state)
        raise

def apply(root, bundle, action, mod_id=None, coexist=False):
    root = Path(root).absolute()
    need(root.is_dir() and root == root.resolve(), 'Use the real absolute game folder; root links are unsupported')
    closed()
    with locked(root) as state:
        if action == 'recover':
            recover(root, state); return
        need(not (state/'pending.json').exists(), 'Interrupted transaction found. Run recover first.')
        if not coexist:
            legacy_check(root)
        old = records(root, state)
        for r in old:
            p = safe_path(root, target_name(r['target']))
            need(optional_hash(file_bytes(p)) == digest(r['installed_sha256']), 'Installed file changed; refusing overwrite: ' + r['target'])
            original(root, r)
        if action in ('restore', 'remove'):
            need(old, 'Nothing is installed by this manager')
            selected = old if action == 'restore' else [r for r in old if r.get('mod_id') == mod_id]
            need(selected, 'No installed mod matches that ID. Run status to list installed IDs.')
            changes = [(safe_path(root, r['target']), safe_path(root, r['target']).read_bytes(), original(root, r)) for r in selected]
            remaining = [r for r in old if r not in selected]
            transact(root, state, changes, remaining)
            print('Restored selected files. Backups retained.'); return
        ops = package(bundle)
        need(not old, 'A bundle is already installed. Restore it before deploying a different selection.')
        changes, new = [], []
        for op, payload in ops:
            for rel, h in op.get('build_sha256', {}).items():
                need(sha(safe_path(root, rel).read_bytes()) == h, 'Unsupported game build: ' + rel)
            p = safe_path(root, op['target'])
            before = file_bytes(p)
            need((before is None and op.get('before_missing') is True) or
                 (before is not None and (sha(before) in op.get('before_sha256', []) or fingerprint(before) in op.get('before_fingerprints', []))),
                 'Unknown original/game update/other mod: ' + op['target'])
            changes.append((p, before, payload))
            new.append(dict(target=op['target'], original_sha256=optional_hash(before), installed_sha256=sha(payload), name=op['name'], mod_id=op.get('mod_id', op['name'])))
            print('Ready:', op['name'], '->', op['target'], flush=True)
        if action == 'check':
            print('Preflight passed. No game files changed.'); return
        backupdir = safe_path(root, '.unifiedmods/backups')
        backupdir.mkdir(exist_ok=True)
        for p, before, after in changes:
            if before is None:
                continue
            backup = safe_path(root, '.unifiedmods/backups/' + sha(before))
            if backup.exists():
                need(sha(backup.read_bytes()) == sha(before), 'Backup corruption')
            else:
                write_atomic(backup, before)
        transact(root, state, changes, new)
        print('Deployment verified. Launch the game normally.')

def resource_claims(target, data):
    if not re.search(r'\.patch_[0-9]+$', target):
        return []
    need(len(data) >= 72 and struct.unpack_from('<I', data)[0] == 0xf0000011,
         'Unrecognised game patch archive; a developer-reviewed manifest is required: ' + target)
    types, files = struct.unpack_from('<II', data, 4)
    start = 72 + 32 * types
    need(types <= 100000 and files <= 100000 and start + 80 * files <= len(data), 'Damaged archive resource table')
    result = []
    for i in range(files):
        resource_id, resource_type = struct.unpack_from('<QQ', data, start + 80*i)
        result.append(f'stingray:{resource_id:016x}:{resource_type:016x}')
    need(len(result) == len(set(result)), 'Duplicate resource in game patch archive')
    return result


def pack_files(source, game_root, output, prefix='', name='Imported file mod'):
    source, root, output = Path(source).absolute(), Path(game_root).absolute(), Path(output).absolute()
    need(source.is_dir() and source == source.resolve(), 'Use a real exported-files folder')
    need(root.is_dir() and root == root.resolve(), 'Use the real game folder path')
    need(not output.exists(), 'Output already exists')
    need(not output.is_relative_to(source), 'Save the output ZIP outside the input folder')
    need(not source.is_relative_to(root) and not root.is_relative_to(source), 'Export and game folders must be separate')
    need(prefix == '' or (prefix in ('data', 'mods', 'plugins', 'bin')),
         'Prefix must be data, mods, plugins, bin or empty')
    closed()
    with locked(root) as state:
        need(not records(root, state) and not (state/'pending.json').exists(), 'Restore installed bundle before importing a baseline')
        legacy_check(root)
        guards = {rel:sha(safe_path(root, rel).read_bytes()) for rel in BUILD_HASHES}
        operations, blobs, total = [], {}, 0
        for p in sorted(source.rglob('*')):
            need(not p.is_symlink() and not (hasattr(p, 'is_junction') and p.is_junction()), 'Export links are unsupported')
            if p.is_dir():
                continue
            relative = p.relative_to(source).as_posix()
            target = target_name((prefix + '/' if prefix else '') + relative)
            data = p.read_bytes()
            total += len(data)
            need(total <= LIMIT and len(operations) < 10000, 'Export exceeds import limits')
            before = file_bytes(safe_path(root, target))
            if before == data:
                continue
            blob = 'payloads/' + sha(data)
            op = dict(target=target, payload=blob, sha256=sha(data), build_sha256=guards,
                      resource_claims=resource_claims(target, data))
            if before is None:
                op['before_missing'] = True
            else:
                op['before_sha256'] = [sha(before)]
            validate_operation(op, data)
            operations.append(op)
            blobs[blob] = data
        need(operations, 'No changed/new files found')
        for rel, h in guards.items():
            need(sha(safe_path(root, rel).read_bytes()) == h, 'Build changed during import')
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=output.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('unified-mod.json', json.dumps(dict(schema=1, id='files-'+sha(
                json.dumps(operations,sort_keys=True).encode())[:16], name=name, files=operations), indent=2))
            for rel, data in blobs.items():
                z.writestr(rel, data)
        os.replace(tmp, output)
    finally:
        Path(tmp).unlink(missing_ok=True)
    print('Imported file tree:', output, '\nFiles:', len(operations))


STAGE_INPUTS = [
    'data/game/generated_customization_armor_sets.dl_bin',
    'data/game/generated_customization_passive_bonuses.dl_bin',
    'data/game/dl_library.dl_typelib',
    'data/game/game.dll',
]
MARKER = b'Unified Mods staging marker. Not an executable. Do not launch.\r\n'

def stage_create(game_root, destination, bases, extra_inputs=()):
    root, dest = Path(game_root).absolute(), Path(destination).absolute()
    need(root.is_dir() and root == root.resolve(), 'Use the real game folder path')
    need(not dest.exists() and dest == dest.resolve(), 'Stage must be a new folder with no linked parents')
    need(not dest.is_relative_to(root) and not root.is_relative_to(dest), 'Stage and game must be separate folders')
    closed()
    with locked(root) as state:
        need(not records(root, state) and not (state/'pending.json').exists(), 'Restore/recover installed bundle before staging')
        legacy_check(root)
        base_ops, seen = [], set()
        for path in bases:
            for op, data in import_archive(path):
                op = bind_operation(op, data, root)
                need(op['target'].casefold() not in seen, 'Base target conflict: ' + op['target'])
                seen.add(op['target'].casefold())
                base_ops.append((op, data))
        inputs = sorted(set(STAGE_INPUTS + [target_name(p) for p in extra_inputs] + [op['target'] for op, _ in base_ops]))
        before = {rel:file_bytes(safe_path(root, rel)) for rel in inputs}
        need(all(before[rel] is not None for rel in STAGE_INPUTS), 'Required configurator input is missing')
        # Bind captured output to the exact source installation build.
        guards = {rel:sha(safe_path(root, rel).read_bytes()) for rel in BUILD_HASHES}
        for op, data in base_ops:
            original_data = before[op['target']]
            need((original_data is None and op.get('before_missing') is True) or
                 (original_data is not None and (sha(original_data) in op.get('before_sha256', []) or
                 fingerprint(original_data) in op.get('before_fingerprints', []))),
                 'Base mod does not match source file: ' + op['target'])
            for rel, h in op.get('build_sha256', {}).items():
                need(guards[rel] == h, 'Base mod does not support this game build: ' + rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        temporary = Path(tempfile.mkdtemp(prefix='.unified-stage-', dir=dest.parent))
        try:
            for rel, data in before.items():
                if data is None:
                    continue
                out = temporary/rel
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(data)
            for op, data in base_ops:
                out = temporary/op['target']
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(data)
            (temporary/'bin').mkdir()
            (temporary/'bin/helldivers2.exe').write_bytes(MARKER)
            # Source file copies are independent regular files, never links to the live install.
            meta = temporary/'.unified-stage'
            meta.mkdir()
            (meta/'manifest.json').write_text(json.dumps(dict(
                schema=1, source_root=str(root), inputs={rel:optional_hash(data) for rel,data in before.items()},
                build_sha256=guards, bases=[op['name'] for op,_ in base_ops]), indent=2))
            for rel, data in before.items():
                if data is None:
                    continue
                backup = meta/'original'/rel
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_bytes(data)
            for rel, data in before.items():
                need(optional_hash(file_bytes(safe_path(root, rel))) == optional_hash(data), 'Source changed while staging')
            for rel, h in guards.items():
                need(sha(safe_path(root, rel).read_bytes()) == h, 'Build changed while staging')
            os.rename(temporary, dest)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    print('Staging game created:', dest)
    print('In a fresh ArmorWorkbench copy: Settings > Choose install folder > select this STAGE folder.')
    print('Configure and Install changes there; close Workbench; then run stage-capture.')
    print('This folder redirects output by selection. It is not an OS security sandbox.')

def stage_capture(stage, output, name):
    stage, output = Path(stage).absolute(), Path(output).absolute()
    need(stage == stage.resolve(), 'Use the real staging folder')
    need(not output.exists(), 'Output already exists; choose a new filename')
    meta = safe_path(stage, '.unified-stage/manifest.json')
    spec = json.loads(meta.read_text())
    need(spec['schema'] == 1, 'Unsupported stage manifest')
    need(safe_path(stage, 'bin/helldivers2.exe').read_bytes() == MARKER, 'Staging marker changed')
    need(set(spec['build_sha256']) == set(BUILD_HASHES), 'Stage build guards missing')
    for rel, h in spec['build_sha256'].items():
        need(rel in BUILD_HASHES, 'Invalid build guard')
        digest(h)
    operations, blobs = [], {}
    known = set(spec['inputs'])
    for p in safe_path(stage, 'data/game').iterdir():
        need(p.is_file() and not p.is_symlink(), 'Unexpected nested/link content in staged data/game')
        if p.suffix == '.dl_bin':
            need(p.relative_to(stage).as_posix() in known, 'Untracked generated file; explicit adapter needed: ' + p.name)
    for rel, h in spec['inputs'].items():
        need(rel in STAGE_INPUTS or target_name(rel), 'Unsupported staged input')
        original_data = (safe_path(stage, '.unified-stage/original/' + rel).read_bytes()
                         if h is not None else None)
        need(optional_hash(original_data) == h, 'Staged original backup changed')
        current = file_bytes(safe_path(stage, rel))
        if optional_hash(current) == h:
            continue
        need(current is not None, 'Deleted staged inputs are unsupported: ' + rel)
        need(rel not in ['data/game/game.dll', 'data/game/dl_library.dl_typelib'], 'Configurator changed a read-only build input: ' + rel)
        target_name(rel)
        blob = 'payloads/' + sha(current)
        blobs[blob] = current
        op = dict(target=rel, payload=blob, sha256=sha(current),
                  build_sha256=spec['build_sha256'])
        if h is None:
            op['before_missing'] = True
        else:
            op['before_sha256'] = [digest(h)]
        validate_operation(op, current)
        operations.append(op)
    need(operations, 'No changed .dl_bin files found. Use Install changes in the staged game folder first.')
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=output.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('unified-mod.json', json.dumps(dict(schema=1, id='captured-'+sha(
                json.dumps(operations,sort_keys=True).encode())[:16], name=name, files=operations), indent=2))
            for rel, data in blobs.items():
                z.writestr(rel, data)
        os.replace(tmp, output)
    finally:
        Path(tmp).unlink(missing_ok=True)
    print('Captured:', output, '\nChanged files:', len(operations))
    if spec.get('bases'):
        print('Already contains base mods:', ', '.join(spec['bases']))
        print('Do not separately add those base ZIPs to the same bundle.')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Unified Mods: one runnable bundle, guarded offline file deployment.')
    sub = parser.add_subparsers(dest='command', required=True)
    b = sub.add_parser('build', help='Build a single .pyz from selected mod ZIPs')
    b.add_argument('archives', nargs='+'); b.add_argument('-o', '--output', required=True)
    b.add_argument('--game-root', help='Baseline for a reviewed legacy mod lacking original-file guards')
    i = sub.add_parser('inspect', help='Inspect ZIP compatibility or a built bundle')
    i.add_argument('archives', nargs='*')
    for name in ['check', 'deploy', 'restore', 'remove', 'recover', 'status']:
        p = sub.add_parser(name)
        p.add_argument('--game-root', required=True)
        p.add_argument('--coexist', action='store_true', help='Preserve external manager patches; skip the legacy installer blanket check')
        if name in ['check', 'deploy']:
            p.add_argument('--bundle')
        if name == 'remove':
            p.add_argument('--mod-id', required=True)
    st = sub.add_parser('stage-create', help='Make a copied game folder for ArmorWorkbench output')
    st.add_argument('--game-root', required=True)
    st.add_argument('--stage', required=True)
    st.add_argument('--input', action='append', default=[], help='Additional game-relative file to copy for a configurator')
    st.add_argument('--base', action='append', default=[], help='Base mod ZIP already included in staged output')
    cap = sub.add_parser('stage-capture', help='Turn configured staged files into a compatible mod ZIP')
    cap.add_argument('--stage', required=True)
    cap.add_argument('-o', '--output', required=True)
    cap.add_argument('--name', default='Configured ArmorWorkbench')
    files = sub.add_parser('pack-files', help='Import an exported file tree with an explicit game-relative mapping')
    files.add_argument('--source', required=True)
    files.add_argument('--game-root', required=True)
    files.add_argument('--prefix', default='')
    files.add_argument('--name', default='Imported file mod')
    files.add_argument('-o', '--output', required=True)
    args = parser.parse_args(argv)
    own = Path(sys.argv[0]).absolute()
    if args.command == 'pack-files':
        pack_files(args.source, args.game_root, args.output, args.prefix, args.name)
    elif args.command == 'stage-create':
        stage_create(args.game_root, args.stage, args.base, args.input)
    elif args.command == 'stage-capture':
        stage_capture(args.stage, args.output, args.name)
    elif args.command == 'build':
        build(args.archives, args.output, args.game_root)
    elif args.command == 'inspect':
        for path in args.archives or [own]:
            with read_zip(path) as z:
                is_bundle = 'package.json' in z.namelist()
            result = package(path) if is_bundle else import_archive(path)
            print('\n' + str(path))
            for op, payload in result:
                print(' ', op['name'], '\n   Target:', op['target'], '\n   Bytes:', len(payload), '\n   SHA256:', op['sha256'])
                if op.get('baseline_required'):
                    print('   Requires local baseline binding at build time; game-build compatibility is unverified.')
                if op.get('before_fingerprints'):
                    print('   Guard: legacy sampled fingerprint (weaker than full SHA-256)')
    elif args.command == 'status':
        root = Path(args.game_root).absolute()
        need(root.is_dir(), 'Game folder does not exist')
        with locked(root) as state:
            print('Recovery pending:', (state/'pending.json').exists())
            for r in records(root, state):
                p = safe_path(root, target_name(r['target']))
                print(r.get('mod_id', r.get('name')), '->', r['target'], 'OK' if p.exists() and sha(p.read_bytes()) == r['installed_sha256'] else 'CHANGED/MISSING')
    else:
        apply(args.game_root, getattr(args, 'bundle', None) or own, args.command, getattr(args, 'mod_id', None),getattr(args,'coexist',False))

if __name__ == '__main__':
    try:
        main()
    except (ModError, OSError, ValueError, KeyError, struct.error, zipfile.BadZipFile, subprocess.SubprocessError) as e:
        print('ERROR:', e, file=sys.stderr)
        sys.exit(1)
