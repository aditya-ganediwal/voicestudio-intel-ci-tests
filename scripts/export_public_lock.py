"""Run only on the owner's local private checkout; emits public third-party pins only."""
import json, pathlib, sys
p=pathlib.Path(sys.argv[1] if len(sys.argv)>1 else 'config/macos-intel-proof.json')
o=pathlib.Path(sys.argv[2] if len(sys.argv)>2 else 'public-intel-lock.json')
d=json.loads(p.read_text(encoding='utf-8'))
assert d['platform']=='macos-x64' and d['pythonVersion']=='3.11.14'
assert d['torchVersion']=='2.6.0' and d['torchaudioVersion']=='2.6.0'
allowed={'name','version','build','subdir','url','sha256','size'}
packages=[{k:x[k] for k in ('name','version','build','subdir','url','sha256','size')} for x in d['condaPackages']]
assert len(packages)>=40 and len({x['name'] for x in packages})==len(packages)
for x in packages:
    assert x['url'].startswith('https://conda.anaconda.org/conda-forge/') and len(x['sha256'])==64 and x['size']>0
node={k:d['node'][k] for k in ('version','url','sha256')}
mm={k:d['micromamba'][k] for k in ('url','sha256','sizeBytes')}
whisper={k:d['whisper'][k] for k in ('repository','commit')}
assert node['url'].startswith('https://nodejs.org/dist/') and len(node['sha256'])==64
assert mm['url'].startswith('https://conda.anaconda.org/conda-forge/')
assert whisper['repository']=='https://github.com/ggml-org/whisper.cpp.git'
out={'schemaVersion':1,'platform':'macos-x64','purpose':'public-third-party-foundation','pythonVersion':d['pythonVersion'],'condaPackages':packages,'micromamba':mm,'node':node,'whisper':whisper,'excludedNumbaTbb':{'path':'lib/python3.11/site-packages/numba/np/ufunc/tbbpool.cpython-311-darwin.so','sha256':'2a30f66677662bb6744a99c3886b7c4915e196933fc0acbd3c5e2f63a704ff20'}}
o.write_text(json.dumps(out,sort_keys=True,indent=2)+'\n',encoding='utf-8')
print('Exported',len(packages),'public conda pins:',o)
