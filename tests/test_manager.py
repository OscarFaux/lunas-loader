import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('manager', Path(__file__).parents[1] / 'manager.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'game'
        (self.root/'data/game').mkdir(parents=True)
        self.inputs = []
        for n in ['a', 'b']:
            before, after = ('original-' + n).encode(), ('modified-' + n).encode()
            (self.root/f'data/game/{n}.dl_bin').write_bytes(before)
            archive = self.base / (n + '.zip')
            manifest = dict(schema=1, id=n, name='Mod '+n, files=[dict(
                target=f'data/game/{n}.dl_bin', payload='file.bin', sha256=m.sha(after),
                before_sha256=[m.sha(before)])])
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('unified-mod.json', json.dumps(manifest))
                z.writestr('file.bin', after)
            self.inputs.append(archive)
        self.bundle = self.base/'combined.pyz'
        m.build(self.inputs, self.bundle)

    def test_round_trip_and_preflight(self):
        m.apply(self.root, self.bundle, 'check')
        self.assertEqual((self.root/'data/game/a.dl_bin').read_bytes(), b'original-a')
        m.apply(self.root, self.bundle, 'deploy')
        self.assertEqual((self.root/'data/game/b.dl_bin').read_bytes(), b'modified-b')
        m.apply(self.root, None, 'restore')
        self.assertEqual((self.root/'data/game/a.dl_bin').read_bytes(), b'original-a')
        self.assertEqual((self.root/'data/game/b.dl_bin').read_bytes(), b'original-b')

    def test_conflict_rejected(self):
        conflict = self.base/'different.zip'
        with zipfile.ZipFile(self.inputs[0]) as z:
            manifest = json.loads(z.read('unified-mod.json'))
        manifest['files'][0]['sha256'] = m.sha(b'different')
        with zipfile.ZipFile(conflict, 'w') as z:
            z.writestr('unified-mod.json', json.dumps(manifest))
            z.writestr('file.bin', b'different')
        with self.assertRaisesRegex(m.ModError, 'Target conflict'):
            m.build([self.inputs[0], conflict], self.base/'conflict.pyz')
        self.assertFalse((self.base/'conflict.pyz').exists())

    def test_unknown_original_prevents_all_writes(self):
        (self.root/'data/game/b.dl_bin').write_bytes(b'updated-game')
        with self.assertRaises(m.ModError):
            m.apply(self.root, self.bundle, 'deploy')
        self.assertEqual((self.root/'data/game/a.dl_bin').read_bytes(), b'original-a')

    def test_external_change_protected_on_restore(self):
        m.apply(self.root, self.bundle, 'deploy')
        (self.root/'data/game/b.dl_bin').write_bytes(b'other-mod')
        with self.assertRaises(m.ModError):
            m.apply(self.root, None, 'restore')
        self.assertEqual((self.root/'data/game/a.dl_bin').read_bytes(), b'modified-a')

    def test_failure_after_first_write_rolls_back(self):
        real = m.write_atomic
        def fail_second(path, data):
            if path.name == 'b.dl_bin' and data == b'modified-b':
                raise OSError('simulated disk failure')
            real(path, data)
        with patch.object(m, 'write_atomic', side_effect=fail_second):
            with self.assertRaises(OSError):
                m.apply(self.root, self.bundle, 'deploy')
        self.assertEqual((self.root/'data/game/a.dl_bin').read_bytes(), b'original-a')
        self.assertFalse((self.root/'.unifiedmods/pending.json').exists())

    def test_crash_requires_explicit_recovery(self):
        real = m.write_atomic
        def crash(path, data):
            if path.name == 'b.dl_bin' and data == b'modified-b':
                raise KeyboardInterrupt('simulated process termination')
            real(path, data)
        with patch.object(m, 'write_atomic', side_effect=crash):
            with self.assertRaises(KeyboardInterrupt):
                m.apply(self.root, self.bundle, 'deploy')
        self.assertTrue((self.root/'.unifiedmods/pending.json').exists())
        with self.assertRaisesRegex(m.ModError, 'recover first'):
            m.apply(self.root, self.bundle, 'deploy')
        m.apply(self.root, None, 'recover')
        self.assertEqual((self.root/'data/game/a.dl_bin').read_bytes(), b'original-a')

    def test_corrupt_backup_blocks_restore(self):
        m.apply(self.root, self.bundle, 'deploy')
        for p in (self.root/'.unifiedmods/backups').iterdir():
            p.write_bytes(b'bad')
        with self.assertRaisesRegex(m.ModError, 'damaged'):
            m.apply(self.root, None, 'restore')
        self.assertEqual((self.root/'data/game/a.dl_bin').read_bytes(), b'modified-a')

    def test_legacy_boot_conflict(self):
        (self.root/'data/9ba626afa44a3aa3.patch_1').touch()
        with self.assertRaisesRegex(m.ModError, 'legacy boot'):
            m.apply(self.root, self.bundle, 'deploy')

    def test_zip_slip(self):
        archive = self.base/'unsafe.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('../escape', b'x')
        with self.assertRaisesRegex(m.ModError, 'Unsafe archive'):
            m.import_archive(archive)

    def test_payload_tampering(self):
        with zipfile.ZipFile(self.inputs[0], 'r') as z:
            manifest = z.read('unified-mod.json')
        with zipfile.ZipFile(self.inputs[0], 'w') as z:
            z.writestr('unified-mod.json', manifest)
            z.writestr('file.bin', b'tampered')
        with self.assertRaisesRegex(m.ModError, 'SHA-256 mismatch'):
            m.import_archive(self.inputs[0])

    def test_link_escape(self):
        (self.root/'data/game/a.dl_bin').unlink()
        outside = self.base/'outside'
        outside.write_bytes(b'original-a')
        (self.root/'data/game/a.dl_bin').symlink_to(outside)
        with self.assertRaisesRegex(m.ModError, 'Links/junctions'):
            m.apply(self.root, self.bundle, 'deploy')
        self.assertEqual(outside.read_bytes(), b'original-a')

    def test_cross_process_lock(self):
        import subprocess, sys
        with m.locked(self.root):
            result = subprocess.run([sys.executable, str(Path(m.__file__)), 'status', '--game-root', str(self.root)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Another manager operation', result.stderr)

    def build_inputs(self):
        (self.root/'bin').mkdir(exist_ok=True)
        (self.root/'bin/helldivers2.exe').write_bytes(b'real-game-marker')
        for rel in m.STAGE_INPUTS:
            (self.root/rel).write_bytes(('baseline-'+rel).encode())

    def test_identical_shared_files_deduplicated(self):
        out = self.base/'dedup.pyz'
        m.build([self.inputs[0],self.inputs[0]],out)
        self.assertEqual(len(m.package(out)),1)

    def test_new_plugin_created_and_removed(self):
        archive=self.base/'plugin.zip'
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('unified-mod.json',json.dumps(dict(schema=1,id='plugin',name='Plugin',files=[dict(
                target='plugins/Example/plugin.dll',payload='p',sha256=m.sha(b'plugin'),before_missing=True)])))
            z.writestr('p',b'plugin')
        bundle=self.base/'plugin.pyz';m.build([archive],bundle)
        m.apply(self.root,bundle,'deploy')
        self.assertEqual((self.root/'plugins/Example/plugin.dll').read_bytes(),b'plugin')
        m.apply(self.root,None,'restore')
        self.assertFalse((self.root/'plugins/Example/plugin.dll').exists())

    def test_patch_resource_conflict(self):
        import struct
        archives=[]
        for n in range(2):
            payload=bytearray(184);struct.pack_into('<III',payload,0,0xf0000011,1,1)
            struct.pack_into('<QQ',payload,104,123,456)
            payload[-1]=n
            archive=self.base/f'patch{n}.zip';archives.append(archive)
            with zipfile.ZipFile(archive,'w') as z:
                z.writestr('unified-mod.json',json.dumps(dict(schema=1,id=str(n),name='Patch',files=[dict(
                    target=f'data/{n}.patch_0',payload='p',sha256=m.sha(payload),before_missing=True)])))
                z.writestr('p',payload)
        with self.assertRaisesRegex(m.ModError,'Resource conflict'):
            m.build(archives,self.base/'bad-resources.pyz')

    def test_stage_base_and_configurator_captured_together(self):
        self.build_inputs()
        stage=self.base/'stage'
        m.stage_create(self.root,stage,[self.inputs[0]],['data/game/a.dl_bin','data/game/b.dl_bin'])
        self.assertEqual((stage/'data/game/a.dl_bin').read_bytes(),b'modified-a')
        (stage/'data/game/b.dl_bin').write_bytes(b'configured-b')
        (stage/'data/game/a.dl_bin').write_bytes(b'base-plus-configured-a')
        captured=self.base/'capture.zip';m.stage_capture(stage,captured,'Combined')
        result=m.import_archive(captured)
        self.assertEqual({op['target'] for op,b in result},{'data/game/a.dl_bin','data/game/b.dl_bin'})
        self.assertEqual((self.root/'data/game/a.dl_bin').read_bytes(),b'original-a')
        combined=self.base/'stage.pyz';m.build([captured],combined)
        m.apply(self.root,combined,'deploy')
        self.assertEqual((self.root/'data/game/a.dl_bin').read_bytes(),b'base-plus-configured-a')
        m.apply(self.root,None,'restore')
        self.assertEqual((self.root/'data/game/b.dl_bin').read_bytes(),b'original-b')

    def test_stage_dll_change_rejected(self):
        self.build_inputs();stage=self.base/'stage'
        m.stage_create(self.root,stage,[])
        (stage/'data/game/game.dll').write_bytes(b'changed')
        with self.assertRaisesRegex(m.ModError,'read-only build input'):
            m.stage_capture(stage,self.base/'captured.zip','Bad')

    def test_stage_inside_game_rejected(self):
        self.build_inputs()
        with self.assertRaisesRegex(m.ModError,'separate folders'):
            m.stage_create(self.root,self.root/'stage',[])

    def test_generic_file_tree_import_and_roundtrip(self):
        self.build_inputs()
        exported=self.base/'export';exported.mkdir()
        (exported/'custom.bin').write_bytes(b'exported-data')
        archive=self.base/'filemod.zip'
        m.pack_files(exported,self.root,archive,'data','Example export')
        bundle=self.base/'export.pyz';m.build([archive],bundle)
        m.apply(self.root,bundle,'deploy')
        self.assertEqual((self.root/'data/custom.bin').read_bytes(),b'exported-data')
        m.apply(self.root,None,'restore')
        self.assertFalse((self.root/'data/custom.bin').exists())

    def test_bundle_can_rebuild_itself(self):
        import subprocess,sys
        out=self.base/'rebuilt.pyz'
        r=subprocess.run([sys.executable,str(self.bundle),'build',str(self.inputs[0]),'-o',str(out)],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(len(m.package(out)),1)

    def test_remove_one_mod_preserves_other(self):
        m.apply(self.root,self.bundle,'deploy')
        m.apply(self.root,None,'remove','a')
        self.assertEqual((self.root/'data/game/a.dl_bin').read_bytes(),b'original-a')
        self.assertEqual((self.root/'data/game/b.dl_bin').read_bytes(),b'modified-b')
        m.apply(self.root,None,'restore')
        self.assertEqual((self.root/'data/game/b.dl_bin').read_bytes(),b'original-b')

    def test_unguarded_payload_requires_explicit_baseline(self):
        data=b'candidate'
        op=dict(name='Legacy candidate',mod_id='candidate',target='data/game/a.dl_bin',sha256=m.sha(data),baseline_required=True)
        with self.assertRaisesRegex(m.ModError,'local baseline'):
            m.bind_operation(op,data,None)
        self.build_inputs()
        bound=m.bind_operation(op,data,self.root)
        self.assertEqual(bound['before_sha256'],[m.sha(b'original-a')])
        self.assertEqual(set(bound['build_sha256']),set(m.BUILD_HASHES))

if __name__ == '__main__':
    unittest.main()
