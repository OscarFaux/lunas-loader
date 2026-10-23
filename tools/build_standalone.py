#!/usr/bin/env python3
"""Build a Windows x64 single-file EXE from the supplied redistributable runtime.

Uses the PyInstaller bootloader, standard-library PYZ modules, and Python/Tcl/Tk
runtime from the supplied ArmorWorkbench distribution. No ArmorWorkbench code,
assets, native solver, or third-party Python packages are incorporated.
Requires CPython 3.12 to marshal our code. It does not run a Windows executable.
"""
import argparse
import importlib.util
import json
import marshal
from pathlib import Path
import struct
import sys
import zlib
import zipfile

COOKIE=struct.Struct('!8sIIII64s')
ENTRY=struct.Struct('!IIIIBc')
MAGIC=b'MEI\014\013\012\013\016'


def archive_parts(exe):
    cookie=exe.rfind(MAGIC)
    magic,length,toc_offset,toc_size,version,library=COOKIE.unpack_from(exe,cookie)
    assert version==312 and magic==MAGIC
    start=cookie+COOKIE.size-length
    entries=[];position=start+toc_offset
    while position<start+toc_offset+toc_size:
        size,offset,packed,unpacked,compressed,kind=ENTRY.unpack_from(exe,position)
        name=exe[position+ENTRY.size:position+size].rstrip(b'\0').decode('utf-8')
        data=exe[start+offset:start+offset+packed]
        if compressed:data=zlib.decompress(data)
        assert len(data)==unpacked
        entries.append((name,kind,data))
        position+=size
    return exe[:start],entries


def pyz_entries(data):
    assert data[:4]==b'PYZ\0'
    assert data[4:8]==importlib.util.MAGIC_NUMBER,'Builder and embedded Python bytecode versions differ'
    offset=struct.unpack_from('!i',data,8)[0]
    toc=marshal.loads(data[offset:])
    return [(name,kind,zlib.decompress(data[pos:pos+length])) for name,(kind,pos,length) in toc]


def make_pyz(entries):
    out=bytearray(b'PYZ\0'+importlib.util.MAGIC_NUMBER+b'\0'*4+b'\0'*5)
    toc=[]
    for name,kind,data in entries:
        packed=zlib.compress(data,9);pos=len(out);out.extend(packed)
        toc.append((name,(kind,pos,len(packed))))
    offset=len(out);out.extend(marshal.dumps(toc));struct.pack_into('!i',out,8,offset)
    return bytes(out)


def append_carchive(stub,items):
    data=bytearray();toc=bytearray()
    for name,kind,raw,compressed in items:
        offset=len(data);packed=zlib.compress(raw,9) if compressed else raw
        data.extend(packed)
        name=name.encode('utf-8')+b'\0'
        length=ENTRY.size+len(name)
        length=(length+15)//16*16
        toc.extend(ENTRY.pack(length,offset,len(packed),len(raw),int(compressed),kind))
        toc.extend(name);toc.extend(b'\0'*(length-ENTRY.size-len(name)))
    offset=len(data);data.extend(toc)
    data.extend(COOKIE.pack(MAGIC,len(data)+COOKIE.size,offset,len(toc),312,b'python312.dll'))
    return stub+data


def replace_icon(stub,icon):
    """Replace fixed-size resource slots without changing the bootloader code."""
    b=bytearray(stub)
    pe=struct.unpack_from('<I',b,0x3c)[0]
    count=struct.unpack_from('<H',b,pe+6)[0]
    optional=pe+24;optional_size=struct.unpack_from('<H',b,pe+20)[0]
    rsrc=struct.unpack_from('<I',b,optional+112+16)[0]
    def file_offset(rva):
        for i in range(count):
            pos=optional+optional_size+i*40
            virtual_size,virtual,raw_size,raw=struct.unpack_from('<IIII',b,pos+8)
            if virtual<=rva<virtual+max(virtual_size,raw_size):return raw+rva-virtual
        raise ValueError('Resource RVA outside executable sections')
    root=file_offset(rsrc);leaves={}
    def walk(pos,path):
        named,ids=struct.unpack_from('<HH',b,pos+12)
        for i in range(named+ids):
            key,value=struct.unpack_from('<II',b,pos+16+i*8)
            if value&0x80000000:walk(root+(value&0x7fffffff),path+(key,))
            else:
                entry=root+value;rva,size=struct.unpack_from('<II',b,entry)
                leaves[path+(key,)]=(entry,file_offset(rva),size)
    walk(root,())
    icons={}
    entries=struct.unpack_from('<H',icon,4)[0]
    for i in range(entries):
        pos=6+16*i;width,height=icon[pos],icon[pos+1]
        size,offset=struct.unpack_from('<II',icon,pos+8)
        icons[(width,height)]=icon[offset:offset+size]
    for path,(entry,pos,size) in list(leaves.items()):
        if path[0]!=14:continue
        number=struct.unpack_from('<H',b,pos+4)[0]
        for i in range(number):
            group=pos+6+14*i
            dims=(b[group],b[group+1]);identity=struct.unpack_from('<H',b,group+12)[0]
            payload=icons[dims]
            ie,ip,capacity=next(v for k,v in leaves.items() if k[0]==3 and k[1]==identity)
            assert len(payload)<=capacity,'New icon exceeds reserved PE resource slot'
            b[ip:ip+capacity]=payload+b'\0'*(capacity-len(payload))
            struct.pack_into('<I',b,ie+4,len(payload))
            struct.pack_into('<I',b,group+8,len(payload))
    struct.pack_into('<I',b,optional+64,0)  # Recompute on a signed/release build if needed.
    return bytes(b)


