"""Persistent mod library and generic configurator staging for Luna's Modloader."""
import copy
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tempfile
import uuid
import zipfile
import manager as m
import mod_options as opts

TITLE = "Luna's Modloader"
BUILD = '0.5.1'


def configurator_private_file(target):
    """Known game-resource backup/state sidecars belong to the configurator."""
    return bool(re.fullmatch(r'data/game/[^/]+\.(?:dl_bin|dl_typelib|dll)\.(?:original|bak|backup|MikerPairs\.(?:json|original))',target,re.I))


def repairable_game_file(target):
    return target == 'bin/helldivers2.exe' or bool(re.fullmatch(r'data/game/[a-zA-Z0-9_][a-zA-Z0-9_. -]*\.(?:dl_bin|dl_typelib|dll)',target))


def request_steam_verification():
    m.need(os.name=='nt','Open Steam → Helldivers 2 → Properties → Installed Files → Verify integrity of game files.')
    os.startfile('steam://validate/553850')


def default_home():
    base = Path(os.environ.get('LOCALAPPDATA', Path.home()/'AppData'/'Local'))
    return base/'lunas_loader'


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    m.save_json(path, value)


def content_hash(path):
    import hashlib
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def staging_files(root):
    """Inspect an independent staging tree before copying or modifying it."""
    m.need(not root.is_symlink() and not (hasattr(root,'is_junction') and root.is_junction()),'Dummy directory is a link; refusing update')
    files={}
    for path in root.rglob('*'):
        m.need(not path.is_symlink() and not (hasattr(path,'is_junction') and path.is_junction()),'Dummy contains a link; refusing update')
        if path.is_file():files[path.relative_to(root).as_posix()]=content_hash(path)
        else:m.need(path.is_dir(),'Unsupported entry in dummy directory: '+str(path))
    return files


def copy_staging_file(source,destination):
    """Stream into a new file before replacement; never write through a hardlink."""
    destination.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.luna-copy-',dir=destination.parent)
    os.close(fd)
    temporary=Path(name)
    try:
        shutil.copyfile(source,temporary)
        if destination.exists() and not destination.stat().st_mode & stat.S_IWRITE:
            destination.chmod(destination.stat().st_mode | stat.S_IWRITE)
        os.replace(temporary,destination)
    finally:
        if temporary.exists():temporary.unlink()


def sync_staging(source,destination):
    """Retain the top-level directory so an open folder handle cannot block it."""
    desired=staging_files(source);current=staging_files(destination)
    for rel in sorted(current.keys()-desired.keys()):
        path=m.safe_path(destination,rel)
        try:
            if not path.stat().st_mode & stat.S_IWRITE:path.chmod(path.stat().st_mode | stat.S_IWRITE)
            path.unlink()
        except OSError as exc:raise m.ModError('Cannot remove dummy file: '+str(path)+'. Close other configurators or programs using it, then retry. '+str(exc)) from exc
    for path in sorted(destination.rglob('*'),key=lambda p:len(p.parts),reverse=True):
        if path.is_dir():
            try:path.rmdir()
            except OSError:
                # Nonempty/held empty directories may stay; they are not outputs.
                pass
    for rel,h in desired.items():
        path=m.safe_path(destination,rel)
        if current.get(rel)==h and path.is_file() and path.stat().st_nlink<=1 and path.stat().st_mode & stat.S_IWRITE:continue
        try:copy_staging_file(m.safe_path(source,rel),path)
        except OSError as exc:raise m.ModError('Cannot update dummy file: '+str(path)+'. Close other configurators or programs using it, then retry. '+str(exc)) from exc
    m.need(staging_files(destination)==desired,'Dummy contents changed during preparation; close other configurators and retry')


def extract_checked(archive, destination):
    """Independent files only; no code from the ZIP is imported or executed."""
    with m.read_zip(archive) as z:
        for item in z.infolist():
            parts = PurePosixPath(item.filename).parts
            for part in parts:
                m.need(part not in ('.', '..') and not part.endswith((' ', '.')) and
                       part.split('.')[0].upper() not in {'CON','PRN','AUX','NUL',
                       *[f'COM{i}' for i in range(10)], *[f'LPT{i}' for i in range(10)]},
                       'Unsafe Windows archive name: '+item.filename)
            out = m.safe_path(destination, '/'.join(parts))
            if item.is_dir():
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(item) as src, out.open('xb') as dst:
                shutil.copyfileobj(src, dst)


