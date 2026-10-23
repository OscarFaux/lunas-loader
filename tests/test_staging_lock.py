from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile
import test_luna as fixtures
import luna_core as lc
import manager as m


class StagingLockTests(unittest.TestCase):
    setUp=fixtures.LunaTests.setUp
    native=fixtures.LunaTests.native

    def configurator(self):
        archive=self.base/'config.zip'
        with zipfile.ZipFile(archive,'w') as z:z.writestr('Config.exe',b'fixture-not-run')
        return self.store.import_zip(archive)

    def test_config_launch_succeeds_when_windows_would_deny_dummy_rename(self):
        row=self.configurator();self.store.set_game(self.game)
        old_inode=self.store.dummy.stat().st_ino
        (self.store.dummy/'unsaved.txt').write_bytes(b'keep in snapshot')
        original=lc.os.rename
        def windows_lock(source,dest,*args,**kwargs):
            if Path(source)==self.store.dummy:raise PermissionError('[WinError 5] Access is denied')
            return original(source,dest,*args,**kwargs)
        with patch.object(lc.os,'rename',windows_lock),patch.object(lc.subprocess,'Popen') as start:
            result=self.store.launch(row['id'])
        start.assert_called_once();self.assertIs(result,start.return_value)
        self.assertEqual(self.store.dummy.stat().st_ino,old_inode)
        self.assertFalse((self.store.dummy/'unsaved.txt').exists())
        self.assertTrue(any((p/'unsaved.txt').read_bytes()==b'keep in snapshot' for p in (self.store.home/'snapshots').iterdir()))
        self.assertEqual(self.store.launch_record['id'],row['id'])

    def test_locked_file_restores_old_dummy_and_does_not_start_exe(self):
        base=self.store.import_zip(self.native());base['enabled']=False
        row=self.configurator();self.store.set_game(self.game)
        marker=self.store.dummy/'unsaved.txt';marker.write_bytes(b'preserve')
        before=lc.staging_files(self.store.dummy);base['enabled']=True
        original=lc.copy_staging_file
        def locked_file(source,destination):
            if destination==self.store.dummy/'data/game/table.dl_bin':raise PermissionError('fixture file locked')
            return original(source,destination)
        with patch.object(lc,'copy_staging_file',locked_file),patch.object(lc.subprocess,'Popen') as start:
            with self.assertRaisesRegex(m.ModError,'Cannot update dummy file:.*table.dl_bin.*Previous dummy contents restored'):
                self.store.launch(row['id'])
        start.assert_not_called();self.assertIsNone(self.store.launch_record)
        self.assertEqual(lc.staging_files(self.store.dummy),before)
        self.assertFalse((self.store.home/'staging/ready.json').exists())
        self.assertEqual((self.game/'data/game/table.dl_bin').read_bytes(),b'original')

    def test_rebuild_retains_directory_handle_and_removes_unsaved_outputs(self):
        self.store.set_game(self.game)
        inode=self.store.dummy.stat().st_ino
        (self.store.dummy/'discard.txt').write_text('discard')
        with patch.object(lc.os,'rename',side_effect=AssertionError('Root rename must not be used')):
            # Baseline rotation still uses rename, so keep that independent step real.
            with patch.object(self.store,'clean_baseline'):
                self.store.rebuild_dummy()
        self.assertEqual(self.store.dummy.stat().st_ino,inode)
        self.assertFalse((self.store.dummy/'discard.txt').exists())
        self.assertFalse(list((self.store.home/'staging').glob('.dummy-backup-*')))

    def test_hardlinked_dummy_file_is_replaced_without_modifying_link_target(self):
        base=self.store.import_zip(self.native());base['enabled']=False;self.store.set_game(self.game)
        external=self.base/'outside';external.write_bytes(b'original')
        path=self.store.dummy/'data/game/table.dl_bin';path.unlink();path.hardlink_to(external)
        base['enabled']=True;self.store.prepare()
        self.assertEqual(path.read_bytes(),b'modded');self.assertEqual(external.read_bytes(),b'original')

    def test_readonly_staged_resource_can_be_updated(self):
        base=self.store.import_zip(self.native());base['enabled']=False;self.store.set_game(self.game)
        path=self.store.dummy/'data/game/table.dl_bin';path.chmod(0o444)
        base['enabled']=True;self.store.prepare()
        self.assertEqual(path.read_bytes(),b'modded')

    def test_unchanged_hardlink_is_broken_before_configurator_can_write(self):
        self.store.set_game(self.game)
        external=self.base/'outside';external.write_bytes(b'original')
        path=self.store.dummy/'data/game/table.dl_bin';path.unlink();path.hardlink_to(external)
        self.store.prepare();path.write_bytes(b'configurator output')
        self.assertEqual(external.read_bytes(),b'original')

    def test_unchanged_readonly_input_becomes_writable_for_configuration(self):
        import stat
        self.store.set_game(self.game)
        path=self.store.dummy/'data/game/table.dl_bin';path.chmod(0o444)
        self.store.prepare()
        self.assertTrue(path.stat().st_mode & stat.S_IWRITE)

    def test_backup_failure_keeps_dummy_intact_and_does_not_start_exe(self):
        row=self.configurator();self.store.set_game(self.game)
        before=lc.staging_files(self.store.dummy)
        original=lc.shutil.copytree
        def denied(source,destination,*args,**kwargs):
            if Path(source)==self.store.dummy:raise PermissionError('fixture backup inaccessible')
            return original(source,destination,*args,**kwargs)
        with patch.object(lc.shutil,'copytree',denied),patch.object(lc.subprocess,'Popen') as start:
            with self.assertRaises(PermissionError):self.store.launch(row['id'])
        start.assert_not_called();self.assertEqual(lc.staging_files(self.store.dummy),before)

    def test_failed_rollback_reports_preserved_snapshot_and_never_launches(self):
        row=self.configurator();self.store.set_game(self.game)
        with patch.object(lc,'sync_staging',side_effect=m.ModError('fixture locked file')),patch.object(lc.subprocess,'Popen') as start:
            with self.assertRaisesRegex(m.ModError,'Rollback could not finish.*Previous dummy saved at.*snapshots'):
                self.store.launch(row['id'])
        start.assert_not_called()
        snapshots=list((self.store.home/'snapshots').iterdir())
        self.assertEqual(len(snapshots),1)
        self.assertEqual(lc.staging_files(snapshots[0]),lc.staging_files(self.store.dummy))