def main():
    p=argparse.ArgumentParser();p.add_argument('runtime_zip');p.add_argument('--project',default=str(Path(__file__).parents[1]));p.add_argument('--output',required=True)
    args=p.parse_args();root=Path(args.project);output=Path(args.output)
    assert sys.version_info[:2]==(3,12),'Build using Python 3.12'
    with zipfile.ZipFile(args.runtime_zip) as z:
        original=z.read('ArmorWorkbench/ArmorWorkbench.exe')
        stub,old=archive_parts(original)
        stub=replace_icon(stub,(root/'luna.ico').read_bytes())
        original_pyz=next(data for name,kind,data in old if kind==b'z')
        standard=[];excluded=[]
        for name,kind,data in pyz_entries(original_pyz):
            if name.split('.')[0] in sys.stdlib_module_names:standard.append((name,kind,data))
            else:excluded.append(name)
        # Original GUI did not need tkinter.font; it is pure standard-library Python.
        font_source=Path(__import__('tkinter').__file__).parent/'font.py'
        standard=[e for e in standard if e[0]!='tkinter.font']
        standard.append(('tkinter.font',0,marshal.dumps(compile(font_source.read_text(),'tkinter/font.py','exec',optimize=1))))
        for name in ('manager','mod_options','mod_images','luna_core'):
            code=compile((root/(name+'.py')).read_text('utf-8'),name+'.py','exec',optimize=1)
            standard.append((name,0,marshal.dumps(code)))
        items=[]
        for name,kind,data in old:
            if kind in (b'm',b'M') or (kind==b's' and name!='app'):
                items.append((name,kind,data,True))
        code=compile((root/'gui.py').read_text('utf-8'),'gui.py','exec',optimize=1)
        items.append(('lunas_loader',b's',marshal.dumps(code),True))
        items.append(('PYZ.pyz',b'z',make_pyz(standard),False))
        # Binaries/data force the bootloader's onefile extraction mode. The onedir
        # contents-directory option is deliberately not carried into this archive.
        for member in z.infolist():
            prefix='ArmorWorkbench/_internal/'
            if not member.filename.startswith(prefix) or member.is_dir():continue
            relative=member.filename[len(prefix):]
            parts=relative.split('/')
            if len(parts)>1 and parts[0] not in ('_tcl_data','_tk_data'):continue
            if len(parts)==1 and relative.startswith('_cffi'):continue
            if len(parts)==1 and not relative.lower().endswith(('.dll','.pyd','.zip')):continue
            kind=b'b' if relative.lower().endswith(('.dll','.pyd')) else b'x'
            items.append((relative.replace('/','\\'),kind,z.read(member.filename),True))
        for relative in ['manager.py','luna.ico','README.md','docs/DEVELOPERS.md','LICENSE.txt']:
            items.append((relative.replace('/','\\'),b'x',(root/relative).read_bytes(),True))
        for source,dest in [
            ('ArmorWorkbench/LICENSES/Python-LICENSE.txt','LICENSES/Python-LICENSE.txt'),
            ('ArmorWorkbench/LICENSES/pyinstaller-6.20.0.dist-info/licenses/COPYING.txt','LICENSES/PyInstaller-COPYING.txt'),
            ('ArmorWorkbench/LICENSES/Tcl-Tk/tk8.6/license.terms','LICENSES/Tcl-Tk-license.terms')]:
            data=z.read(source);items.append((dest.replace('/','\\'),b'x',data,True))
            destpath=root/dest;destpath.parent.mkdir(parents=True,exist_ok=True);destpath.write_bytes(data)
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_bytes(append_carchive(stub,items))
        report=dict(executable=str(output.name),architecture='Windows x64',python='3.12',
                    bytes=output.stat().st_size,entries=len(items),stdlib_modules=len(standard)-4,python_modules=len(standard),
                    excluded_nonstdlib_modules=excluded,windows_execution_tested=False)
        (root/'docs'/'BUILD-REPORT.json').write_text(json.dumps(report,indent=2))
        # Round trip every entry, code object and PYZ compression stream.
        _,check=archive_parts(output.read_bytes())
        assert len(check)==len(items)
        check_pyz=next(b for n,k,b in check if k==b'z')
        for name,kind,data in pyz_entries(check_pyz):marshal.loads(data)
        for name,kind,data in check:
            if kind in (b's',b'm',b'M'):marshal.loads(data)
        print(json.dumps(report,indent=2))

if __name__=='__main__':main()
