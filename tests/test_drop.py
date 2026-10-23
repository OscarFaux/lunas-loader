"""Exercise the native-handler boundary without requiring Windows or a Tk display."""
from pathlib import Path
import queue
import sys
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]))
import gui

class Shell:
    def __init__(self,paths):self.paths=paths;self.finished=[];self.handles=[];self.accepted=[]
    def DragQueryFileW(self,handle,index,buffer,count):
        self.handles.append(handle)
        if index==0xffffffff:return len(self.paths)
        value=self.paths[index]
        if buffer is None:return len(value)
        buffer.value=value
        return len(value)
    def DragFinish(self,handle):self.finished.append(handle)
    def DragAcceptFiles(self,hwnd,flag):self.accepted.append((hwnd,flag))

class Common:
    def __init__(self):self.removed=[];self.forwarded=[]
    def RemoveWindowSubclass(self,*args):self.removed.append(args);return True
    def DefSubclassProc(self,*args):self.forwarded.append(args);return 0x123456789ab

class DropTests(unittest.TestCase):
    def make_drop(self,paths):
        drop=gui.WindowsDrop.__new__(gui.WindowsDrop)
        drop.events=queue.Queue();drop.shell=Shell(paths);drop.common=Common()
        drop.installed=True;drop.hwnd=0x123456789ab;drop.proc=object();drop.subclass_id=0x4c554e41
        calls=[];drop.callback=lambda p,e:calls.append((p,e))
        return drop,calls

    def test_drop_never_calls_ui_until_timer_drains_queue(self):
        paths=[r'C:\Mods\stayput.zip',r'C:\Mods\模组.zip']
        drop,calls=self.make_drop(paths);handle=0x1abcdef123456
        self.assertEqual(drop._dispatch(drop.hwnd,drop.WM_DROPFILES,handle,0,drop.subclass_id,0),0)
        self.assertEqual(calls,[])
        self.assertEqual(drop.shell.finished,[handle])
        self.assertTrue(all(h==handle for h in drop.shell.handles))
        drop.drain();self.assertEqual(calls,[(paths,None)])
        drop.drain();self.assertEqual(len(calls),1)

    def test_read_error_releases_handle_and_reports_after_return(self):
        drop,calls=self.make_drop(['example.zip'])
        def fail(*args):raise OSError('simulated shell error')
        drop.shell.DragQueryFileW=fail
        self.assertEqual(drop._dispatch(drop.hwnd,drop.WM_DROPFILES,123,0,drop.subclass_id,0),0)
        self.assertEqual(drop.shell.finished,[123]);self.assertFalse(calls)
        drop.drain();self.assertIn('simulated shell error',calls[0][1]);self.assertEqual(calls[0][0],[])

    def test_default_result_and_pointer_values_preserved(self):
        drop,_=self.make_drop([])
        result=drop._dispatch(drop.hwnd,0x20,0x1abcdef12345,-0x123456789,drop.subclass_id,0)
        self.assertEqual(result,0x123456789ab)
        self.assertEqual(drop.common.forwarded[0],(drop.hwnd,0x20,0x1abcdef12345,-0x123456789))

    def test_destroy_detaches_subclass_before_forwarding(self):
        drop,_=self.make_drop([])
        drop._dispatch(drop.hwnd,drop.WM_NCDESTROY,0,0,drop.subclass_id,0)
        self.assertFalse(drop.installed);self.assertEqual(len(drop.common.removed),1)
        self.assertEqual(len(drop.common.forwarded),1)

    def test_close_is_idempotent_and_keeps_callback_alive(self):
        drop,_=self.make_drop([]);callback=drop.proc
        drop.close();drop.close()
        self.assertEqual(drop.shell.accepted,[(drop.hwnd,False)])
        self.assertEqual(len(drop.common.removed),1);self.assertIs(drop.proc,callback)

    def test_invalid_count_rejected_and_finished_once(self):
        drop,calls=self.make_drop([])
        drop._dispatch(drop.hwnd,drop.WM_DROPFILES,123,0,drop.subclass_id,0)
        self.assertEqual(drop.shell.finished,[123]);drop.drain()
        self.assertIn('1,000',calls[0][1])

    def test_callback_boundary_contains_failure(self):
        drop,calls=self.make_drop([])
        def fail(*args):raise RuntimeError('simulated forwarding error')
        drop.common.DefSubclassProc=fail
        self.assertEqual(drop._dispatch(drop.hwnd,0x20,0,0,drop.subclass_id,0),0)
        drop.drain();self.assertIn('simulated forwarding error',calls[0][1])

if __name__=='__main__':unittest.main()
