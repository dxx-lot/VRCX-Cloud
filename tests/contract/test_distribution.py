"""Server source packaging, access documentation and release scope."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tarfile

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('source_package',ROOT/'scripts/export-public.py')
package=importlib.util.module_from_spec(spec);spec.loader.exec_module(package)


def test_source_archive_is_reproducible_and_contains_no_runtime_data(tmp_path):
    staging=tmp_path/'source'
    for name,source in package.source_paths(ROOT).items():
        target=staging/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    (staging/'data').mkdir();(staging/'data/private.db').write_bytes(b'synthetic private fixture')
    (staging/'config.json').write_text('{}')
    first,second=tmp_path/'first.tar.gz',tmp_path/'second.tar.gz'
    manifest=package.build(first,staging);package.build(second,staging)
    assert first.read_bytes()==second.read_bytes()
    assert manifest['version']==(ROOT/'VERSION').read_text().strip()
    with tarfile.open(first) as archive:
        names=archive.getnames()
        assert 'config.json' not in names and not any(name.startswith(('data/','.git/','dist/','artifacts/')) for name in names)
        for member in archive.getmembers():
            assert member.isfile() and member.uid==member.gid==member.mtime==0 and not member.uname and not member.gname
            assert member.mode==(0o755 if member.name.endswith('.sh') or member.name=='run.py' else 0o644)
            if member.name!='public-manifest.json':
                assert hashlib.sha256(archive.extractfile(member).read()).hexdigest()==manifest['files'][member.name]


def test_server_access_and_license_are_documented():
    for name in ('README.md','server/README.md','SECURITY.md'):
        assert '不包含公网防护' in (ROOT/name).read_text()
    text=(ROOT/'server/README.md').read_text()
    assert all(word in text for word in ('本机','局域网','互联网','HTTPS','手机','浏览器'))
    assert 'MIT License' in (ROOT/'LICENSES/VRCX-LICENSE').read_text()
    assert 'noncommercial purposes only' in (ROOT/'LICENSE').read_text()
    assert 'VRCX-Cloud/1.0.0 (unofficial self-hosted client)' in (ROOT/'src/application/launcher.py').read_text()


def test_workflows_only_validate_server_source():
    ci=(ROOT/'.github/workflows/ci.yml').read_text()
    workflow=(ROOT/'.github/workflows/release.yml').read_text()
    assert 'ubuntu-22.04' in ci and 'workflow_dispatch:' in workflow
    assert '  push:' not in workflow
    assert 'scripts/export-public.py' in workflow and 'docker compose' in workflow
    dockerfile=(ROOT/'server/Dockerfile').read_text()
    dockerignore=(ROOT/'.dockerignore').read_text().splitlines()
    assert 'COPY scripts/check-runtime.py' in dockerfile
    assert '!scripts/check-runtime.py' in dockerignore
    for text in (ci,workflow):
        assert not any(word in text for word in ('windows-','macos-','build-desktop.py','gh release create','contents: write'))
