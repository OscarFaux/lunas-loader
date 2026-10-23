from pathlib import Path
import base64
import copy
import json
import struct
import sys
import tempfile
import unittest
import zipfile
sys.path.insert(0,str(Path(__file__).parents[1]))
import luna_core as lc
import manager as m
import mod_images
import mod_options as opts

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a0ZkAAAAASUVORK5CYII=')

def patch(value):
    data=bytearray(184);struct.pack_into('<III',data,0,0xf0000011,1,1)
    struct.pack_into('<QQ',data,104,100+value,456);data[-1]=value
    return data

class OptionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.store=lc.Store(self.base/'local/lunas_loader')
        self.game=self.base/'game';(self.game/'data/game').mkdir(parents=True);(self.game/'bin').mkdir()
        for relative in m.BUILD_HASHES:(self.game/relative).write_bytes(('stock '+relative).encode())
        self.manifest=dict(Version=1,Guid='example',Name='Model choices',Description='Choose the model',IconPath='Art/profile.png',Options=[
            dict(Name='Model',Description='The main model',Include=['Common'],SubOptions=[
                dict(Name='Blue',Description='Blue variant',Include=['Variants/Blue']),
                dict(Name='Red',Description='Red variant',Include=['Variants/Red'])]),
            dict(Name='Accessory',Description='Optional extra',Include=['Extra'])])

    def archive(self,manifest=None):
        archive=self.base/'Model.zip'
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('Package/manifest.json',json.dumps(manifest or self.manifest))
            z.writestr('Package/Art/profile.png',PNG)
            for folder,value in [('Common',1),('Variants/Blue',2),('Variants/Red',3),('Extra',4)]:
                z.writestr('Package/'+folder+'/abcdef0123456789.patch_0',patch(value))
                z.writestr('Package/'+folder+'/abcdef0123456789.patch_0.stream',b'')
        return archive

    def values(self,row):
        return [data[-1] for op,data in self.store.static_operations(row,bind=False) if op['target'].endswith('.patch_0')]

    def test_manifest_checkboxes_and_subchoices_filter_actual_payloads(self):
        row=self.store.import_zip(self.archive());self.assertEqual(self.values(row),[1,2,4])
        state=copy.deepcopy(row['option_state']);state[0]['choice']=1;state[1]['enabled']=False
        self.store.set_options(row['id'],state)
        self.assertEqual(self.values(row),[1,3])
        state[0]['enabled']=False
        self.assertTrue(row['option_state'][0]['enabled'])  # Saved state is not aliased to the editor.
        reopened=lc.Store(self.store.home);self.assertEqual(reopened.state['mods'][0]['option_state'][0]['choice'],1)

    def test_selected_components_sharing_archive_keep_separate_slots(self):
        row=self.store.import_zip(self.archive());self.store.set_game(self.game);self.store.deploy()
        mains=[p for p in (self.game/'data').glob('*.patch_*') if p.suffix.rsplit('_',1)[-1].isdigit()]
        self.assertEqual(sorted(p.read_bytes()[-1] for p in mains),[1,2,4])
        selection=copy.deepcopy(row['option_state']);selection[0]['choice']=1;selection[1]['enabled']=False
        self.store.set_options(row['id'],selection);self.store.deploy()
        mains=[p for p in (self.game/'data').glob('*.patch_*') if p.suffix.rsplit('_',1)[-1].isdigit()]
        self.assertEqual(sorted(p.read_bytes()[-1] for p in mains),[1,3])
        self.store.purge();self.assertFalse(list((self.game/'data').glob('*.patch_*')))

    def test_disabled_parent_excludes_common_and_all_variants(self):
        row=self.store.import_zip(self.archive());state=copy.deepcopy(row['option_state']);state[0]['enabled']=False
        self.store.set_options(row['id'],state);self.assertEqual(self.values(row),[4])

    def test_invalid_choice_rejected_without_changing_profile(self):
        row=self.store.import_zip(self.archive());state=copy.deepcopy(row['option_state']);state[0]['choice']=8
        before=self.store.path.read_bytes()
        with self.assertRaises(m.ModError):self.store.set_options(row['id'],state)
        self.assertEqual(before,self.store.path.read_bytes())

    def test_unsafe_include_rejected(self):
        definition=copy.deepcopy(self.manifest);definition['Options'][0]['Include']=['../../outside']
        with self.assertRaisesRegex(m.ModError,'Unsafe option'):self.store.import_zip(self.archive(definition))
        self.assertFalse(self.store.state['mods'])

    def test_manifest_icon_resolves_inside_wrapped_mod_root(self):
        row=self.store.import_zip(self.archive());image=self.store.icon_path(row['id'])
        self.assertEqual(image.read_bytes(),PNG)
        self.assertEqual(row['option_model']['icon'],'Package/Art/profile.png')

    def test_missing_or_unsafe_icon_falls_back_without_blocking_mod(self):
        definition=copy.deepcopy(self.manifest);definition['IconPath']='../../outside.png'
        row=self.store.import_zip(self.archive(definition));self.assertIsNone(self.store.icon_path(row['id']))
        self.assertEqual(self.values(row),[1,2,4])

    def test_old_records_gain_option_defaults_and_image_metadata(self):
        row=self.store.import_zip(self.archive());row.pop('option_model');row.pop('option_state');self.store.save()
        reopened=lc.Store(self.store.home);record=reopened.state['mods'][0]
        self.assertEqual(record['option_state'][0],dict(enabled=True,choice=0))
        self.assertEqual(reopened.icon_path(record['id']).read_bytes(),PNG)

    def test_native_manifest_can_declare_icon(self):
        archive=self.base/'native.zip'
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('unified-mod.json',json.dumps(dict(schema=1,id='native',name='Native',icon='picture.png',files=[])))
            z.writestr('picture.png',PNG)
        row=self.store.import_zip(archive);self.assertEqual(self.store.icon_path(row['id']).read_bytes(),PNG)

    def test_thumbnail_size_and_alpha_preserve_aspect(self):
        self.assertEqual(mod_images.fit_size(200,100), (24,12))
        self.assertEqual(mod_images.fit_size(5,10), (5,10))
        self.assertEqual(mod_images.rgb_pixel(0x00ff0000),bytes((24,53,66)))
        self.assertEqual(mod_images.rgb_pixel(0xffff0000),bytes((255,0,0)))
        with self.assertRaises(ValueError):mod_images.fit_size(100000,100000)

if __name__=='__main__':unittest.main()
