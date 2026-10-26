#!/usr/bin/env python3
"""Build a reproducible server source archive from an explicit file allowlist."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
METADATA = ('README.md','CONTRIBUTING.md','SECURITY.md','LICENSE','LICENSING.md','VERSION',
            'UPSTREAM_BASE_SHA','.gitignore','.dockerignore','requirements.txt',
            'requirements-frozen.txt','requirements-dev.txt','run.py',
            'LICENSES/NOTICE.md','LICENSES/PROJECT_SCOPE.md','LICENSES/VRCX-LICENSE',
            'examples/app.example.json','.github/workflows/ci.yml','.github/workflows/release.yml',
            'server/README.md','server/Dockerfile','server/compose.yaml')


def source_paths(root=ROOT):
    root=Path(root).resolve()
    paths={name:root/name for name in METADATA}
    groups=(('src/webui',{'.py','.js','.css','.html'}),('backend',{'.py'}),
            ('src/application',{'.py','.png','.svg'}),('tests',{'.py','.cjs'}),('scripts',{'.py','.sh'}))
    for folder,suffixes in groups:
        for path in (root/folder).rglob('*'):
            if path.is_file() and path.suffix in suffixes:
                paths[path.relative_to(root).as_posix()]=path
    for name,path in paths.items():
        info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or path.resolve()!=path:
            raise ValueError('Source files must be ordinary files without links: '+name)
        if path.name in ('config.json','application.json') or path.name.startswith('auth') and path.suffix=='.json':
            raise ValueError('Private runtime data cannot be packaged')
    return paths


def build(output,root=ROOT):
    root=Path(root).resolve()
    if not (root/'LICENSE').is_file(): raise ValueError('A project license is required')
    contents={name:path.read_bytes() for name,path in source_paths(root).items()}
    version=(root/'VERSION').read_text().strip()
    manifest={'format':1,'kind':'server-source','version':version,
              'files':{name:hashlib.sha256(data).hexdigest() for name,data in sorted(contents.items())}}
    contents['public-manifest.json']=(json.dumps(manifest,indent=2)+'\n').encode()
    output=Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.is_symlink() or output.exists() and output.stat().st_nlink!=1:
        raise ValueError('Archive output cannot be a link')
    fd,temporary=tempfile.mkstemp(prefix='.source-archive-',dir=output.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            with gzip.GzipFile(filename='',fileobj=stream,mode='wb',mtime=0) as compressed:
                with tarfile.open(fileobj=compressed,mode='w') as archive:
                    for name,data in sorted(contents.items()):
                        member=tarfile.TarInfo(name);member.size=len(data);member.mode=0o755 if name.endswith('.sh') or name=='run.py' else 0o644;member.mtime=0
                        archive.addfile(member,io.BytesIO(data))
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,output)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'dist'/('vrcx-cloud-'+(ROOT/'VERSION').read_text().strip()+'-server.tar.gz'))
    args=parser.parse_args()
    result=build(args.output)
    print(str(args.output)+': '+str(len(result['files']))+' source files')
