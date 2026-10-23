"""Compare original application source with code extracted from our 0.5.1 EXE.

This reads archive data and disassembles code; it never starts the EXE or execs
its code objects. Use only on the known loader artifact, not arbitrary files.
"""
import argparse
import dis
import hashlib
import io
import json
import marshal
from pathlib import Path
import sys
import build_standalone as archive


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exe',type=Path)
    parser.add_argument('--output',type=Path,default=Path('review-evidence'))
    args=parser.parse_args()
    if sys.version_info[:2]!=(3,12):parser.error('Use CPython 3.12 for this bytecode format')
    root=Path(__file__).resolve().parents[1]
    raw=args.exe.read_bytes();stub,entries=archive.archive_parts(raw)
    modules={name:data for name,kind,data in archive.pyz_entries(next(data for name,kind,data in entries if kind==b'z'))}
    args.output.mkdir(parents=True,exist_ok=True)
    matches=[]
    for name in ('gui','luna_core','manager','mod_options','mod_images'):
        source=root/(name+'.py');source_bytes=source.read_bytes()
        extracted=next(data for n,k,data in entries if n=='lunas_loader' and k==b's') if name=='gui' else modules[name]
        compiled=compile(source.read_text('utf-8'),name+'.py','exec',optimize=1)
        expected=marshal.dumps(compiled)
        actual=marshal.loads(extracted)
        stream=io.StringIO();dis.dis(actual,file=stream,depth=None)
        (args.output/(name+'.dis.txt')).write_text(stream.getvalue(),encoding='utf-8')
        matches.append(dict(module=name,source_file=source.name,source_sha256=digest(source_bytes),
                            embedded_marshal_sha256=digest(extracted),compiled_marshal_sha256=digest(expected),
                            exact_marshaled_code_match=expected==extracted,code_object_match=compiled==actual))
    inventory=[dict(name=name,type=kind.decode('ascii'),unpacked_bytes=len(data),sha256=digest(data)) for name,kind,data in entries]
    (args.output/'archive-inventory.json').write_text(json.dumps(inventory,indent=2)+'\n')
    report=dict(exe_file=args.exe.name,exe_sha256=digest(raw),exe_bytes=len(raw),
                inspection_python=sys.version,compile_optimization=1,app_modules=matches,
                all_five_app_modules_match=all(r['exact_marshaled_code_match'] and r['code_object_match'] for r in matches),
                scope='Five original application modules; runtime/bootloader is inventoried, not audited by this comparison.',
                method='Compile supplied source, compare exact marshal bytes, extract recursive bytecode disassembly. No decompilation and no EXE execution.')
    (args.output/'SOURCE-TO-EXE.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    if not report['all_five_app_modules_match']:raise SystemExit(1)


if __name__=='__main__':main()
