"""Canvas UI: cyan lettering with fine green strokes, dark pink/blue gradient."""
import contextlib
import ctypes
from pathlib import Path
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, font as tkfont
import traceback
import luna_core
import copy
import mod_images
import manager

CYAN='#00ffff'
GREEN='#17a95b'
PANEL='#0b172a'


class WindowsDrop:
    """Keep native drop handling separate from Tcl and the import/UI code.

    The native procedure only copies paths, releases the HDROP and queues an
    event. App.poll delivers it after Windows has unwound the callback.
    """
    WM_DROPFILES=0x233
    WM_NCDESTROY=0x82

    def __init__(self, root, callback):
        self.callback=callback;self.events=queue.Queue();self.installed=False
        self.hwnd=None;self.proc=None;self.subclass_id=0x4c554e41
        if os.name!='nt':return
        self.user=ctypes.WinDLL('user32',use_last_error=True)
        self.shell=ctypes.WinDLL('shell32',use_last_error=True)
        self.common=ctypes.WinDLL('comctl32',use_last_error=True)
        # Explicit pointer-width ABI types: HWND/WPARAM/LPARAM must not truncate
        # a 64-bit drop handle. Message IDs and BOOL remain 32-bit.
        handle=ctypes.c_void_p;uint=ctypes.c_uint32;uptr=ctypes.c_size_t;iptr=ctypes.c_ssize_t
        CALLBACK=ctypes.WINFUNCTYPE(iptr,handle,uint,uptr,iptr,uptr,uptr)
        self.proc=CALLBACK(self._dispatch)
        self.user.GetAncestor.argtypes=[handle,uint];self.user.GetAncestor.restype=handle
        self.common.SetWindowSubclass.argtypes=[handle,CALLBACK,uptr,uptr]
        self.common.SetWindowSubclass.restype=ctypes.c_int32
        self.common.RemoveWindowSubclass.argtypes=[handle,CALLBACK,uptr]
        self.common.RemoveWindowSubclass.restype=ctypes.c_int32
        self.common.DefSubclassProc.argtypes=[handle,uint,uptr,iptr]
        self.common.DefSubclassProc.restype=iptr
        self.shell.DragAcceptFiles.argtypes=[handle,ctypes.c_int32];self.shell.DragAcceptFiles.restype=None
        self.shell.DragQueryFileW.argtypes=[handle,uint,ctypes.c_wchar_p,uint]
        self.shell.DragQueryFileW.restype=uint
        self.shell.DragFinish.argtypes=[handle];self.shell.DragFinish.restype=None
        self.hwnd=self.user.GetAncestor(root.winfo_id(),2)
        if not self.hwnd:raise OSError('Could not find the top-level drop window')
        if not self.common.SetWindowSubclass(self.hwnd,self.proc,self.subclass_id,0):
            raise OSError('Windows could not register the file-drop handler')
        self.installed=True
        self.shell.DragAcceptFiles(self.hwnd,True)

    def _drop(self,handle):
        paths=[];error=None
        try:
            count=self.shell.DragQueryFileW(handle,0xffffffff,None,0)
            if not 0<count<=1000:raise ValueError('Drop between one and 1,000 files at a time')
            for n in range(count):
                length=self.shell.DragQueryFileW(handle,n,None,0)
                if not 0<length<=32767:raise ValueError('Windows returned an invalid dropped path')
                text=ctypes.create_unicode_buffer(length+1)
                copied=self.shell.DragQueryFileW(handle,n,text,length+1)
                if copied!=length:raise ValueError('Windows could not read a complete dropped path')
                paths.append(text.value)
        except Exception as exc:
            paths=[];error='File drop failed: '+str(exc)
        finally:
            try:self.shell.DragFinish(handle)
            except Exception as exc:
                paths=[];error='Could not release dropped files: '+str(exc)
        self.events.put((paths,error))

    def _dispatch(self,hwnd,msg,wp,lp,subclass_id,reference):
        # Never call Tk, root.after, import code or a user callback here.
        try:
            if msg==self.WM_DROPFILES:
                self._drop(wp)
                return 0
            if msg==self.WM_NCDESTROY:
                self.common.RemoveWindowSubclass(hwnd,self.proc,self.subclass_id)
                self.installed=False
            return self.common.DefSubclassProc(hwnd,msg,wp,lp)
        except BaseException as exc:
            # An exception must never cross a ctypes/native callback boundary.
            self.events.put(([],'Windows drop handler error: '+str(exc)))
            return 0

    def drain(self):
        """Called exclusively by the ordinary Tk poll timer, not the native hook."""
        while True:
            try:paths,error=self.events.get_nowait()
            except queue.Empty:return
            self.callback(paths,error)

    def close(self):
        if self.installed:
            self.shell.DragAcceptFiles(self.hwnd,False)
            if self.common.RemoveWindowSubclass(self.hwnd,self.proc,self.subclass_id):
                self.installed=False
            # Keep proc strongly referenced through window destruction, even if
            # removal failed. WM_NCDESTROY also detaches the subclass.