def candidate_exes(folder):
    out = []
    for p in folder.rglob('*'):
        if p.suffix.lower() != '.exe' or not p.is_file():
            continue
        parts = p.relative_to(folder).parts
        if any(x.casefold() in ('_internal', 'source', 'sources', 'extras', 'tools', 'vendor') for x in parts[:-1]):
            continue
        if p.stem.casefold() in ('uninstall', 'unins000', 'python', 'pythonw', 'crashpad_handler'):
            continue
        out.append(p.relative_to(folder).as_posix())
    return sorted(out, key=lambda x:(len(PurePosixPath(x).parts), x.casefold()))


class ElevatedProcess:
    """Keep a process handle when an EXE's own manifest requires elevation."""
    def __init__(self,exe,args,directory):
        import ctypes
        from ctypes import wintypes as w
        class Info(ctypes.Structure):
            _fields_=[('cbSize',w.DWORD),('fMask',w.ULONG),('hwnd',w.HWND),
                      ('lpVerb',w.LPCWSTR),('lpFile',w.LPCWSTR),('lpParameters',w.LPCWSTR),
                      ('lpDirectory',w.LPCWSTR),('nShow',ctypes.c_int),('hInstApp',w.HINSTANCE),
                      ('lpIDList',ctypes.c_void_p),('lpClass',w.LPCWSTR),('hkeyClass',w.HKEY),
                      ('dwHotKey',w.DWORD),('hIcon',w.HANDLE),('hProcess',w.HANDLE)]
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.kernel.GetExitCodeProcess.argtypes=[w.HANDLE,ctypes.POINTER(w.DWORD)]
        self.kernel.CloseHandle.argtypes=[w.HANDLE]
        shell=ctypes.WinDLL('shell32',use_last_error=True)
        shell.ShellExecuteExW.argtypes=[ctypes.POINTER(Info)]
        shell.ShellExecuteExW.restype=w.BOOL
        info=Info();info.cbSize=ctypes.sizeof(info);info.fMask=0x40
        info.lpVerb='open';info.lpFile=str(exe);info.lpParameters=subprocess.list2cmdline(args)
        info.lpDirectory=str(directory);info.nShow=1
        if not shell.ShellExecuteExW(ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        m.need(info.hProcess,'Configuration EXE did not return a process handle')
        self.handle=info.hProcess;self.result=None

    def poll(self):
        if self.handle is None:return self.result
        import ctypes
        from ctypes import wintypes as w
        code=w.DWORD()
        if not self.kernel.GetExitCodeProcess(self.handle,ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        if code.value==259:return None
        self.result=code.value;self.kernel.CloseHandle(self.handle);self.handle=None
        return self.result


class Store:
    def __init__(self, home=None):
        self.home = Path(home or default_home()).absolute()
        self.home.mkdir(parents=True, exist_ok=True)
        m.need(self.home == self.home.resolve(), 'Loader storage must not be a redirected folder')
        for name in ('mods','staging','backups','snapshots','packages'):
            m.safe_path(self.home,name).mkdir(exist_ok=True)
        self.path = self.home/'library.json'
        self.state = json.loads(self.path.read_text('utf-8')) if self.path.exists() else dict(schema=2, game_root='', mods=[], sequence=0)
        m.need(self.state.get('schema') == 2, 'Unsupported library version')
        self.dummy = self.home/'staging'/'dummy_game'
        self.baseline = self.home/'staging'/'baseline'
        self.launch_record = None
        migrated=False
        for row in self.state['mods']:
            if 'option_model' not in row:
                files=self.home/'mods'/row['id']/'files'
                row['option_model']=opts.model(files) if files.is_dir() else dict(root='',description='',options=[])
                row['option_state']=opts.defaults(row['option_model']);migrated=True
        if migrated:self.save()

    def save(self):
        atomic_json(self.path,self.state)
        for row in self.state['mods']:
            atomic_json(self.home/'mods'/row['id']/'record.json',row)

    def enabled(self):
        return [r for r in self.state['mods'] if r['enabled']]

    def mod(self, identity):
        found=[r for r in self.state['mods'] if r['id']==identity]
        m.need(len(found)==1,'Unknown mod')
        return found[0]

    def import_zip(self, path):
        path=Path(path)
        m.need(path.suffix.casefold()=='.zip' and path.is_file(),'Drop ZIP files, not folders or EXEs')
        identity=content_hash(path)
        existing=next((r for r in self.state['mods'] if r['id']==identity),None)
        if existing:
            print('Already imported:',existing['name']);return existing
        folder=self.home/'mods'/identity
        if folder.exists():
            record=json.loads((folder/'record.json').read_text('utf-8'))
            record['enabled']=True
            if 'option_model' not in record:
                record['option_model']=opts.model(folder/'files');record['option_state']=opts.defaults(record['option_model'])
            self.state['mods'].append(record);self.save()
            print('Restored to library:',record['name']);return record
        temporary=Path(tempfile.mkdtemp(prefix='.import-',dir=self.home/'mods'))
        try:
            shutil.copyfile(path,temporary/'archive.zip')
            extracted=temporary/'files';extracted.mkdir()
            extract_checked(temporary/'archive.zip',extracted)
            exes=candidate_exes(extracted)
            name=path.stem
            manifest=next((p for p in extracted.rglob('manifest.json') if len(p.relative_to(extracted).parts)<=2),None)
            if manifest:
                try:name=json.loads(manifest.read_text('utf-8-sig')).get('Name',name)
                except (ValueError,OSError):pass
            launch_args=[]
            native=extracted/'unified-mod.json'
            if native.exists():
                author=json.loads(native.read_text('utf-8-sig'))
                name=author.get('name',name)
                config=author.get('configuration')
                if config:
                    entry=config['executable']
                    exe=m.safe_path(extracted,entry)
                    m.need(exe.is_file() and exe.suffix.lower()=='.exe','Declared configurator EXE missing')
                    exes=[entry]+[e for e in exes if e!=entry]
                    launch_args=config.get('arguments',[])
                    m.need(isinstance(launch_args,list) and all(isinstance(a,str) for a in launch_args),'Invalid configuration arguments')
            # Rank one primary executable. Multiple equally deep candidates can be cycled in the UI.
            descriptor=dict(id=identity,name=str(name),enabled=True,executables=exes,
                            executable=exes[0] if exes else None,arguments=launch_args,
                            configurations=[],configuration_order=0,option_model=opts.model(extracted))
            descriptor['option_state']=opts.defaults(descriptor['option_model'])
            os.rename(temporary,folder)
            self.state['mods'].append(descriptor);self.save()
            print('Imported:',name,'—',len(exes),'configurator EXE(s)')
            return descriptor
        finally:
            if temporary.exists():shutil.rmtree(temporary)

    def set_game(self, path):
        root=Path(path).absolute()
        m.need(root.is_dir() and root == root.resolve(),'Choose the real game folder')
        for rel in m.BUILD_HASHES:
            m.need(m.safe_path(root,rel).is_file(),'Game folder is missing '+rel)
        previous=self.state.get('game_root')
        if previous and Path(previous)!=root:
            old_state=Path(previous)/'.unifiedmods/installed.json'
            if old_state.exists():
                m.need(not json.loads(old_state.read_text()).get('files'),'Purge the previous game folder before changing it')
            m.need(not any(r['configurations'] for r in self.state['mods']),
                   'Configured outputs are tied to the previous game. Remove their saved configuration before changing game folders.')
        self.state['game_root']=str(root);self.save()
        self.prepare()

    def root(self):
        value=self.state.get('game_root')
        m.need(value,'Choose the real game folder first')
        return Path(value)

    def clean_baseline(self):
        m.need(not self.state.get('repair_pending'),'Finish Steam verification, then click Rebuild dummy and confirm Steam has finished.')
        root=self.root();m.closed()
        with m.locked(root) as state:
            m.need(not (state/'pending.json').exists(),'An interrupted deployment needs Recover before continuing')
            # External manager patches are not owned by this loader. Copying
            # inputs for a configurator must never require their removal.
            installed=m.records(root,state)
            original_map={r['target']:r for r in installed}
            for r in installed:
                m.need(m.optional_hash(m.file_bytes(m.safe_path(root,r['target'])))==r['installed_sha256'],
                       'A deployed file changed externally: '+r['target'])
            inputs=set(m.BUILD_HASHES)
            for p in m.safe_path(root,'data/game').iterdir():
                if p.is_file() and p.suffix.lower() in ('.dl_bin','.dl_typelib','.dll'):
                    inputs.add(p.relative_to(root).as_posix())
            # Include exact targets needed by native packages/plain exports.
            for row in self.enabled():
                for op,b in self.static_operations(row,bind=False):inputs.add(op['target'])
                for saved in row['configurations']:
                    if not configurator_private_file(saved['operation']['target']):inputs.add(saved['operation']['target'])
            temp=Path(tempfile.mkdtemp(prefix='.baseline-',dir=self.home/'staging'))
            hashes={}
            try:
                for rel in sorted(inputs):
                    if rel in original_map:
                        b=m.original(root,original_map[rel])
                    else:b=m.file_bytes(m.safe_path(root,rel))
                    hashes[rel]=m.optional_hash(b)
                    if b is not None:
                        p=temp/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
                atomic_json(temp/'baseline.json',dict(root=str(root),hashes=hashes))
                # The fixed dummy path is independent of the real installation. No links or hardlinks.
                if self.baseline.exists():shutil.rmtree(self.baseline)
                os.rename(temp,self.baseline)
            finally:
                if temp.exists():shutil.rmtree(temp)

    def static_operations(self,row,bind=True):
        folder=self.home/'mods'/row['id'];archive=folder/'archive.zip'
        definition=row.get('option_model',dict(root='',options=[]))
        selected=None
        if definition['options']:
            selected=opts.selected_files(folder/'files',definition,row['option_state'])
        try:
            operations=m.import_archive(archive)
            if selected is not None:
                members=[path.relative_to(folder/'files').as_posix() for path,base in selected]
                try:operations=m.import_archive(archive,selected_members=members)
                except m.ModError:
                    # A known adapter with only its uninstaller/no payload selected
                    # contributes nothing. Our own Purge/Deploy handles restoration.
                    operations=[]
        except m.ModError:
            native=folder/'files'/'unified-mod.json'
            if native.exists() and json.loads(native.read_text('utf-8-sig')).get('files'):
                raise
            if row['executables']:
                return []  # Sibling DLLs are the tool's runtime, not inferred game plugins.
            operations=self.plain_operations(folder/'files',selected)
            if not operations and selected is None:
                m.need(row['executables'],'This ZIP contains no supported payload or configurator: '+row['name'])
                return []
        result=[]
        for op,data in operations:
            if configurator_private_file(op['target']):continue
            op=dict(op,name=row['name'],mod_id=row['id'])
            if bind:
                if op.get('baseline_required'):
                    op=m.bind_operation(op,data,self.baseline)
                elif not (op.get('before_sha256') or op.get('before_fingerprints') or op.get('before_missing')):
                    before=m.file_bytes(m.safe_path(self.baseline,op['target']))
                    if before is None:op['before_missing']=True
                    else:op['before_sha256']=[m.sha(before)]
                    op['build_sha256']={p:content_hash(self.baseline/p) for p in m.BUILD_HASHES}
                m.validate_operation(op,data)
            result.append((op,data))
        return result

    def plain_operations(self,folder,selected=None):
        result=[]
        paths=selected if selected is not None else [(p,folder) for p in sorted(folder.rglob('*'))]
        for p,base in paths:
            if not p.is_file():continue
            rel=p.relative_to(base).as_posix();parts=PurePosixPath(rel).parts
            # Root data/mods/plugins/bin folders, or conventional bare Install/Addon archive outputs.
            if parts[0] in ('data','mods','plugins','bin'):target=rel
            elif len(parts)==1 and p.suffix.lower()=='.dll':target='bin/'+p.name
            elif (len(parts)==1 or parts[0] in ('Install','Addon')) and '.patch_' in p.name:
                target='data/'+p.name
            else:continue
            if p.name.startswith('9ba626afa44a3aa3.patch_'):
                raise m.ModError('Unknown boot installer needs an adapter: '+rel)
            try:m.target_name(target)
            except m.ModError:continue
            data=p.read_bytes()
            result.append((dict(name=folder.parent.name,target=target,sha256=m.sha(data),source_component=base.relative_to(folder).as_posix()),data))
        return result

    def patch_slots(self):
        """Reserve fresh numbered patches above external files without touching them."""
        root=self.root();owned=set()
        with m.locked(root) as state:
            owned={r['target'].casefold() for r in m.records(root,state) if r['original_sha256'] is None}
        highest=-1
        for p in m.safe_path(root,'data').glob('*.patch_*'):
            relative=p.relative_to(root).as_posix()
            match=re.fullmatch(r'data/[0-9a-fA-F]+\.patch_([0-9]+)(?:\.(?:stream|gpu_resources))?',relative)
            if match and relative.casefold() not in owned:highest=max(highest,int(match[1]))
        return highest+1

    def assembled(self,stop_after=None):
        final={};owners={};claims={};next_slot=self.patch_slots()
        for row in self.enabled():
            operations=self.static_operations(row)
            # Each archive and its companions share a slot. All slots increase
            # along the visible list, including archives with different IDs.
            groups={}
            grouped=operations+[(entry['operation'],b'') for entry in row['configurations']]
            for op,b in sorted(grouped,key=lambda pair:pair[0]['target']):
                match=re.fullmatch(r'(data/[0-9a-fA-F]+)\.patch_([0-9]+)(\.(?:stream|gpu_resources))?',op['target'])
                if match:
                    group=(op.get('source_component',''),match[1].casefold(),int(match[2]))
                    if group not in groups:groups[group]=next_slot;next_slot+=1
            for source,b in operations:
                op=copy.deepcopy(source);target=op['target']
                match=re.fullmatch(r'(data/[0-9a-fA-F]+)\.patch_([0-9]+)(\.(?:stream|gpu_resources))?',target)
                if match:
                    slot=groups[(op.get('source_component',''),match[1].casefold(),int(match[2]))]
                    target=match[1]+'.patch_'+str(slot)+(match[3] or '')
                    op['source_target']=op['target'];op['target']=target;op['patch_priority']=slot
                    op.pop('before_sha256',None);op.pop('before_fingerprints',None)
                    op['before_missing']=True
                before=m.file_bytes(m.safe_path(self.baseline,target))
                valid=(before is None and op.get('before_missing') is True) or (before is not None and
                      (m.sha(before) in op.get('before_sha256',[]) or m.fingerprint(before) in op.get('before_fingerprints',[])))
                m.need(valid,'Mod does not match the copied baseline: '+row['name']+' → '+target)
                for rel,h in op.get('build_sha256',{}).items():
                    m.need(content_hash(m.safe_path(self.baseline,rel))==h,'Unsupported game build for '+row['name'])
                key=target.casefold()
                if key in final and final[key][0]['sha256']!=op['sha256']:
                    print('Load-order override:',row['name'],'replaces earlier output for',target)
                final[key]=(op,b);owners[key]=dict(id=row['id'],sha256=op['sha256'])
            # Configuration is part of its row, not a separate timestamp-sorted pass.
            for saved in row['configurations']:
                op=copy.deepcopy(saved['operation']);key=op['target'].casefold()
                if configurator_private_file(op['target']):continue
                match=re.fullmatch(r'(data/[0-9a-fA-F]+)\.patch_([0-9]+)(\.(?:stream|gpu_resources))?',op['target'])
                for dep in saved.get('dependencies',[]):
                    dependency_present=owners.get(key)==dep
                    if match and not dependency_present:
                        dependency_present=any(owner==dep and name.startswith(match[1].casefold()+'.patch_') for name,owner in owners.items())
                    m.need(dependency_present,'Configured output needs its base above it in the load order. Reset and reconfigure '+row['name'])
                if match:
                    slot=groups[(op.get('source_component',''),match[1].casefold(),int(match[2]))]
                    op['source_target']=op['target'];op['target']=match[1]+'.patch_'+str(slot)+(match[3] or '')
                    op['patch_priority']=slot;op.pop('before_sha256',None);op.pop('before_fingerprints',None);op['before_missing']=True
                    key=op['target'].casefold()
                b=(self.home/'mods'/row['id']/'configured'/op['sha256']).read_bytes()
                m.validate_operation(op,b)
                for rel,h in op.get('build_sha256',{}).items():
                    m.need(content_hash(m.safe_path(self.baseline,rel))==h,'Saved configuration belongs to a different game build. Reset and reconfigure '+row['name'])
                final[key]=(op,b);owners[key]=dict(id=row['id'],sha256=op['sha256'])
            if row['id']==stop_after:break
        for op,b in final.values():
            m.validate_operation(op,b)
            for claim in op.get('resource_claims',[]):
                previous=claims.get(claim)
                if previous is not None:
                    m.need(op.get('patch_priority') is not None and previous.get('patch_priority') is not None,
                           'Unordered resource conflict: '+claim)
                    print('Ordered archive override:',claim,'→',op['target'])
                claims[claim]=op
        return final,owners

    def prepare(self,stop_after=None,discard_old=False):
        self.clean_baseline()
        final,owners=self.assembled(stop_after)
        temp=Path(tempfile.mkdtemp(prefix='.dummy-',dir=self.home/'staging'))
        try:
            shutil.copytree(self.baseline,temp,dirs_exist_ok=True)
            for op,b in final.values():
                out=m.safe_path(temp,op['target']);out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(b)
            if self.dummy.exists():
                before=staging_files(self.dummy)
                snapshot=(self.home/'staging'/('.dummy-backup-'+uuid.uuid4().hex) if discard_old else
                          self.home/'snapshots'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
                shutil.copytree(self.dummy,snapshot)
                m.need(staging_files(snapshot)==before and staging_files(self.dummy)==before,'Dummy changed during backup; close other configurators and retry')
                ready=self.home/'staging'/'ready.json'
                if ready.exists():ready.unlink()
                try:sync_staging(temp,self.dummy)
                except Exception as exc:
                    try:sync_staging(snapshot,self.dummy)
                    except Exception as rollback:
                        raise m.ModError(str(exc)+' Rollback could not finish: '+str(rollback)+'. Previous dummy saved at '+str(snapshot)+'. No configurator was launched.') from exc
                    if discard_old:shutil.rmtree(snapshot)
                    raise m.ModError(str(exc)+' Previous dummy contents restored. No configurator was launched.') from exc
                if discard_old:shutil.rmtree(snapshot)
            else:
                self.dummy.mkdir()
                sync_staging(temp,self.dummy)
            atomic_json(self.home/'staging'/'ready.json',dict(enabled=[r['id'] for r in self.enabled()],owners=owners))
            print('Dummy game ready:',self.dummy)
        finally:
            if temp.exists():shutil.rmtree(temp)
        return final

    def rebuild_dummy(self,steam_finished=False):
        m.need(not self.launch_record,'Close and capture the configurator before rebuilding')
        pending=self.state.get('repair_pending')
        if pending:
            m.need(pending.get('phase')=='waiting','Reset was interrupted. Click Reset game files again to finish removing the backed-up files.')
            m.need(steam_finished,'Confirm that Steam has finished verification first')
            for rel in pending['targets']:
                m.need(m.safe_path(self.root(),rel).is_file(),'Steam has not restored '+rel)
            self.state.pop('repair_pending');self.save()
        return self.prepare(discard_old=True)

    def reset_targets(self):
        targets=set(m.BUILD_HASHES)
        for row in self.state['mods']:
            for saved in row['configurations']:
                if repairable_game_file(saved['operation']['target']):targets.add(saved['operation']['target'])
            for op,b in self.static_operations(row,bind=False):
                if repairable_game_file(op['target']):targets.add(op['target'])
        with m.locked(self.root()) as state:
            installed=m.records(self.root(),state)
            targets.update(r['target'] for r in installed if repairable_game_file(r['target']))
            created={r['target'] for r in installed if r['original_sha256'] is None}
        return sorted(rel for rel in targets if rel in m.BUILD_HASHES or
                      (rel not in created and m.safe_path(self.root(),rel).is_file()))

    def reset_game_files(self,reviewed_targets=None):
        """Back up a bounded set of base files, remove them, hand repair to Steam."""
        root=self.root();m.closed()
        m.need(not self.launch_record,'Close and capture the configurator before resetting')
        pending=self.state.get('repair_pending')
        if not pending:
            targets=self.reset_targets()
            if reviewed_targets is not None:m.need(targets==reviewed_targets,'Reset targets changed. Review Reset game files again.')
            directory=self.home/'backups'/'steam-reset'/uuid.uuid4().hex
            directory.mkdir(parents=True)
            with m.locked(root) as state:
                m.need(not (state/'pending.json').exists(),'Run Recover before Reset game files')
                installed=m.records(root,state)
                atomic_json(directory/'library-before.json',self.state)
                atomic_json(directory/'installed-before.json',dict(schema=1,root=str(root),files=installed))
                hashes={}
                for rel in targets:
                    m.need(repairable_game_file(rel),'Unsupported reset target')
                    path=m.safe_path(root,rel);data=m.file_bytes(path);hashes[rel]=m.optional_hash(data)
                    if data is not None:
                        dest=directory/'files'/rel;dest.parent.mkdir(parents=True,exist_ok=True)
                        m.write_atomic(dest,data);m.need(content_hash(dest)==hashes[rel],'Reset backup verification failed')
                atomic_json(directory/'backup.json',dict(root=str(root),hashes=hashes))
                pending=dict(targets=targets,backup=str(directory),phase='removing')
                self.state['repair_pending']=pending;self.save()
        m.need(all(repairable_game_file(rel) for rel in pending['targets']),'Invalid reset journal')
        with m.locked(root) as state:
            m.need(not (state/'pending.json').exists(),'Run Recover before Reset game files')
            if pending['phase']=='removing':
                # Journal is durable before deletion. A retry completes this same set.
                directory=Path(pending['backup'])
                backup=json.loads((directory/'backup.json').read_text())
                m.need(backup['root']==str(root) and set(backup['hashes'])==set(pending['targets']),'Reset backup does not match the journal')
                for rel,h in backup['hashes'].items():
                    if h is not None:m.need(content_hash(m.safe_path(directory/'files',rel))==h,'Reset backup is corrupt: '+rel)
                    actual=m.optional_hash(m.file_bytes(m.safe_path(root,rel)))
                    m.need(actual is None or actual==h,'Game file changed since reset backup; refusing deletion: '+rel)
                for rel in pending['targets']:
                    path=m.safe_path(root,rel)
                    if path.exists():path.unlink()
                installed=m.records(root,state)
                atomic_json(state/'installed.json',dict(schema=1,root=str(root),files=[r for r in installed if r['target'] not in pending['targets']]))
                for row in self.state['mods']:row['configurations']=[]
                self.state.pop('deployed_bundle',None)
                pending['phase']='waiting';self.save()
        print('Reset backup:',pending['backup'])
        print('Saved EXE outputs cleared; imported ZIPs, options and load order retained.')
        try:request_steam_verification()
        except Exception as exc:
            print('Steam could not be opened:',exc)
            print('In Steam: Helldivers 2 → Properties → Installed Files → Verify integrity of game files.')
        print('Verification requested. Wait for Steam to finish, then click Rebuild dummy. Luna cannot detect Steam completion.')

    def file_inventory(self):
        inventory={}
        for name in ('data','mods','plugins','bin'):
            base=m.safe_path(self.dummy,name)
            if not base.exists():continue
            for p in base.rglob('*'):
                m.need(not p.is_symlink() and not (hasattr(p,'is_junction') and p.is_junction()),'A configurator created a file link')
                if not p.is_file():continue
                rel=p.relative_to(self.dummy).as_posix()
                inventory[rel]=content_hash(p)
        return inventory

    def launch(self,identity):
        row=self.mod(identity)
        m.need(row['enabled'],'Enable this mod before configuring it')
        m.need(row.get('executable'),'This mod has no configuration EXE')
        self.prepare(stop_after=identity)
        final,owners=self.assembled(stop_after=identity)
        before=self.file_inventory()
        folder=self.home/'mods'/identity/'files'
        exe=m.safe_path(folder,row['executable'])
        args=[a.replace('{dummy}',str(self.dummy)).replace('{mod}',str(folder)).replace('{game}',str(self.root())) for a in row.get('arguments',[])]
        env=dict(os.environ,PYINSTALLER_RESET_ENVIRONMENT='1')
        # PyInstaller's private DLL directory must not leak into another bundled executable.
        if os.name=='nt':
            import ctypes
            ctypes.windll.kernel32.SetDllDirectoryW(None)
        try:
            try:process=subprocess.Popen([str(exe),*args],cwd=exe.parent,env=env)
            except OSError as e:
                if os.name!='nt' or getattr(e,'winerror',None)!=740:raise
                process=ElevatedProcess(exe,args,exe.parent)
        finally:
            if os.name=='nt' and getattr(__import__('sys'),'frozen',False):
                import ctypes,sys
                ctypes.windll.kernel32.SetDllDirectoryW(sys._MEIPASS)
        self.launch_record=dict(id=identity,before=before,owners=owners)
        print('Opened:',row['name'])
        print('If asked for a game directory, paste the dummy path shown in the loader.')
        return process

    def capture(self,return_code=0):
        record=self.launch_record
        m.need(record,'No configuration session to capture')
        m.need(return_code==0,'Configurator returned an error. Its outputs remain in the dummy area; no configuration was committed.')
        row=self.mod(record['id']);after=self.file_inventory()
        m.need(all(rel in after for rel in record['before']),'Configurator deleted an input. Staging is preserved for inspection.')
        saved={e['operation']['target']:e for e in row['configurations']}
        for rel,h in after.items():
            if record['before'].get(rel)==h:continue
            if configurator_private_file(rel):
                print('Kept configurator helper in staging:',rel);continue
            m.need(rel not in m.BUILD_HASHES,'Configurator changed a read-only build witness: '+rel)
            m.target_name(rel)
            b=m.safe_path(self.dummy,rel).read_bytes()
            original=m.file_bytes(m.safe_path(self.baseline,rel))
            op=dict(target=rel,sha256=m.sha(b),name=row['name'],mod_id=row['id'],
                    build_sha256={p:content_hash(self.baseline/p) for p in m.BUILD_HASHES})
            if original is None:op['before_missing']=True
            else:op['before_sha256']=[m.sha(original)]
            m.validate_operation(op,b)
            owner=record['owners'].get(rel.casefold())
            deps=[owner] if owner and owner['id']!=row['id'] else saved.get(rel,{}).get('dependencies',[])
            payload=self.home/'mods'/row['id']/'configured'/op['sha256']
            payload.parent.mkdir(exist_ok=True);m.write_atomic(payload,b)
            saved[rel]=dict(operation=op,dependencies=deps)
        row['configurations']=list(saved.values())
        self.state['sequence']+=1;row['configuration_order']=self.state['sequence'];self.save()
        self.launch_record=None
        print('Saved configured output:',len(row['configurations']),'file(s)')

    def write_bundle(self,final):
        ops=[];blobs={}
        for op,b in final.values():
            op=dict(op,payload='payloads/'+op['sha256']);ops.append(op);blobs[op['payload']]=b
        m.need(ops,'No deployable outputs are selected. Enable an option/mod, configure an EXE, or use Purge to restore the active deployment.')
        filename=self.home/'packages'/(uuid.uuid4().hex+'.pyz')
        source=Path(m.__file__)
        if not source.is_file():
            import sys
            source=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'manager.py'
        with zipfile.ZipFile(filename,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('__main__.py',source.read_bytes())
            z.writestr('package.json',json.dumps(dict(schema=1,name=TITLE,files=ops)))
            for name,b in blobs.items():z.writestr(name,b)
        m.package(filename)
        return filename

    def mirror_backups(self):
        root=self.root();state=root/'.unifiedmods'
        if state.exists():
            destination=self.home/'backups'/m.sha(str(root).casefold().encode())[:20]
            shutil.copytree(state,destination,dirs_exist_ok=True)
            print('Backup copy:',destination)

    def save_plan_backup(self,final):
        directory=self.home/'backups'/m.sha(str(self.root()).casefold().encode())[:20]/'pre-deploy'/uuid.uuid4().hex
        directory.mkdir(parents=True)
        records=[]
        for op,data in final.values():
            before=m.file_bytes(m.safe_path(self.baseline,op['target']))
            h=m.optional_hash(before)
            if before is not None:
                p=directory/'originals'/h;p.parent.mkdir(exist_ok=True);m.write_atomic(p,before)
                m.need(content_hash(p)==h,'Pre-deployment backup verification failed')
            records.append(dict(target=op['target'],original_sha256=h,installed_sha256=op['sha256']))
        atomic_json(directory/'backup.json',dict(root=str(self.root()),files=records))
        print('Verified pre-deployment backup:',directory)

    def deploy(self):
        final=self.prepare();bundle=self.write_bundle(final)
        # Verify the proposed result against clean copies before purging an active deployment.
        m.apply(self.baseline,bundle,'check',coexist=True)
        root=self.root()
        with m.locked(root) as state:
            m.need(not (state/'pending.json').exists(),'Run Recover before Deploy')
            installed=bool(m.records(root,state))
        self.save_plan_backup(final)
        previous=self.state.get('deployed_bundle')
        if installed:
            self.mirror_backups();m.apply(root,None,'restore',coexist=True)
        try:m.apply(root,bundle,'deploy',coexist=True)
        except Exception:
            if installed and previous and Path(previous).is_file():
                print('New deployment failed; restoring the previous mod selection.')
                m.apply(root,previous,'deploy',coexist=True)
            raise
        self.state['deployed_bundle']=str(bundle);self.save();self.mirror_backups()
        print('Deployed. Launch the game normally.')

    def purge(self):
        root=self.root()
        with m.locked(root) as state:
            m.need(not (state/'pending.json').exists(),'Run Recover before Purge')
            installed=bool(m.records(root,state))
        if installed:
            self.mirror_backups();m.apply(root,None,'restore',coexist=True);self.mirror_backups()
        else:print('Already purged. No deployed files to restore.')
        self.state.pop('deployed_bundle',None);self.save()
        print('Purge complete. Imported ZIPs, configuration and backups retained.')

    def recover(self):
        m.apply(self.root(),None,'recover',coexist=True);self.mirror_backups()

    def icon_path(self,identity):
        row=self.mod(identity);relative=row.get('option_model',{}).get('icon')
        if not relative:return None
        try:
            image=m.safe_path(self.home/'mods'/identity/'files',relative)
            return image if image.is_file() and image.stat().st_size<=16*1024*1024 else None
        except (m.ModError,OSError):return None

    def set_options(self,identity,selection):
        row=self.mod(identity)
        opts.validate(row['option_model'],selection)
        row['option_state']=copy.deepcopy(selection);self.save()
        print('Saved mod options:',row['name'],'— click Deploy to apply')

    def move_mod(self,identity,index):
        rows=self.state['mods'];row=self.mod(identity)
        old=rows.index(row);index=max(0,min(int(index),len(rows)-1))
        if old==index:return
        rows.pop(old);rows.insert(index,row);self.save()
        print('Load order:',index+1,'—',row['name'],'(top first; bottom last)')

    def toggle(self,identity):
        row=self.mod(identity);row['enabled']=not row['enabled'];self.save()
        print(('Enabled: ' if row['enabled'] else 'Disabled: ')+row['name'])

    def remove(self,identity):
        row=self.mod(identity)
        # Keep files on disk, including presets and archives, so removal is reversible.
        row['enabled']=False
        self.state['mods']=[r for r in self.state['mods'] if r['id']!=identity]
        self.save();print('Removed from list; files retained:',row['name'])

    def clear_configuration(self,identity):
        row=self.mod(identity);row['configurations']=[];row['configuration_order']=0;self.save()
        print('Saved configured outputs cleared; previous files remain in the mod folder.')
