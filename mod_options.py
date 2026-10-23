"""Data-only HD2 manifest v1 options: checkboxes and single-choice sub-options."""
import json
from pathlib import PurePosixPath
import manager as m


def model(files):
    candidates=sorted((p for p in files.rglob('manifest.json') if len(p.relative_to(files).parts)<=2),
                      key=lambda p:(len(p.relative_to(files).parts),str(p).casefold()))
    if not candidates:
        native=files/'unified-mod.json'
        if native.exists():candidates=[native]
        else:return dict(root='',description='',options=[],icon=None)
    manifest=candidates[0]
    m.need(manifest.stat().st_size<=1024*1024,'Mod manifest is too large')
    value=json.loads(manifest.read_text('utf-8-sig'))
    if manifest.name!='unified-mod.json' and not ('Options' in value or ('Guid' in value and 'Name' in value)):
        return dict(root='',description='',options=[],icon=None)
    options=value.get('Options') or []
    m.need(value.get('Version',1)==1,'Unsupported mod-option manifest version')
    m.need(isinstance(options,list) and len(options)<=1000,'Invalid Options array')
    def includes(item):
        paths=item.get('Include') or []
        m.need(isinstance(paths,list) and all(isinstance(p,str) for p in paths),'Invalid Include paths')
        out=[]
        for path in paths:
            path=path.replace('\\','/')
            p=PurePosixPath(path)
            m.need(not p.is_absolute() and '..' not in p.parts and ':' not in path,'Unsafe option Include path')
            normalized=p.as_posix()
            actual=m.safe_path(manifest.parent,normalized)
            m.need(actual.exists(),'Option Include path is missing: '+path)
            out.append(normalized)
        return out
    definitions=[];total=0
    for index,item in enumerate(options):
        m.need(isinstance(item,dict),'An option must be an object')
        children=item.get('SubOptions') or []
        m.need(isinstance(children,list) and len(children)<=1000,'Invalid SubOptions array')
        group=[]
        for child in children:
            m.need(isinstance(child,dict),'A sub-option must be an object')
            group.append(dict(name=str(child.get('Name','Variant')),description=str(child.get('Description','')),
                              include=includes(child)))
        total+=1+len(group);m.need(total<=5000,'Too many mod options')
        definitions.append(dict(name=str(item.get('Name','Option '+str(index+1))),
                                description=str(item.get('Description','')),include=includes(item),choices=group))
    icon=None
    declared=value.get('IconPath',value.get('icon'))
    if isinstance(declared,str) and declared:
        try:
            image=m.safe_path(manifest.parent,declared.replace('\\','/'))
            if image.is_file() and image.stat().st_size<=16*1024*1024:
                icon=image.relative_to(files).as_posix()
        except (m.ModError,OSError):pass
    return dict(root=manifest.parent.relative_to(files).as_posix(),
                description=str(value.get('Description',value.get('description',''))),options=definitions,icon=icon)


def defaults(definition):
    return [dict(enabled=True,choice=0 if option['choices'] else None) for option in definition['options']]


def validate(definition,state):
    m.need(isinstance(state,list) and len(state)==len(definition['options']),'Option state does not match this mod')
    for option,selection in zip(definition['options'],state):
        m.need(isinstance(selection,dict) and type(selection.get('enabled')) is bool,'Invalid checkbox selection')
        choice=selection.get('choice')
        m.need((not option['choices'] and choice is None) or
               (type(choice) is int and 0<=choice<len(option['choices'])),'Choose exactly one sub-option')
    return state


def selected_files(files,definition,state):
    validate(definition,state)
    root=m.safe_path(files,definition['root'] or '.')
    all_includes=[];chosen=[]
    for option,selection in zip(definition['options'],state):
        all_includes.extend(option['include'])
        for choice in option['choices']:all_includes.extend(choice['include'])
        if selection['enabled']:
            chosen.extend(option['include'])
            if option['choices']:chosen.extend(option['choices'][selection['choice']]['include'])
    exclusions=[m.safe_path(root,p) for p in all_includes]
    selected={}
    # Files outside every option directory are common assets.
    for path in sorted(root.rglob('*')):
        if not path.is_file():continue
        if not any(path==item or path.is_relative_to(item) for item in exclusions):selected[path]=root
    for relative in chosen:
        include=m.safe_path(root,relative)
        paths=[include] if include.is_file() else sorted(include.rglob('*'))
        for path in paths:
            if path.is_file():
                m.safe_path(root,path.relative_to(root).as_posix())
                selected[path]=include.parent if include.is_file() else include
    return [(path,base) for path,base in selected.items()]