class App:
    def __init__(self,root,store=None):
        self.root=root;self.store=store or luna_core.Store()
        root.title(luna_core.TITLE);root.geometry('1100x840');root.minsize(920,740)
        root.configure(bg='#160f29')
        icon=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'luna.ico'
        if os.name=='nt' and icon.exists():
            try:root.iconbitmap(str(icon))
            except tk.TclError:pass
        self.canvas=tk.Canvas(root,highlightthickness=0,bd=0,bg='#160f29')
        self.canvas.pack(fill='both',expand=True)
        self.fonts={};self.buttons=[];self.rows=[];self.logs=[];self.partial=''
        self.events=queue.Queue();self.busy=False;self.process=None;self.selected=None;self.offset=0
        self.status='Drop mod ZIPs anywhere in this window.';self.pending_draw=False;self.drag=None;self.dialog=None;self.images={}
        self.canvas.bind('<Configure>',self.schedule)
        self.canvas.bind('<Button-1>',self.click)
        self.canvas.bind('<Double-Button-1>',self.double_click)
        self.canvas.bind('<B1-Motion>',self.drag_motion)
        self.canvas.bind('<ButtonRelease-1>',self.drag_release)
        self.canvas.bind('<MouseWheel>',self.scroll)
        self.canvas.bind('<Button-4>',lambda e:self.scroll(e,-1))
        self.canvas.bind('<Button-5>',lambda e:self.scroll(e,1))
        root.bind('<Control-o>',lambda e:self.add())
        root.bind('<Control-c>',lambda e:self.copy_dummy())
        root.bind('<Delete>',lambda e:self.remove_selected())
        root.protocol('WM_DELETE_WINDOW',self.close)
        root.update_idletasks()
        try:self.drop=WindowsDrop(root,self.dropped)
        except Exception as e:
            self.drop=None;self.log('Windows drop registration failed: '+str(e)+'. Use Add ZIPs.')
        self.log('Library: '+str(self.store.home))
        self.log('ZIPs are imported as files. Double-click explicitly launches that mod’s configuration EXE.')
        root.after(100,self.poll);self.draw()

    def font(self,size=11,bold=False):
        key=(size,bold)
        if key not in self.fonts:self.fonts[key]=tkfont.Font(family='Segoe UI',size=size,weight='bold' if bold else 'normal')
        return self.fonts[key]

    def text(self,x,y,value,size=11,bold=False,anchor='nw',width=None):
        options=dict(text=str(value),font=self.font(size,bold),anchor=anchor)
        if width:options['width']=width
        for dx,dy in [(-.55,0),(.55,0),(0,-.55),(0,.55),(-.4,-.4),(.4,.4),(-.4,.4),(.4,-.4)]:
            self.canvas.create_text(x+dx,y+dy,fill=GREEN,**options)
        return self.canvas.create_text(x,y,fill=CYAN,**options)

    def fit(self,value,width,size=10):
        value=str(value);f=self.font(size)
        if f.measure(value)<=width:return value
        while value and f.measure(value+'…')>width:value=value[:-1]
        return value+'…'

    def button(self,x,y,w,label,action,h=35,accent=False):
        self.canvas.create_rectangle(x,y,x+w,y+h,fill='#153243' if accent else PANEL,outline=GREEN,width=1)
        self.text(x+w/2,y+h/2,self.fit(label,w-12,10),10,True,anchor='center')
        self.buttons.append((x,y,x+w,y+h,action))

    def schedule(self,*args):
        if not self.pending_draw:
            self.pending_draw=True;self.root.after(25,self.draw)

    def draw(self):
        self.pending_draw=False;c=self.canvas;c.delete('all');self.buttons=[];self.rows=[]
        w,h=c.winfo_width(),c.winfo_height()
        if w<100:return
        top,bottom=(44,12,40),(5,25,53)
        for y in range(0,h,3):
            t=y/max(1,h-1);rgb=tuple(round(a+(b-a)*t) for a,b in zip(top,bottom))
            c.create_rectangle(0,y,w,y+3,fill='#%02x%02x%02x'%rgb,outline='')
        self.text(28,21,luna_core.TITLE,25,True)
        self.button(w-305,29,125,'Recover',self.recover,38)
        self.button(w-165,29,135,'Add ZIPs',self.add,38)
        self.text(30,101,'GAME DIRECTORY',9,True)
        self.text(30,124,self.fit(self.store.state.get('game_root') or 'Choose your game folder to prepare copied inputs.',w-210),10)
        self.button(w-165,108,135,'Choose game',self.choose_game)
        self.text(30,160,'DUMMY GAME DIRECTORY',9,True)
        self.text(30,183,self.fit(self.store.dummy,w-360),10)
        self.button(w-304,167,130,'Copy path',self.copy_dummy)
        self.button(w-165,167,135,'Open folder',self.open_dummy)
        c.create_rectangle(28,220,w-28,260,fill='#102134',outline=GREEN,width=1)
        self.text(43,231,'DROP .ZIP FILES HERE  ·  Double-click a mod to open its configuration EXE.',11)
        self.text(30,278,'LOAD ORDER  ·  TOP FIRST / BOTTOM LAST  ·  DRAG MOD ICONS',10,True)
        self.text(w-30,280,str(len(self.store.state['mods']))+' in library',10,anchor='ne')
        self.list_top=307;self.list_bottom=h-280
        visible=max(1,(self.list_bottom-self.list_top)//62)
        items=self.store.state['mods'];self.offset=max(0,min(self.offset,max(0,len(items)-visible)))
        if not items:self.text(w/2,(self.list_top+self.list_bottom)/2,'Drop a ZIP to start your mod library.',13,anchor='center')
        for i,row in enumerate(items[self.offset:self.offset+visible]):
            y=self.list_top+i*62;selected=self.selected==row['id']
            c.create_rectangle(28,y,w-28,y+54,fill='#152b40' if selected else '#10192c',outline=GREEN if selected else '#24544a')
            c.create_rectangle(42,y+18,58,y+34,outline=GREEN,fill='#164739' if row['enabled'] else '#0d1726')
            if row['enabled']:
                c.create_line(45,y+26,49,y+30,55,y+22,fill=CYAN,width=2)
            c.create_rectangle(72,y+12,98,y+40,fill='#183542',outline=GREEN)
            image=self.profile_image(row)
            if image is not None:c.create_image(85,y+26,image=image,anchor='center')
            else:self.text(85,y+26,'E' if row['executables'] else 'M',11,True,anchor='center')
            self.text(109,y+7,self.fit(row['name'],w-440,12),12,True)
            kind='Configuration EXE' if row['executables'] else 'File mod'
            count=len(row['configurations'])
            detail=kind+('  ·  '+str(count)+' configured output(s)' if count else '')
            if row['executables'] and len(row['executables'])>1:detail+='  ·  '+str(len(row['executables']))+' EXEs available'
            self.text(109,y+30,self.fit(detail,w-440,9),9)
            self.button(w-285,y+12,110,'Configure',lambda identity=row['id']:self.configure(identity),h=30)
            self.text(w-99,y+18,str(self.offset+i+1).zfill(2),10,True,anchor='ne')
            self.text(w-45,y+18,'ON' if row['enabled'] else 'OFF',10,True,anchor='ne')
            self.rows.append((28,y,w-28,y+54,row['id']))
        drag=getattr(self,'drag',None)
        if drag and drag.get('active'):
            marker=self.list_top+(drag['insertion']-self.offset)*62-4
            marker=max(self.list_top-4,min(marker,self.list_bottom))
            c.create_line(29,marker,w-29,marker,fill=CYAN,width=2)
        y=h-270
        self.button(28,y,130,'Remove selected',self.remove_selected)
        self.button(168,y,120,'Choose EXE',self.cycle_exe)
        self.button(298,y,120,'Reset config',self.clear_config)
        self.button(428,y,135,'Refresh dummy',self.prepare)
        self.button(w-279,y,110,'Purge',self.purge)
        self.button(w-159,y,131,'Deploy',self.deploy,accent=True)
        self.button(28,h-224,160,'Rebuild dummy',self.rebuild_dummy)
        self.button(198,h-224,175,'Reset game files',self.reset_game_files)
        self.text(30,h-177,self.fit(('WORKING  ·  ' if self.busy else 'CONFIGURATOR OPEN  ·  ' if self.process else '')+self.status,w-60),10)
        c.create_rectangle(28,h-148,w-28,h-40,fill='#0a1527',outline='#24544a')
        for i,line in enumerate(self.logs[-5:]):self.text(40,h-139+i*18,self.fit(line,w-82,9),9)
        self.text(29,h-27,'Purge restores deployed game files. Your ZIPs, presets and backups stay in the library.',9)
        self.text(w-29,h-27,'v'+luna_core.BUILD,9,anchor='ne')

    def click(self,event):
        for x,y,x2,y2,action in self.buttons:
            if x<=event.x<=x2 and y<=event.y<=y2:action();return
        for x,y,x2,y2,identity in self.rows:
            if x<=event.x<=x2 and y<=event.y<=y2:
                self.selected=identity
                if event.x<67 and self.available():self.store.toggle(identity)
                elif 67<=event.x<=103 and not self.busy and not self.process:
                    self.drag=dict(id=identity,start=(event.x,event.y),active=False,insertion=self.offset)
                self.schedule();return

    def drag_motion(self,event):
        drag=getattr(self,'drag',None)
        if not drag or self.busy or self.process:return
        dx=event.x-drag['start'][0];dy=event.y-drag['start'][1]
        if not drag['active'] and dx*dx+dy*dy<36:return
        drag['active']=True
        count=len(self.store.state['mods'])
        if event.y<self.list_top+8:self.offset=max(0,self.offset-1)
        elif event.y>self.list_bottom-8:self.offset=min(max(0,count-1),self.offset+1)
        insertion=self.offset+max(0,int((event.y-self.list_top+31)//62))
        drag['insertion']=max(0,min(insertion,count))
        self.status='Release to move this mod. Top loads first; bottom loads last.'
        self.schedule()

    def drag_release(self,event):
        drag=getattr(self,'drag',None);self.drag=None
        if not drag or not drag['active']:return
        if self.busy or self.process:return
        rows=self.store.state['mods'];source=next(i for i,r in enumerate(rows) if r['id']==drag['id'])
        destination=drag['insertion']-(1 if source<drag['insertion'] else 0)
        self.store.move_mod(drag['id'],destination)
        self.status='Load order saved. Click Deploy to apply the new order.'
        self.schedule()

    def double_click(self,event):
        if event.x<67:return
        if getattr(self,'drag',None) and self.drag.get('active'):return
        self.drag=None
        for x,y,x2,y2,identity in self.rows:
            if x<=event.x<=x2 and y<=event.y<=y2:self.configure(identity);return

    def scroll(self,event,direction=None):
        self.offset+=direction if direction is not None else (-1 if event.delta>0 else 1)
        self.schedule()

    def available(self):
        if self.busy or self.process or getattr(self,'dialog',None):
            self.log('Finish the current operation or close the configuration dialog first.');return False
        return True

    def log(self,value):
        for line in str(value).splitlines():
            if line.strip():self.logs.append(line)
        self.logs=self.logs[-300:];self.schedule()

    def run(self,func,on_success=None):
        if not self.available():return
        self.busy=True;self.status='Preparing…';self.schedule()
        def worker():
            class Writer:
                def write(_,s):self.events.put(('text',s))
                def flush(_):pass
            try:
                with contextlib.redirect_stdout(Writer()),contextlib.redirect_stderr(Writer()):result=func()
                self.events.put(('done',(result,on_success)))
            except Exception as e:
                self.events.put(('error',str(e)))
                try:
                    with (self.store.home/'loader.log').open('a',encoding='utf-8') as f:f.write(traceback.format_exc()+'\n')
                except OSError:pass
        threading.Thread(target=worker,daemon=True).start()

    def poll(self):
        if self.drop:
            try:self.drop.drain()
            except Exception as exc:self.log('File-drop delivery failed: '+str(exc))
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=='text':
                    self.partial+=value
                    while '\n' in self.partial:
                        line,self.partial=self.partial.split('\n',1);self.log(line)
                elif kind=='error':
                    self.busy=False;self.status=value;self.log('Stopped: '+value)
                else:
                    self.busy=False;self.status='Ready.'
                    result,callback=value
                    if callback:callback(result)
                    self.schedule()
        except queue.Empty:pass
        self.root.after(80,self.poll)

    def add(self):
        if not self.available():return
        self.dropped(filedialog.askopenfilenames(title='Import mod ZIPs',filetypes=[('Mod ZIP archives','*.zip')]),None)

    def dropped(self,paths,error=None):
        if error:self.log(error);return
        if not paths or not self.available():return
        paths=list(paths)
        def task():
            for path in paths:self.store.import_zip(path)
            if self.store.state.get('game_root'):self.store.prepare()
            else:print('Imported. Choose your game directory to prepare the dummy area.')
        self.run(task)

    def choose_game(self):
        if not self.available():return
        path=filedialog.askdirectory(title='Choose your game folder containing bin and data')
        if path:self.run(lambda:self.store.set_game(path))

    def copy_dummy(self):
        self.root.clipboard_clear();self.root.clipboard_append(str(self.store.dummy));self.root.update_idletasks()
        self.status='Dummy directory copied. Paste it into the mod’s game-directory picker.';self.schedule()

    def open_dummy(self):
        self.store.dummy.mkdir(parents=True,exist_ok=True)
        if os.name=='nt':os.startfile(self.store.dummy)
        else:self.log(str(self.store.dummy))

    def profile_image(self,row):
        if not row.get('option_model',{}).get('icon'):return None
        if not hasattr(self,'images'):self.images={}
        try:
            path=self.store.icon_path(row['id'])
            if path is None:return None
            stat=path.stat();key=(row['id'],str(path),stat.st_size,stat.st_mtime_ns)
            if key not in self.images:
                try:self.images[key]=mod_images.thumbnail(self.canvas,path)
                except Exception:self.images[key]=None
            return self.images[key]  # Retain a strong Tk image reference across redraws.
        except OSError:return None

    def configure(self,identity):
        if not self.available():return
        self.selected=identity;row=self.store.mod(identity)
        self.dialog=ModDialog(self,row,exe=bool(row['executables']))

    def launch_configuration(self,identity):
        self.copy_dummy()
        def ready(process):
            self.process=process;self.status='Choose the dummy directory in the mod if requested; close it when finished.'
            self.root.after(400,self.watch_process);self.schedule()
        self.run(lambda:self.store.launch(identity),ready)

    def watch_process(self):
        result=self.process.poll()
        if result is None:self.root.after(400,self.watch_process);return
        self.process=None
        self.run(lambda:self.store.capture(result))

    def cycle_exe(self):
        if not self.available() or not self.selected:return
        row=self.store.mod(self.selected);exes=row['executables']
        if not exes:self.log('No configuration EXE in this mod.');return
        current=exes.index(row['executable']);row['executable']=exes[(current+1)%len(exes)]
        self.store.save();self.log('Double-click will open: '+row['executable'])

    def clear_config(self):
        if self.available() and self.selected:self.store.clear_configuration(self.selected);self.schedule()

    def remove_selected(self):
        if self.available() and self.selected:
            self.store.remove(self.selected);self.selected=None;self.schedule()

    def prepare(self):self.run(self.store.prepare)
    def deploy(self):self.run(self.store.deploy)

    def rebuild_dummy(self):
        if not self.available():return
        pending=self.store.state.get('repair_pending')
        if pending and pending.get('phase')!='waiting':
            self.log('Reset was interrupted. Click Reset game files again first.');return
        text='Rebuild the contents of the dummy directory? Unsaved configurator changes in it will be discarded. Saved configurations, ZIPs and options are retained.'
        if pending:text+='\n\nContinue only after Steam has finished verifying Helldivers 2. Has Steam completed verification?'
        if messagebox.askyesno('Rebuild dummy',text,parent=self.root):
            self.run(lambda:self.store.rebuild_dummy(steam_finished=bool(pending)))

    def reset_game_files(self):
        if not self.available():return
        def confirm(targets):
            text=('Back up, then delete these base game files and ask Steam to verify Helldivers 2?\n\n'+'\n'.join(targets)+
                  '\n\nSaved EXE outputs will be cleared. ZIPs, options and load order stay saved. Other managers’ direct edits to these files will also be replaced by Steam. Numbered Arsenal patches are left in place.\n\nWait for Steam to finish, then use Rebuild dummy and reconfigure your EXE mods.')
            if messagebox.askyesno('Reset game files through Steam',text,parent=self.root):self.run(lambda:self.store.reset_game_files(reviewed_targets=targets))
        pending=self.store.state.get('repair_pending')
        if pending:confirm(pending['targets'])
        else:self.run(self.store.reset_targets,confirm)

    def purge(self):self.run(self.store.purge)
    def recover(self):self.run(self.store.recover)

    def close(self):
        if self.busy or self.process or getattr(self,'dialog',None):
            self.log('Close the configurator and wait for the operation to finish before closing the loader.');return
        if self.drop:self.drop.close()
        self.root.destroy()


class ModDialog(App):
    """One styled modal for manifest options or the EXE directory handoff."""
    def __init__(self,app,row,exe=False):
        self.app=app;self.row=row;self.exe=exe;self.fonts={};self.buttons=[];self.scroll_y=0
        self.definition=row.get('option_model',dict(description='',options=[]))
        self.selections=copy.deepcopy(row.get('option_state',[]));self.redraw=None;self.closed=False
        self.root=tk.Toplevel(app.root);self.root.title('Configure — '+row['name'])
        self.root.geometry('790x620' if not exe else '790x390');self.root.minsize(650,360)
        self.root.transient(app.root)
        self.canvas=tk.Canvas(self.root,highlightthickness=0,bd=0,bg=PANEL);self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',self.schedule);self.canvas.bind('<Button-1>',self.click)
        self.canvas.bind('<MouseWheel>',self.scroll_options)
        self.canvas.bind('<Button-4>',lambda e:self.scroll_options(e,-1))
        self.canvas.bind('<Button-5>',lambda e:self.scroll_options(e,1))
        self.root.bind('<Escape>',lambda e:self.close())
        self.root.bind('<Control-c>',lambda e:self.copy_path() if self.exe else None)
        self.root.protocol('WM_DELETE_WINDOW',self.close);self.root.grab_set();self.root.lift()
        self.redraw=self.root.after_idle(self.draw)

    def schedule(self,*args):
        if not self.closed and self.redraw is None:self.redraw=self.root.after(20,self.draw)

    def lines(self,value,width,size=10):
        result=[];font=self.font(size)
        for paragraph in str(value).splitlines() or ['']:
            current=''
            for word in paragraph.split():
                if current and font.measure(current+' '+word)>width:result.append(current);current=word
                else:current=(current+' '+word).strip()
            result.append(current)
        return result

    def draw(self):
        self.redraw=None
        if self.closed:return
        c=self.canvas;c.delete('all');self.buttons=[];w,h=c.winfo_width(),c.winfo_height()
        if w<50:return
        for y in range(0,h,3):
            t=y/max(1,h-1);rgb=tuple(round(a+(b-a)*t) for a,b in zip((44,12,40),(5,25,53)))
            c.create_rectangle(0,y,w,y+3,fill='#%02x%02x%02x'%rgb,outline='')
        self.text(25,20,self.fit(self.row['name'],w-50,17),17,True)
        if self.exe:
            self.text(25,65,'Paste this dummy directory into the mod’s game/install directory picker.',11,width=w-50)
            self.text(25,112,'DUMMY GAME DIRECTORY',10,True)
            c.create_rectangle(24,140,w-24,h-112,fill=PANEL,outline=GREEN)
            self.text(38,155,str(self.app.store.dummy),11,width=w-76)
            self.text(25,h-96,'Choose this copied folder rather than the real game directory.',10)
            self.button(25,h-59,130,'Copy path',self.copy_path)
            self.button(w-320,h-59,125,'Cancel',self.close)
            self.button(w-180,h-59,155,'Copy and launch',self.launch,accent=True)
            return
        self.text(25,61,'Mod options  ·  check components; choose one variant per enabled component.',10,width=w-50)
        top=105;bottom=h-82;y=top-self.scroll_y;self.hitboxes=[]
        options=self.definition.get('options',[])
        if not options:
            self.text(25,117,'This mod declares no optional components in its manifest.',12,width=w-50)
            self.text(25,165,'Its standard package contents will be used. Enable or disable the mod in the main list.',10,width=w-50)
        for i,(option,state) in enumerate(zip(options,self.selections)):
            row_height=36
            desc=self.lines(option['description'],w-100,10)
            choice_lines=[self.lines(choice['description'],w-125,9) if choice['description'] else [] for choice in option['choices']]
            block=36+len(desc)*17+sum(36+len(lines)*16 for lines in choice_lines)
            if y+block>=top and y<bottom:
                if top<=y<bottom-27:
                    c.create_rectangle(27,y+3,44,y+20,outline=GREEN,fill='#164739' if state['enabled'] else PANEL)
                    if state['enabled']:c.create_line(30,y+11,35,y+16,41,y+6,fill=CYAN,width=2)
                    self.text(57,y,self.fit(option['name'],w-90,11),11,True)
                    self.hitboxes.append((24,y-2,w-24,y+27,lambda index=i:self.toggle_option(index)))
                dy=y+29
                for line in desc:
                    if top<=dy<bottom-18:self.text(57,dy,line,10)
                    dy+=17
                for j,choice in enumerate(option['choices']):
                    if top<=dy<bottom-30:
                        c.create_oval(59,dy+5,73,dy+19,outline=GREEN,fill=PANEL)
                        if state['choice']==j:c.create_oval(63,dy+9,69,dy+15,fill=CYAN,outline='')
                        self.text(86,dy+1,self.fit(choice['name'],w-115,10),10,True)
                        if state['enabled']:self.hitboxes.append((54,dy-1,w-24,dy+30,lambda index=i,value=j:self.choose(index,value)))
                    child_y=dy+25
                    for line in choice_lines[j]:
                        if top<=child_y<bottom-18:self.text(86,child_y,line,9)
                        child_y+=16
                    dy+=36+len(choice_lines[j])*16
            y+=block+18
        self.total_height=max(0,y+self.scroll_y-top)
        self.max_scroll=max(0,self.total_height-(bottom-top))
        if self.scroll_y>self.max_scroll:self.scroll_y=self.max_scroll;self.schedule()
        self.text(25,h-75,'Changes take effect on Refresh dummy / Deploy. Scroll for more options.',9)
        self.button(w-295,h-52,120,'Cancel',self.close)
        self.button(w-160,h-52,135,'Save options',self.save_options,accent=True)

    def click(self,event):
        for x,y,x2,y2,action in self.buttons:
            if x<=event.x<=x2 and y<=event.y<=y2:action();return
        for x,y,x2,y2,action in getattr(self,'hitboxes',[]):
            if x<=event.x<=x2 and y<=event.y<=y2:action();return

    def toggle_option(self,index):
        state=self.selections[index];state['enabled']=not state['enabled'];self.schedule()

    def choose(self,index,value):self.selections[index]['choice']=value;self.schedule()

    def scroll_options(self,event,direction=None):
        if self.exe:return
        delta=direction if direction is not None else (-1 if event.delta>0 else 1)
        self.scroll_y=max(0,min(getattr(self,'max_scroll',0),self.scroll_y+delta*46));self.schedule()

    def copy_path(self):
        self.root.clipboard_clear();self.root.clipboard_append(str(self.app.store.dummy));self.root.update_idletasks()

    def launch(self):
        self.copy_path();identity=self.row['id'];self.close();self.app.launch_configuration(identity)

    def save_options(self):
        try:self.app.store.set_options(self.row['id'],self.selections)
        except Exception as exc:self.app.log('Options not saved: '+str(exc));return
        self.app.status='Mod options saved. Click Deploy to apply them.';self.close()

    def close(self):
        if self.closed:return
        self.closed=True
        if self.redraw is not None:self.root.after_cancel(self.redraw)
        self.app.dialog=None;self.root.grab_release();self.root.destroy();self.app.schedule()


def main():
    # One process may own this library; concurrent instances must not edit its staging tree.
    store=luna_core.Store()
    import faulthandler
    # Keep this file open for the lifetime of the native callback/runtime.
    with (store.home/'native-crash.log').open('a',encoding='utf-8') as crash_log:
        faulthandler.enable(file=crash_log,all_threads=True)
        try:
            with manager.locked(store.home):
                root=tk.Tk();app_holder=[]
                def report_callback(exc_type,value,tb):
                    details=''.join(traceback.format_exception(exc_type,value,tb))
                    with (store.home/'loader.log').open('a',encoding='utf-8') as f:f.write(details+'\n')
                    if app_holder:app_holder[0].log('Interface error: '+str(value))
                root.report_callback_exception=report_callback
                app=App(root,store);app_holder.append(app)
                root.mainloop()
        finally:faulthandler.disable()


if __name__=='__main__':
    try:main()
    except Exception:
        folder=luna_core.default_home();folder.mkdir(parents=True,exist_ok=True)
        (folder/'startup-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        if os.name=='nt':ctypes.windll.user32.MessageBoxW(None,'Startup failed. See '+str(folder/'startup-error.txt'),luna_core.TITLE,0x10)
        else:raise
