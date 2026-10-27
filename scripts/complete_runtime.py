"""Public, third-party-only Intel Nano/Perth completion proof. NOT a VoiceStudio release."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile
import zipfile

EXPECTED = '1b7c70ce00e216d62a1eb36713f7b0d5531dbd7cfd7a9337f0c25fd1960d9350'
REPOS = {
    'chatterbox': ('https://github.com/resemble-ai/chatterbox.git', '5de7a54aa4e5e2baadb0182dde554908b48b85c2', 'chatterbox_tts-'),
    'perth': ('https://github.com/resemble-ai/Perth.git', 'ff1c8ac55a976971245cdd53c18d6131ca00d993', 'resemble_perth-'),
}

def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()

def run(*args, env=None):
    subprocess.run([str(x) for x in args], check=True, env=env)

def safe(name):
    if not name or name.startswith('/') or '\\' in name or ':' in name or any(x in ('', '.', '..') for x in name.split('/')):
        raise ValueError('unsafe archive member')
    return name

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--archive', required=True, type=Path)
    p.add_argument('--work', required=True, type=Path)
    args=p.parse_args()
    if platform.system() != 'Darwin' or platform.machine() != 'x86_64':
        raise RuntimeError('native Intel macOS required')
    archive=args.archive.resolve(); work=args.work.resolve()
    if sha(archive) != EXPECTED:
        raise ValueError('foundation SHA-256 mismatch')
    if work.exists():
        raise ValueError('work directory exists; refuse overwrite')
    work.mkdir(parents=True)
    root=work/'foundation'; root.mkdir()
    members=set(); inventory=None
    with tarfile.open(archive, 'r:gz') as tar:
        for m in tar:
            name=safe(m.name)
            if name.casefold() in members or not m.isfile() or m.mode & 0o7000:
                raise ValueError('duplicate/unsafe file')
            members.add(name.casefold())
            dst=root/name; dst.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(m) as src, dst.open('xb') as output:
                shutil.copyfileobj(src,output)
            dst.chmod(m.mode & 0o777)
    index=root/'native-foundation-inventory.json'
    obj=json.loads(index.read_bytes())
    if obj.get('purpose') != 'public-third-party-foundation' or obj.get('platform') != 'macos-x64':
        raise ValueError('wrong foundation inventory')
    indexed=obj['files']
    if len(indexed) != 63850 or len(members) != len(indexed)+1:
        raise ValueError('unexpected inventory count')
    for item in indexed:
        path=root/safe(item['path'])
        if not path.is_file() or path.stat().st_size != item['sizeBytes'] or sha(path) != item['sha256']:
            raise ValueError('foundation member differs: '+item['path'])
    index.unlink()
    py=root/'runtime/python/macos-x64/bin/python3'
    run(py,'-I','-c','import torch, torchaudio, numba, numpy; print(torch.__version__)')
    env={**os.environ,'PIP_DISABLE_PIP_VERSION_CHECK':'1','PIP_NO_CACHE_DIR':'1','PYTHONNOUSERSITE':'1','PYTHONDONTWRITEBYTECODE':'1'}
    wheels=work/'wheels'; wheels.mkdir()
    builder=work/'wheel-builder'
    run('python3','-m','venv',builder)
    builder_py=builder/'bin/python3'
    env['PATH']=str(builder/'bin')+os.pathsep+env.get('PATH','')
    run(builder_py,'-m','pip','install','packaging==26.3','uv_build==0.12.7','setuptools==80.9.0',env=env)
    built=[]
    for name,(url,commit,prefix) in REPOS.items():
        source=work/name
        run('git','clone','--filter=blob:none','--no-checkout',url,source)
        run('git','-C',source,'checkout','--detach',commit)
        actual=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
        if actual != commit: raise ValueError('upstream commit changed')
        run(builder_py,'-m','pip','wheel','--no-deps','--no-build-isolation','--wheel-dir',wheels,source,env=env)
        candidates=list(wheels.glob(prefix+'*.whl'))
        if len(candidates)!=1: raise ValueError('expected one wheel for '+name)
        built.append(candidates[0])
    # Install pinned source wheels first. Third-party dependencies are deliberately
    # resolved on Intel using pip's installed native conda providers.
    run(py,'-I','-m','pip','install','--no-deps',*built,env=env)
    # Capture an exact requirements plan; stop before a resolver substitutes native providers.
    constraint=work/'constraints.txt'
    constraint.write_text('torch==2.6.0\ntorchaudio==2.6.0\nnumpy==1.26.4\nnumba==0.68.0\nllvmlite==0.50.0\n')
    plan=work/'dependency-plan.json'
    run(py,'-I','-m','pip','install','--dry-run','--report',plan,'--constraint',constraint,'chatterbox-tts==0.1.7','resemble-perth==1.1.0',env=env)
    report=json.loads(plan.read_text())
    blocked={'torch','torchaudio','numpy','numba','llvmlite'}
    bad=[x['metadata']['name'] for x in report['install'] if x['metadata']['name'].lower().replace('_','-') in blocked]
    if bad:raise ValueError('pip proposed replacing conda native providers: '+str(bad))
    # Install dependencies with native core versions constrained. The existing
    # resolver audit above must pass before installation.
    probe = """import importlib.metadata as m,json
