"""Public third-party Intel foundation; not a VoiceStudio production proof."""
import argparse, hashlib, io, json, os, pathlib, platform, shutil, subprocess, sys, tarfile, tempfile, urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[1]
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def run(*cmd,env=None): subprocess.run([str(x) for x in cmd],check=True,env=env)
def safe(n):
    if not isinstance(n,str) or not n or n.startswith('/') or '\\' in n or ':' in n or any(x in ('','.','..') for x in n.split('/')):raise ValueError('unsafe path: '+repr(n))
    return n
def download(url,target,digest,size=None):
    assert url.startswith(('https://conda.anaconda.org/conda-forge/','https://nodejs.org/dist/'))
    if target.exists(): raise ValueError('file already exists')
    with urllib.request.urlopen(url,timeout=120) as f,target.open('xb') as out:
        shutil.copyfileobj(f,out)
    if (size is not None and target.stat().st_size!=size) or sha(target)!=digest:raise ValueError('frozen input hash/size mismatch: '+target.name)
def inventory(root):
    items=[]
    for p in root.rglob('*'):
        if p.is_symlink():raise ValueError('symlink not allowed in foundation: '+str(p))
        if p.is_file():
            name=safe(p.relative_to(root).as_posix());s=p.stat()
            items.append({'path':name,'sha256':sha(p),'sizeBytes':s.st_size,'mode':s.st_mode&0o777})
    return sorted(items,key=lambda x:x['path'])
def archive_roundtrip(root,dest):
    entries=inventory(root);data=(json.dumps({'schemaVersion':1,'platform':'macos-x64','purpose':'public-third-party-foundation','files':entries},sort_keys=True,indent=2)+'\n').encode()
    with tarfile.open(dest,'w:gz',compresslevel=5) as t:
        for e in entries:
            info=tarfile.TarInfo(e['path']);info.size=e['sizeBytes'];info.mode=e['mode']
            with (root/e['path']).open('rb') as f:t.addfile(info,f)
        info=tarfile.TarInfo('native-foundation-inventory.json');info.size=len(data);info.mode=0o644;t.addfile(info,io.BytesIO(data))
    with tempfile.TemporaryDirectory(prefix='foundation roundtrip ') as td:
        target=pathlib.Path(td);found=set();modes={}
        with tarfile.open(dest,'r:gz') as t:
            for m in t:
                name=safe(m.name)
                if not m.isfile() or m.mode&0o7000 or name.casefold() in found:raise ValueError('unsafe archive member')
                found.add(name.casefold());p=target/name;p.parent.mkdir(parents=True,exist_ok=True)
                with p.open('xb') as out:shutil.copyfileobj(t.extractfile(m),out)
                p.chmod(m.mode&0o777);modes[name]=m.mode&0o777
        if (target/'native-foundation-inventory.json').read_bytes()!=data:raise ValueError('inventory bytes mismatch')
        (target/'native-foundation-inventory.json').unlink()
        actual=inventory(target)
        if actual!=entries:
            for i in range(max(len(actual),len(entries))):
                x=actual[i] if i<len(actual) else None;y=entries[i] if i<len(entries) else None
                if x!=y:raise ValueError(f'round-trip differing entry {i}: actual={x} expected={y}')
    return {'archiveSha256':sha(dest),'archiveSizeBytes':dest.stat().st_size,'files':len(entries),'inventorySha256':hashlib.sha256(data).hexdigest()}
