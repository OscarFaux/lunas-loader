import json
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile
import test_luna as fixtures
import luna_core as lc
import manager as m
import gui


class RepairTests(unittest.TestCase):
    setUp=fixtures.LunaTests.setUp
    native=fixtures.LunaTests.native

    def configurator(self):
        archive=self.base/'config.zip'
        with zipfile.ZipFile(archive,'w') as z:z.writestr('Config.exe',b'fixture-not-run')
        return self.store.import_zip(archive)

    def test_miker_helpers_remain_local_and_existing_helpers_are_untouched(self):
        row=self.configurator()
        helper=self.game/'data/game/table.dl_bin.MikerPairs.json';helper.write_bytes(b'external config')
        self.store.set_game(self.game)
        self.store.launch_record=dict(id=row['id'],before=self.store.file_inventory(),owners={})
        for suffix in ('MikerPairs.json','MikerPairs.original','original'):
            (self.store.dummy/('data/game/table.dl_bin.'+suffix)).write_bytes(b'private helper')
        (self.store.dummy/'data/game/table.dl_bin').write_bytes(b'configured')
        self.store.capture()
        self.assertEqual([s['operation']['target'] for s in row['configurations']],['data/game/table.dl_bin'])
        self.store.deploy()
        self.assertEqual(helper.read_bytes(),b'external config')
        self.assertEqual((self.game/'data/game/table.dl_bin').read_bytes(),b'configured')
        self.assertFalse((self.game/'data/game/table.dl_bin.MikerPairs.original').exists())

    def test_previously_captured_helper_is_ignored_without_losing_record(self):
        row=self.configurator();self.store.set_game(self.game)
        target='data/game/table.dl_bin.MikerPairs.json'
        row['configurations']=[dict(operation=dict(target=target,sha256=m.sha(b'old'),before_missing=True))]
        (self.game/target).write_bytes(b'someone elses config')
        self.store.prepare()
        final,_=self.store.assembled();self.assertFalse(final)
        self.assertEqual(len(row['configurations']),1)

    def test_rebuild_discards_unsaved_files_and_preserves_saved_options(self):
        row=self.store.import_zip(self.native());self.store.set_game(self.game)
        (self.store.dummy/'unsaved.txt').write_text('temporary')
        before=json.dumps(self.store.state,sort_keys=True)
        snapshots=list((self.store.home/'snapshots').iterdir())
        self.store.rebuild_dummy()
        self.assertFalse((self.store.dummy/'unsaved.txt').exists())
        self.assertEqual((self.store.dummy/'data/game/table.dl_bin').read_bytes(),b'modded')
        self.assertEqual((self.game/'data/game/table.dl_bin').read_bytes(),b'original')
        self.assertEqual(json.dumps(self.store.state,sort_keys=True),before)
        self.assertEqual(list((self.store.home/'snapshots').iterdir()),snapshots)

    def test_failed_rebuild_keeps_old_dummy(self):
        self.store.set_game(self.game)
        marker=self.store.dummy/'unsaved.txt';marker.write_text('keep')
        with patch.object(self.store,'assembled',side_effect=m.ModError('bad mod')):
            with self.assertRaisesRegex(m.ModError,'bad mod'):self.store.rebuild_dummy()
        self.assertEqual(marker.read_text(),'keep')

    def test_rebuild_refuses_link_and_preserves_destination(self):
        self.store.set_game(self.game)
        external=self.base/'external';external.mkdir();(external/'keep').write_text('keep')
        (self.store.dummy/'link').symlink_to(external,target_is_directory=True)
        with self.assertRaisesRegex(m.ModError,'contains a link'):self.store.rebuild_dummy()
        self.assertEqual((external/'keep').read_text(),'keep')

    def test_reset_backs_up_deployed_resource_and_preserves_arsenal(self):
        row=self.store.import_zip(self.native());self.store.set_game(self.game);self.store.deploy()
        external=self.game/'data/abcdef.patch_7';external.write_bytes(b'arsenal')
        with patch.object(lc,'request_steam_verification') as request:self.store.reset_game_files()
        request.assert_called_once_with()
        pending=self.store.state['repair_pending']
        backup=Path(pending['backup'])
        self.assertEqual((backup/'files/data/game/table.dl_bin').read_bytes(),b'modded')
        self.assertEqual((backup/'files/bin/helldivers2.exe').read_bytes(),b'fixture-exe')
        self.assertFalse((self.game/'bin/helldivers2.exe').exists())
        self.assertFalse((self.game/'data/game/table.dl_bin').exists())
        self.assertEqual(external.read_bytes(),b'arsenal')
        with m.locked(self.game) as state:self.assertFalse(m.records(self.game,state))
        with self.assertRaisesRegex(m.ModError,'Finish Steam verification'):self.store.prepare()
        with self.assertRaisesRegex(m.ModError,'Confirm'):self.store.rebuild_dummy()
        with self.assertRaisesRegex(m.ModError,'Steam has not restored'):self.store.rebuild_dummy(steam_finished=True)
        # Fixture restoration simulates Steam completion; no Steam process is run.
        for rel in pending['targets']:
            dest=self.game/rel;dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes((backup/'files'/rel).read_bytes())
        row['enabled']=False;self.store.save()
        self.store.rebuild_dummy(steam_finished=True)
        self.assertNotIn('repair_pending',self.store.state)
        self.assertEqual(external.read_bytes(),b'arsenal')

    def test_reset_backup_failure_does_not_delete_files(self):
        self.store.set_game(self.game)
        with patch.object(m,'write_atomic',side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError,'disk full'):self.store.reset_game_files()
        self.assertEqual((self.game/'bin/helldivers2.exe').read_bytes(),b'fixture-exe')
        self.assertNotIn('repair_pending',self.store.state)

    def test_interrupted_reset_resumes_and_reuses_verified_backup(self):
        row=self.configurator();self.store.set_game(self.game)
        row['configurations']=[dict(operation=dict(target='data/game/table.dl_bin'))]
        original=Path.unlink
        def interrupt(path,*args,**kwargs):
            if path==self.game/'data/game/game.dll':raise PermissionError('locked fixture')
            return original(path,*args,**kwargs)
        with patch.object(Path,'unlink',interrupt):
            with self.assertRaisesRegex(PermissionError,'locked fixture'):self.store.reset_game_files()
        self.assertEqual(self.store.state['repair_pending']['phase'],'removing')
        backup=self.store.state['repair_pending']['backup']
        self.store=lc.Store(self.store.home)
        with patch.object(lc,'request_steam_verification'):self.store.reset_game_files()
        self.assertEqual(self.store.state['repair_pending']['backup'],backup)
        self.assertEqual(self.store.state['repair_pending']['phase'],'waiting')
        self.assertFalse(self.store.mod(row['id'])['configurations'])

    def test_reset_retry_refuses_external_change_and_keeps_backup(self):
        self.store.set_game(self.game)
        original=Path.unlink
        def interrupt(path,*args,**kwargs):
            if path==self.game/'data/game/game.dll':raise PermissionError('locked fixture')
            return original(path,*args,**kwargs)
        with patch.object(Path,'unlink',interrupt):
            with self.assertRaises(PermissionError):self.store.reset_game_files()
        (self.game/'data/game/game.dll').write_bytes(b'external change')
        with self.assertRaisesRegex(m.ModError,'changed since reset backup'):self.store.reset_game_files()
        self.assertEqual((self.game/'data/game/game.dll').read_bytes(),b'external change')

    def test_failed_steam_handoff_retains_repair_journal_for_manual_verify(self):
        self.store.set_game(self.game)
        with patch.object(lc,'request_steam_verification',side_effect=OSError('no handler')):self.store.reset_game_files()
        self.assertEqual(self.store.state['repair_pending']['phase'],'waiting')
        with patch.object(lc,'request_steam_verification') as request:self.store.reset_game_files()
        request.assert_called_once_with()

    def test_steam_request_uses_fixed_helldivers_appid(self):
        with patch.object(lc.os,'name','nt'),patch.object(lc.os,'startfile',create=True) as start:
            lc.request_steam_verification()
        start.assert_called_once_with('steam://validate/553850')

    def test_gui_cancel_never_deletes_and_confirmation_runs_reset(self):
        from unittest.mock import Mock
        app=gui.App.__new__(gui.App);app.store=Mock();app.root=Mock()
        app.available=lambda:True;app.store.state={}
        app.store.reset_targets.return_value=['bin/helldivers2.exe']
        app.run=lambda fn,callback=None:callback(fn()) if callback else fn()
        with patch.object(gui.messagebox,'askyesno',return_value=False):app.reset_game_files()
        app.store.reset_game_files.assert_not_called()
        with patch.object(gui.messagebox,'askyesno',return_value=True) as prompt:app.reset_game_files()
        self.assertIn('bin/helldivers2.exe',prompt.call_args.args[1])
        app.store.reset_game_files.assert_called_once_with(reviewed_targets=['bin/helldivers2.exe'])

    def test_gui_rebuild_confirmation_for_steam_completion(self):
        from unittest.mock import Mock
        app=gui.App.__new__(gui.App);app.store=Mock();app.root=Mock()
        app.available=lambda:True;app.store.state={'repair_pending':{'phase':'waiting'}}
        app.run=lambda fn:fn()
        with patch.object(gui.messagebox,'askyesno',return_value=False):app.rebuild_dummy()
        app.store.rebuild_dummy.assert_not_called()
        with patch.object(gui.messagebox,'askyesno',return_value=True):app.rebuild_dummy()
        app.store.rebuild_dummy.assert_called_once_with(steam_finished=True)

    def test_saved_configuration_target_is_copied_into_baseline(self):
        row=self.configurator()
        target='mods/config.json';path=self.game/target;path.parent.mkdir(exist_ok=True);path.write_bytes(b'original config')
        payload=b'configured';h=m.sha(payload)
        folder=self.store.home/'mods'/row['id']/'configured';folder.mkdir();(folder/h).write_bytes(payload)
        row['configurations']=[dict(operation=dict(target=target,sha256=h,name=row['name'],mod_id=row['id'],before_sha256=[m.sha(b'original config')]),dependencies=[])]
        self.store.set_game(self.game)
        self.assertEqual((self.store.baseline/target).read_bytes(),b'original config')
        self.store.deploy();self.assertEqual(path.read_bytes(),payload)
        self.store.purge();self.assertEqual(path.read_bytes(),b'original config')

    def test_reset_refuses_new_targets_after_review(self):
        self.store.set_game(self.game)
        with self.assertRaisesRegex(m.ModError,'Reset targets changed'):
            self.store.reset_game_files(reviewed_targets=['bin/helldivers2.exe'])
        self.assertTrue((self.game/'bin/helldivers2.exe').is_file())
        self.assertNotIn('repair_pending',self.store.state)