print(json.dumps({n:m.version(n) for n in ('torch','torchaudio','numpy','numba','llvmlite')}))"""
    expected_core={'torch':'2.6.0','torchaudio':'2.6.0','numpy':'1.26.4',
                   'numba':'0.68.0','llvmlite':'0.50.0'}
    before=json.loads(subprocess.check_output([str(py),'-I','-c',probe],env=env,text=True))
    if before!=expected_core:raise ValueError('Pinned Intel core mismatch: '+repr(before))
    run(py,'-I','-m','pip','install','--constraint',constraint,
        'chatterbox-tts==0.1.7','resemble-perth==1.1.0',env=env)
    after=json.loads(subprocess.check_output([str(py),'-I','-c',probe],env=env,text=True))
    if after!=before:raise ValueError('Pinned Intel core versions changed: '+repr(after))
    run(py,'-I','-m','pip','check',env=env)
    smoke="""import importlib,importlib.metadata as m,json
import torch,torchaudio,numpy,numba,llvmlite
assert m.version('chatterbox-tts')=='0.1.7'
assert m.version('resemble-perth')=='1.1.0'
for name in ('chatterbox','perth'):importlib.import_module(name)
print(json.dumps({'chatterbox':m.version('chatterbox-tts'),
                  'perth':m.version('resemble-perth'),'torch':torch.__version__}))"""
    run(py,'-I','-c',smoke,env=env)
    result={'status':'INTEL_PYTHON_DEPS_INSTALLED_AND_IMPORT_CHECKED','native':'macos-x64',
            'foundationSha256':EXPECTED,'builtWheels':[{'name':x.name,'sha256':sha(x)} for x in built],
            'dependenciesPlanned':len(report['install']),'coreVersions':after,
            'pipCheckPassed':True,'completeRuntime':False,'relocationAccepted':False}
    # Stage 3: public-only archive and independent second-location smoke test.
    # This does NOT perform private model-backed proof or Mach-O relocation acceptance.
    # Preserve all payload files, including the conda Python alias trees.
    candidate=work/'intel-open-source-runtime-candidate.tar.gz'
    if candidate.exists():raise ValueError('Refuse archive overwrite')
    with tarfile.open(candidate,'w:gz',format=tarfile.PAX_FORMAT) as t:
        for f in sorted(root.rglob('*')):
            if f.is_symlink():raise ValueError('Unexpected symlink in flattened runtime: '+str(f))
            if f.is_file():
                rel=f.relative_to(root).as_posix()
                t.add(f,arcname=rel,recursive=False)
    second=work/'Second Location With Spaces'
    second.mkdir()
    with tarfile.open(candidate,'r:gz') as t:
        for m in t:
            name=safe(m.name)
            if not m.isfile() or m.mode & 0o7000:raise ValueError('Unsafe candidate archive entry')
            dst=second/name
            dst.parent.mkdir(parents=True,exist_ok=True)
            with t.extractfile(m) as src,dst.open('xb') as output:
                shutil.copyfileobj(src,output)
            dst.chmod(m.mode & 0o777)
    second_py=second/'runtime/python/macos-x64/bin/python3'
    run(second_py,'-I','-c',smoke,env=env)
    run(second_py,'-I','-m','pip','check',env=env)
    result.update({'status':'INTEL_PUBLIC_ARCHIVE_SECOND_LOCATION_IMPORT_PASSED',
        'candidateArchive':candidate.name,
        'candidateSha256':sha(candidate),'candidateSizeBytes':candidate.stat().st_size,
        'secondLocationImportPassed':True,'secondLocationPipCheckPassed':True,
        'completeRuntime':False,'relocationAccepted':False,
        'disclaimer':'Provisional open-source archive only; no model-backed proof, native closure or licensed production acceptance'})
    (work/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
