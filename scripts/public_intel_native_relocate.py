"""Public open-source Intel Mach-O relocation candidate; never a production receipt."""
import argparse, hashlib, json, os, platform, re, shutil, subprocess, tarfile
from pathlib import Path

EXPECTED='c8ab0d72a5e607ce9a296a168ead8307506d7c670315125d1a16907d87a599c6'
PREFIX='runtime/python/macos-x64'

def digest(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()

def cmd(*a):return subprocess.check_output(list(map(str,a)),text=True,stderr=subprocess.STDOUT).strip()

def extract(archive,dest):
    if dest.exists():raise ValueError('Destination already exists: '+str(dest))
    dest.mkdir(parents=True); seen=set()
    with tarfile.open(archive,'r:gz') as t:
        for m in t:
            n=m.name
            if (not n or n.startswith('/') or '\\' in n or ':' in n or
                any(s in ('','.','..') for s in n.split('/')) or n.casefold() in seen or
                not m.isfile() or m.mode & 0o7000):raise ValueError('Unsafe/duplicate archive entry: '+n)
            seen.add(n.casefold()); p=dest/n; p.parent.mkdir(parents=True,exist_ok=True)
            with t.extractfile(m) as src,p.open('xb') as f:shutil.copyfileobj(src,f)
            p.chmod(m.mode & 0o777)

def machos(root):
    for p in sorted(root.rglob('*')):
        if p.is_file():
            with p.open('rb') as f:magic=f.read(4)
            if magic in (b'\xcf\xfa\xed\xfe',b'\xce\xfa\xed\xfe',b'\xca\xfe\xba\xbe',b'\xca\xfe\xba\xbf'):yield p

def deps(p):return [x.strip().split(' (compatibility')[0] for x in cmd('/usr/bin/otool','-L',p).splitlines()[1:] if x.strip()]
def rpaths(p):return re.findall(r'cmd LC_RPATH\s+cmdsize \d+\s+path (.+?) \(offset',cmd('/usr/bin/otool','-l',p))

def allowed(d):return d.startswith(('/System/Library/','/usr/lib/'))

def provider(dep,root):
    marker='/runtime/python/macos-x64/'
    if marker in dep:return root/PREFIX/dep.split(marker,1)[1]
    if '/lib/' in dep:return root/PREFIX/'lib'/dep.split('/lib/',1)[1]
    return None

def scan(root,repair=False):
    errors=[];changes=[];total=0;before=0
    for p in machos(root):
        total+=1; rel=p.relative_to(root).as_posix(); args=[]
        try:
            arches=set(cmd('/usr/bin/lipo','-archs',p).split())
            if arches!={'x86_64'}:
                errors.append({'file':rel,'issue':'unexpected architecture','arches':sorted(arches)});continue
            for dep in deps(p):
                if not dep.startswith('/') or allowed(dep):continue
                before+=1
                target=provider(dep,root)
                if target is None or not target.is_file():
                    errors.append({'file':rel,'issue':'absolute dependency unmapped','dependency':dep});continue
                args+=['-change',dep,'@loader_path/'+os.path.relpath(target,p.parent).replace(os.sep,'/')]
            for rp in rpaths(p):
                if rp.startswith('/'):
                    before+=1;args+=['-delete_rpath',rp]
                elif not rp.startswith(('@loader_path','@executable_path','@rpath')):
                    errors.append({'file':rel,'issue':'unreviewed rpath','rpath':rp})
            if args and repair:
                cmd('/usr/bin/install_name_tool',*args,p)
                cmd('/usr/bin/codesign','--force','--sign','-',p)
                cmd('/usr/bin/codesign','--verify','--strict',p)
                changes.append(rel)
        except (subprocess.CalledProcessError,OSError) as e:
            errors.append({'file':rel,'issue':'native repair/audit command failed','details':str(e)[-500:]})
    leftovers=[]
    for p in machos(root):
        try:
            for d in deps(p):
                if d.startswith('/') and not allowed(d): leftovers.append({'file':p.relative_to(root).as_posix(),'dependency':d})
            for d in rpaths(p):
                if d.startswith('/'):leftovers.append({'file':p.relative_to(root).as_posix(),'rpath':d})
        except subprocess.CalledProcessError as e:errors.append({'file':str(p),'issue':'re-audit failed','details':str(e)})
    return {'machoExamined':total,'nativeChanges':len(changes),'absoluteReferencesInitially':before,'changesSample':changes[:20],
            'errors':errors[:80],'remainingAbsoluteReferences':leftovers[:80],
            'nativeLoaderAuditPassed':not(errors or leftovers),'completeRuntime':False,'relocationAccepted':False}

def smoke(root):
    py=root/PREFIX/'bin/python3'
    code='''import importlib,importlib.metadata as m
import torch,torchaudio,numpy,numba,llvmlite
assert m.version("chatterbox-tts")=="0.1.7"
assert m.version("resemble-perth")=="1.1.0"
for name in ("chatterbox","perth"):importlib.import_module(name)
'''
    cmd(py,'-I','-c',code);cmd(py,'-I','-m','pip','check')

def main():
    a=argparse.ArgumentParser();a.add_argument('--archive',required=True,type=Path);a.add_argument('--work',required=True,type=Path);x=a.parse_args()
    if platform.system()!='Darwin' or platform.machine()!='x86_64':raise RuntimeError('Intel macOS runner required')
    if digest(x.archive)!=EXPECTED:raise ValueError('Input archive checksum mismatch')
    if x.work.exists():raise ValueError('Refusing to replace work directory')
    x.work.mkdir(parents=True);first=x.work/'Native Relocation One';extract(x.archive,first)
    report=scan(first,repair=True);(x.work/'native-audit.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)
    if not report['nativeLoaderAuditPassed']:raise RuntimeError('Native loader repair blocked; see native-audit.json')
    smoke(first)
    archive=x.work/'intel-native-repaired-candidate.tar.gz'
    with tarfile.open(archive,'w:gz',format=tarfile.PAX_FORMAT) as t:
        for p in sorted(first.rglob('*')):
            if p.is_symlink():raise ValueError('Unexpected symlink: '+str(p))
            if p.is_file():t.add(p,arcname=p.relative_to(first).as_posix(),recursive=False)
    second=x.work/'Native Relocation Two With Spaces';extract(archive,second);smoke(second)
    second_report=scan(second,repair=False)
    if not second_report['nativeLoaderAuditPassed']:raise RuntimeError('Native second-location loader gate failed')
    result={'status':'PUBLIC_INTEL_NATIVE_SECOND_LOCATION_SMOKE_PASSED','archive':archive.name,'sha256':digest(archive),
            'sizeBytes':archive.stat().st_size,'nativeLoadAuditPassed':True,'secondLocationImportsPassed':True,
            'completeRuntime':False,'relocationAccepted':False,
            'disclaimer':'No private model generation, sandbox denial, native runtime proof or production license acceptance'}
    (x.work/'stage4-report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