def build(lock,out):
    if sys.platform!='darwin' or platform.machine()!='x86_64':raise SystemExit('native macOS Intel required')
    if out.exists():raise ValueError('output exists')
    cfg=json.loads(lock.read_text());assert cfg['purpose']=='public-third-party-foundation' and cfg['platform']=='macos-x64'
    assert cfg['pythonVersion']=='3.11.14'
    out.parent.mkdir(parents=True,exist_ok=True)
    work=out.parent/'work-public-foundation'
    if work.exists():raise ValueError('work exists')
    work.mkdir();pkg=work/'downloads';pkg.mkdir()
    for x in cfg['condaPackages']:
        name=x['url'].rsplit('/',1)[-1];download(x['url'],pkg/name,x['sha256'],x['size'])
    mm=cfg['micromamba'];download(mm['url'],pkg/'micromamba.tar.bz2',mm['sha256'],mm['sizeBytes'])
    with tarfile.open(pkg/'micromamba.tar.bz2','r:bz2') as t:
        bin_member=t.getmember('bin/micromamba');f=t.extractfile(bin_member);binary=work/'micromamba';binary.write_bytes(f.read());binary.chmod(0o755)
    # @EXPLICIT install uses verified, locally downloaded archives; no solver or floating versions.
    explicit=work/'explicit.txt';explicit.write_text('@EXPLICIT\n'+''.join((pkg/x['url'].rsplit('/',1)[-1]).as_uri()+'\n' for x in cfg['condaPackages']))
    prefix=work/'prefix'
    run(binary,'create','-y','--offline','-p',prefix,'-f',explicit,env={**os.environ,'MAMBA_ROOT_PREFIX':str(work/'mamba')})
    # Verify import and architectures on native host. This step requires full conda closure.
    py=prefix/'bin/python';run(py,'-I','-c','import torch,torchaudio,numpy,numba;print(torch.__version__,torchaudio.__version__)')
    tbb=prefix/cfg['excludedNumbaTbb']['path']
    if tbb.exists():
        if sha(tbb)!=cfg['excludedNumbaTbb']['sha256']:raise ValueError('unexpected optional Numba TBB bytes')
        tbb.unlink()
    # Relocatable binary repair needs established production logic; don't mislabel conda prefix as relocated.
    # The archive deliberately carries dependency inputs and a verified conda prefix as a foundation only.
    out.mkdir();target=out/'runtime/python/macos-x64';target.parent.mkdir(parents=True)
    shutil.copytree(prefix,target)
    node=cfg['node'];node_tar=work/'node.tar.gz';download(node['url'],node_tar,node['sha256'])
    node_dir=out/'runtime/node/macos-x64/bin';node_dir.mkdir(parents=True)
    with tarfile.open(node_tar,'r:gz') as t:
        match=[m for m in t if m.name.endswith('/bin/node') and m.isfile()]
        if len(match)!=1:raise ValueError('node input layout')
        with (node_dir/'node').open('xb') as f:shutil.copyfileobj(t.extractfile(match[0]),f)
    (node_dir/'node').chmod(0o755);run(node_dir/'node','--version')
    # build Whisper from the publicly pinned upstream revision (no private code)
    w=work/'whisper';run('git','clone','--filter=blob:none','--no-checkout',cfg['whisper']['repository'],w);run('git','-C',w,'checkout','--detach',cfg['whisper']['commit'])
    assert subprocess.check_output(['git','-C',str(w),'rev-parse','HEAD'],text=True).strip()==cfg['whisper']['commit']
    b=work/'whisper-build';run('cmake','-S',w,'-B',b,'-DCMAKE_BUILD_TYPE=Release','-DCMAKE_OSX_ARCHITECTURES=x86_64','-DCMAKE_OSX_DEPLOYMENT_TARGET=13.5','-DBUILD_SHARED_LIBS=OFF','-DGGML_NATIVE=OFF','-DGGML_METAL=OFF','-DGGML_BLAS=OFF','-DGGML_OPENMP=OFF','-DWHISPER_COREML=OFF','-DWHISPER_FFMPEG=OFF','-DWHISPER_BUILD_TESTS=OFF','-DWHISPER_BUILD_EXAMPLES=ON')
    run('cmake','--build',b,'--config','Release','--target','whisper-cli','--parallel','2')
    wb=out/'library/whisper/macos-x64/bin';wb.mkdir(parents=True);shutil.copy2(b/'bin/whisper-cli',wb/'whisper-cli')
    for p in (py,node_dir/'node',wb/'whisper-cli'):
        output=subprocess.check_output(['file','-b',str(p)],text=True)
        if 'x86_64' not in output:raise ValueError('not Intel: '+str(p)+' '+output)
    # Captures public dependency provenance; no model weights or VoiceStudio files are added.
    (out/'public-third-party-lock.json').write_text(json.dumps(cfg,sort_keys=True,indent=2)+'\n')
    receipt=archive_roundtrip(out,out.parent/'public-intel-foundation.tar.gz')
    (out.parent/'public-foundation-report.json').write_text(json.dumps({'status':'FOUNDATION_ONLY_NOT_RELOCATED_NOT_PRODUCTION_ACCEPTED',**receipt},indent=2)+'\n')
    print(json.dumps(receipt,indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['build','selftest']);p.add_argument('--lock',type=pathlib.Path,default=ROOT/'public-intel-lock.json');p.add_argument('--output',type=pathlib.Path,default=pathlib.Path('out/public-intel-foundation'));a=p.parse_args()
    if a.command=='selftest':
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d)/'input';root.mkdir();(root/'lib').mkdir();(root/'lib/a').mkdir();(root/'lib/a.txt').write_text('a');(root/'lib/a/z').write_text('z');(root/'bin').mkdir();(root/'bin/python').write_text('#!/bin/sh\n');(root/'bin/python').chmod(0o755)
            print(archive_roundtrip(root,pathlib.Path(d)/'fixture.tar.gz'))
    else:build(a.lock,a.output)
