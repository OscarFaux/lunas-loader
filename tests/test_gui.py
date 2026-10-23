from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]))
import gui

class Canvas:
    def __init__(self,w,h):self.w=w;self.h=h;self.calls=[]
    def winfo_width(self):return self.w
    def winfo_height(self):return self.h
    def delete(self,*a):self.calls=[]
    def create_rectangle(self,*a,**k):self.calls.append(('rectangle',a,k))
    def create_text(self,*a,**k):self.calls.append(('text',a,k))
    def create_line(self,*a,**k):self.calls.append(('line',a,k))
    def create_oval(self,*a,**k):self.calls.append(('oval',a,k))
    def create_image(self,*a,**k):self.calls.append(('image',a,k))

class Font:
    def __init__(self,size,bold=False):self.size=size;self.bold=bold
    def measure(self,s):return len(s)*self.size*.7

class Store:
    state={'mods':[dict(id='1',name='Example file mod',enabled=True,executables=[],configurations=[]),
                   dict(id='2',name='Example configurator',enabled=True,executables=['Tool.exe'],configurations=[])],
           'game_root':'D:/Games/Helldivers 2'}
    dummy=Path('C:/Users/Oscar/AppData/Local/lunas_loader/staging/dummy_game')

class GuiTests(unittest.TestCase):
    def make_app(self,w,h):
        app=gui.App.__new__(gui.App);app.canvas=Canvas(w,h);app.font=lambda s=11,b=False:Font(s,b)
        app.store=Store();app.offset=0;app.selected='2';app.logs=['Ready.'];app.status='Drop mod ZIPs here.'
        app.busy=False;app.process=None
        app.draw();return app

    def test_text_is_cyan_with_green_outline_passes(self):
        app=self.make_app(1100,840)
        texts=[c for c in app.canvas.calls if c[0]=='text']
        self.assertTrue(texts)
        self.assertEqual(len(texts)%9,0)
        for i in range(0,len(texts),9):
            self.assertTrue(all(c[2]['fill']==gui.GREEN for c in texts[i:i+8]))
            self.assertEqual(texts[i+8][2]['fill'],gui.CYAN)

    def test_minimum_size_buttons_do_not_overlap(self):
        app=self.make_app(920,740)
        for i,(x,y,x2,y2,_) in enumerate(app.buttons):
            self.assertTrue(0<=x<x2<=920 and 0<=y<y2<=740)
            for xx,yy,xx2,yy2,_ in app.buttons[i+1:]:
                self.assertFalse(max(x,xx)<min(x2,xx2) and max(y,yy)<min(y2,yy2))

    def test_gradient_and_expected_generic_actions_render(self):
        app=self.make_app(1100,840)
        rectangles=[c for c in app.canvas.calls if c[0]=='rectangle']
        self.assertNotEqual(rectangles[0][2]['fill'],rectangles[200][2]['fill'])
        labels=[c[2]['text'] for c in app.canvas.calls if c[0]=='text']
        self.assertIn("Luna's Modloader",labels)
        self.assertNotIn('Your mods. One library. A clean way back.',labels)
        self.assertIn('Deploy',labels);self.assertIn('Purge',labels);self.assertIn('Copy path',labels)
        self.assertFalse(any('ArmorWorkbench' in text for text in labels))

    def test_icon_drag_changes_order_on_release_not_click(self):
        import copy
        from types import SimpleNamespace
        app=self.make_app(1100,840);app.store=Store();app.store.state=copy.deepcopy(Store.state)
        app.schedule=lambda *args:None
        moves=[]
        def move(identity,index):
            rows=app.store.state['mods'];row=next(r for r in rows if r['id']==identity)
            rows.remove(row);rows.insert(index,row);moves.append((identity,index))
        app.store.move_mod=move
        app.click(SimpleNamespace(x=85,y=332))
        self.assertEqual(moves,[])
        app.drag_motion(SimpleNamespace(x=86,y=430))
        self.assertTrue(app.drag['active'])
        app.drag_release(SimpleNamespace(x=86,y=430))
        self.assertEqual(moves,[('1',1)])
        self.assertEqual([r['id'] for r in app.store.state['mods']],['2','1'])
        self.assertIn('Deploy',app.status)

    def test_icon_click_without_drag_keeps_order(self):
        from types import SimpleNamespace
        app=self.make_app(1100,840);app.schedule=lambda *args:None
        app.click(SimpleNamespace(x=85,y=332))
        app.drag_motion(SimpleNamespace(x=86,y=333))
        app.drag_release(SimpleNamespace(x=86,y=333))
        self.assertIsNone(app.drag)

    def make_dialog(self,exe=False):
        import copy
        dialog=gui.ModDialog.__new__(gui.ModDialog)
        dialog.exe=exe;dialog.canvas=Canvas(790,620 if not exe else 390)
        dialog.font=lambda s=11,b=False:Font(s,b);dialog.row=copy.deepcopy(Store.state['mods'][1])
        dialog.app=type('Owner',(),{'store':Store()})()
        dialog.definition=dict(description='Choose',options=[dict(name='Body model',description='Main model',include=['Common'],choices=[
            dict(name='Blue',description='Blue material',include=['Blue']),
            dict(name='Red',description='Red material',include=['Red'])])])
        dialog.selections=[dict(enabled=True,choice=0)];dialog.scroll_y=0;dialog.closed=False
        dialog.redraw=None;dialog.buttons=[];dialog.schedule=lambda *a:None
        dialog.draw();return dialog

    def test_exe_prompt_displays_full_dummy_path_and_launch_controls(self):
        dialog=self.make_dialog(exe=True)
        labels=[c[2]['text'] for c in dialog.canvas.calls if c[0]=='text']
        self.assertIn(str(Store.dummy),labels)
        self.assertIn('Copy path',labels);self.assertIn('Copy and launch',labels)
        self.assertTrue(any('Paste this dummy directory' in text for text in labels))

    def test_manifest_dialog_has_checkboxes_single_choice_and_descriptions(self):
        dialog=self.make_dialog()
        labels=[c[2]['text'] for c in dialog.canvas.calls if c[0]=='text']
        for label in ('Body model','Blue','Red','Blue material','Save options'):self.assertIn(label,labels)
        self.assertTrue(any(c[0]=='oval' for c in dialog.canvas.calls))
        dialog.toggle_option(0);self.assertFalse(dialog.selections[0]['enabled'])
        dialog.choose(0,1);self.assertEqual(dialog.selections[0]['choice'],1)

    def test_profile_image_is_cached_with_strong_reference(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'icon.png';path.write_bytes(b'icon')
            app=self.make_app(1100,840);app.store.icon_path=lambda identity:path
            row=dict(id='picture',option_model={'icon':'icon.png'})
            image=object()
            with patch.object(gui.mod_images,'thumbnail',return_value=image) as decode:
                self.assertIs(app.profile_image(row),image);self.assertIs(app.profile_image(row),image)
                self.assertEqual(decode.call_count,1)
            self.assertIn(image,app.images.values())

    def test_invalid_image_decoder_falls_back_without_ui_exception(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'bad.png';path.write_bytes(b'bad')
            app=self.make_app(1100,840);app.store.icon_path=lambda identity:path
            with patch.object(gui.mod_images,'thumbnail',side_effect=RuntimeError('bad image')):
                self.assertIsNone(app.profile_image(dict(id='bad',option_model={'icon':'bad.png'})))

    def test_row_uses_image_instead_of_letter_when_available(self):
        app=self.make_app(1100,840);image=object()
        app.profile_image=lambda row:image if row['id']=='1' else None
        app.draw()
        self.assertTrue(any(c[0]=='image' and c[2]['image'] is image for c in app.canvas.calls))
        labels=[c[2]['text'] for c in app.canvas.calls if c[0]=='text']
        self.assertNotIn('M',labels);self.assertIn('E',labels);self.assertIn('Configure',labels)

    def test_configure_opens_correct_dialog_without_starting_exe(self):
        from unittest.mock import patch
        app=self.make_app(1100,840);app.store.mod=lambda identity:next(r for r in app.store.state['mods'] if r['id']==identity)
        with patch.object(gui,'ModDialog',return_value=object()) as dialog:
            app.configure('1');self.assertFalse(dialog.call_args.kwargs['exe'])
            app.dialog=None;app.configure('2');self.assertTrue(dialog.call_args.kwargs['exe'])

if __name__=='__main__':unittest.main()
