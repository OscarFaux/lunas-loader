import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0,str(Path(__file__).parents[1]))
import luna_core as lc
import manager as m

class LunaTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.game=self.base/'game';(self.game/'data/game').mkdir(parents=True)
        (self.game/'bin').mkdir()
        (self.game/'bin/helldivers2.exe').write_bytes(b'fixture-exe')
        (self.game/'data/game/game.dll').write_bytes(b'fixture-dll')
        (self.game/'data/game/dl_library.dl_typelib').write_bytes(b'fixture-types')
        (self.game/'data/game/table.dl_bin').write_bytes(b'original')
        self.store=lc.Store(self.base/'localappdata/lunas_loader')

    def native(self,name='Data mod',target='data/game/table.dl_bin',payload=b'modded'):
        path=self.base/(name+'.zip')
        with zipfile.ZipFile(path,'w') as z:
            z.writestr('unified-mod.json',json.dumps(dict(schema=1,id=name,name=name,files=[dict(target=target,payload='payload',sha256=m.sha(payload),before_sha256=[m.sha(b'original')])])) )
            z.writestr('payload',payload)
        return path

    def test_unicode_zip_is_copied_and_library_persists(self):
        path=self.native('模组 config')
        row=self.store.import_zip(path)
        self.assertEqual((self.store.home/'mods'/row['id']/'archive.zip').read_bytes(),path.read_bytes())
        other=lc.Store(self.store.home)
        self.assertEqual(other.state['mods'][0]['name'],'模组 config')

    def test_remove_reimport_preserves_files(self):
        path=self.native();row=self.store.import_zip(path)
        self.store.remove(row['id']);self.assertFalse(self.store.state['mods'])
        again=self.store.import_zip(path);self.assertEqual(again['id'],row['id'])

    def test_complete_deploy_purge_without_losing_library(self):
        self.store.import_zip(self.native());self.store.set_game(self.game)
        self.assertEqual((self.store.dummy/'data/game/table.dl_bin').read_bytes(),b'modded')
        self.assertEqual((self.game/'data/game/table.dl_bin').read_bytes(),b'original')
        self.store.deploy();self.assertEqual((self.game/'data/game/table.dl_bin').read_bytes(),b'modded')
        self.store.purge();self.assertEqual((self.game/'data/game/table.dl_bin').read_bytes(),b'original')
        self.assertEqual(len(self.store.state['mods']),1)
        self.assertTrue(any((self.store.home/'backups').iterdir()))

    def test_redeploy_changed_selection_restores_disabled_mod(self):
        self.store.import_zip(self.native());self.store.set_game(self.game);self.store.deploy()
        for row in self.store.state['mods']:row['enabled']=False
        raw=self.base/'raw.zip'
        with zipfile.ZipFile(raw,'w') as z:z.writestr('mods/new.bin',b'new')
        self.store.import_zip(raw);self.store.deploy()
        self.assertEqual((self.game/'data/game/table.dl_bin').read_bytes(),b'original')
        self.assertEqual((self.game/'mods/new.bin').read_bytes(),b'new')
        self.store.purge();self.assertFalse((self.game/'mods/new.bin').exists())

    def test_configurator_dependencies_are_enforced(self):
        base=self.store.import_zip(self.native())
        raw=self.base/'Config.zip'
        with zipfile.ZipFile(raw,'w') as z:z.writestr('Config/Config.exe',b'fixture-not-run')
        config=self.store.import_zip(raw);self.store.set_game(self.game)
        final,owners=self.store.assembled()
        self.store.launch_record=dict(id=config['id'],before=self.store.file_inventory(),owners=owners)
        (self.store.dummy/'data/game/table.dl_bin').write_bytes(b'base-plus-config')
        self.store.capture()
        final,_=self.store.assembled();self.assertEqual(final['data/game/table.dl_bin'][1],b'base-plus-config')
        base['enabled']=False
        with self.assertRaisesRegex(m.ModError,'base above it'):
            self.store.prepare()

    def test_readonly_build_witness_not_captured(self):
        raw=self.base/'Config.zip'
        with zipfile.ZipFile(raw,'w') as z:z.writestr('Config.exe',b'fixture')
        row=self.store.import_zip(raw);self.store.set_game(self.game)
        self.store.launch_record=dict(id=row['id'],before=self.store.file_inventory(),owners={})
        (self.store.dummy/'data/game/game.dll').write_bytes(b'changed-dll')
        with self.assertRaisesRegex(m.ModError,'read-only build witness'):self.store.capture()

    def test_zip_extraction_rejects_windows_aliases(self):
        raw=self.base/'bad.zip'
        with zipfile.ZipFile(raw,'w') as z:z.writestr('CON.txt',b'x')
        with self.assertRaisesRegex(m.ModError,'Unsafe Windows'):self.store.import_zip(raw)
        self.assertFalse(self.store.state['mods'])

    def test_separate_exe_payload_never_runs_on_import(self):
        raw=self.base/'Config.zip'
        with zipfile.ZipFile(raw,'w') as z:
            z.writestr('Tool/Setup.exe',b'not executable')
            z.writestr('Tool/_internal/python.exe',b'helper')
        with patch.object(lc.subprocess,'Popen') as launch:
            row=self.store.import_zip(raw);self.assertFalse(launch.called)
        self.assertEqual(row['executables'],['Tool/Setup.exe'])

    def test_new_raw_file_removed_by_purge(self):
        raw=self.base/'raw.zip'
        with zipfile.ZipFile(raw,'w') as z:z.writestr('plugins/test/item.bin',b'new')
        self.store.import_zip(raw);self.store.set_game(self.game);self.store.deploy()
        self.assertEqual((self.game/'plugins/test/item.bin').read_bytes(),b'new')
        self.store.purge();self.assertFalse((self.game/'plugins/test/item.bin').exists())

    def test_repeated_import_deduplicates(self):
        path=self.native();self.store.import_zip(path);self.store.import_zip(path)
        self.assertEqual(len(self.store.state['mods']),1)

    def test_exe_sibling_runtime_dll_is_not_a_game_plugin(self):
        raw=self.base/'Config.zip'
        with zipfile.ZipFile(raw,'w') as z:
            z.writestr('Config.exe',b'fixture')
            z.writestr('VCRUNTIME140.dll',b'runtime-library')
        row=self.store.import_zip(raw)
        self.assertEqual(self.store.static_operations(row,bind=False),[])

    def test_arsenal_legacy_files_do_not_block_dummy_deploy_or_purge(self):
        self.store.import_zip(self.native())
        external=self.game/'data/9ba626afa44a3aa3.patch_4'
        external.write_bytes(b'external-boot-owned-by-arsenal')
        state=self.game/'HD2FileMods.state';state.write_text('data/game/unrelated.dl_bin|external|x|y\n')
        self.store.set_game(self.game);self.store.prepare();self.store.deploy();self.store.purge()
        self.assertEqual(external.read_bytes(),b'external-boot-owned-by-arsenal')
        self.assertEqual(state.read_text(),'data/game/unrelated.dl_bin|external|x|y\n')

    def test_bottom_file_mod_wins_and_reordering_persists(self):
        one=self.store.import_zip(self.native('First',payload=b'first'))
        two=self.store.import_zip(self.native('Last',payload=b'last'))
        self.store.set_game(self.game)
        self.assertEqual((self.store.dummy/'data/game/table.dl_bin').read_bytes(),b'last')
        self.store.move_mod(one['id'],1);self.store.prepare()
        self.assertEqual((self.store.dummy/'data/game/table.dl_bin').read_bytes(),b'first')
        reopened=lc.Store(self.store.home)
        self.assertEqual([r['id'] for r in reopened.state['mods']],[two['id'],one['id']])

    def patch_zip(self,name,value):
        import struct
        payload=bytearray(184);struct.pack_into('<III',payload,0,0xf0000011,1,1)
        struct.pack_into('<QQ',payload,104,123,456);payload[-1]=value
        archive=self.base/(name+'.zip')
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('abcdef0123456789.patch_0',payload)
            z.writestr('abcdef0123456789.patch_0.stream',b'')
            z.writestr('abcdef0123456789.patch_0.gpu_resources',b'')
        return archive

    def test_patch_slots_preserve_arsenal_and_order_companions(self):
        external=self.game/'data/abcdef0123456789.patch_7';external.write_bytes(b'arsenal')
        a=self.store.import_zip(self.patch_zip('Patch A',1));b=self.store.import_zip(self.patch_zip('Patch B',2))
        self.store.set_game(self.game);self.store.deploy()
        self.assertEqual(external.read_bytes(),b'arsenal')
        self.assertEqual((self.game/'data/abcdef0123456789.patch_8').read_bytes()[-1],1)
        self.assertEqual((self.game/'data/abcdef0123456789.patch_9').read_bytes()[-1],2)
        self.assertTrue((self.game/'data/abcdef0123456789.patch_9.stream').exists())
        self.store.move_mod(b['id'],0);self.store.deploy()
        self.assertEqual((self.game/'data/abcdef0123456789.patch_8').read_bytes()[-1],2)
        self.assertEqual((self.game/'data/abcdef0123456789.patch_9').read_bytes()[-1],1)
        self.store.purge();self.assertEqual(external.read_bytes(),b'arsenal')
        self.assertFalse((self.game/'data/abcdef0123456789.patch_8').exists())
        self.assertFalse((self.game/'data/abcdef0123456789.patch_9.stream').exists())

    def test_configuration_preview_uses_only_earlier_rows(self):
        raw=self.base/'Config.zip'
        with zipfile.ZipFile(raw,'w') as z:z.writestr('Config.exe',b'fixture')
        config=self.store.import_zip(raw)
        self.store.import_zip(self.native('Later',payload=b'later'))
        self.store.set_game(self.game);self.store.prepare(stop_after=config['id'])
        self.assertEqual((self.store.dummy/'data/game/table.dl_bin').read_bytes(),b'original')
        self.store.prepare();self.assertEqual((self.store.dummy/'data/game/table.dl_bin').read_bytes(),b'later')

    def test_upgrade_reserves_external_patch_restored_by_old_deployment(self):
        original_zip=self.patch_zip('Original external',9)
        with zipfile.ZipFile(original_zip) as z:before=z.read('abcdef0123456789.patch_0')
        target='data/abcdef0123456789.patch_0';(self.game/target).write_bytes(before)
        old_payload_zip=self.patch_zip('Old loader',1)
        with zipfile.ZipFile(old_payload_zip) as z:payload=z.read('abcdef0123456789.patch_0')
        old_native=self.base/'old-native.zip'
        with zipfile.ZipFile(old_native,'w') as z:
            z.writestr('unified-mod.json',json.dumps(dict(schema=1,id='old',name='old',files=[dict(
                target=target,payload='payload',sha256=m.sha(payload),before_sha256=[m.sha(before)])])))
            z.writestr('payload',payload)
        old_bundle=self.base/'old.pyz';m.build([old_native],old_bundle);m.apply(self.game,old_bundle,'deploy')
        self.store.import_zip(self.patch_zip('New selection',2));self.store.set_game(self.game);self.store.deploy()
        self.assertEqual((self.game/target).read_bytes()[-1],9)
        self.assertEqual((self.game/'data/abcdef0123456789.patch_1').read_bytes()[-1],2)
        self.store.purge();self.assertEqual((self.game/target).read_bytes()[-1],9)

if __name__=='__main__':unittest.main()
