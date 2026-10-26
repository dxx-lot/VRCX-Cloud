#!/usr/bin/env python3
"""Package only allowlisted runtime source; never walk private instance data."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def files(root=ROOT):
    web = root / 'src' / 'webui'
    selected = {Path(p.name): p for p in web.glob('*.py')}
    for folder, extensions in [('services', {'.py'}), ('static', {'.js', '.css'}), ('templates', {'.html'})]:
        selected.update({p.relative_to(web): p for p in (web / folder).rglob('*') if p.is_file() and p.suffix in extensions})
    selected.update({Path('domain') / p.name: p for p in (root / 'backend').glob('*.py')})
    selected.update({Path(p.name): p for p in root.glob('requirements*.txt') if 'dev' not in p.name})
    for name in ['NOTICE.md','VRCX-LICENSE']:
        license_path=root/'LICENSES'/name
        if license_path.is_file(): selected[Path('LICENSES')/name]=license_path
    return selected


def build(output, root=ROOT):
    contents = {name.as_posix(): p.read_bytes() for name, p in files(root).items()}
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, stderr=subprocess.DEVNULL, text=True).strip()
        dirty = bool(subprocess.check_output(['git', 'status', '--porcelain', '--', 'src/webui', 'backend', 'requirements.txt', 'requirements-frozen.txt'], cwd=root, stderr=subprocess.DEVNULL, text=True))
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = 'unknown', True
    manifest = {'format': 1, 'base_commit': commit, 'runtime_dirty': dirty,
                'files': {name: hashlib.sha256(data).hexdigest() for name, data in sorted(contents.items())}}
    contents['release-manifest.json'] = (json.dumps(manifest, ensure_ascii=False, indent=2)+'\n').encode()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Fixed tar headers avoid host paths, usernames and timestamps in the release.
    with tarfile.open(output, 'w:gz') as archive:
        for name, data in sorted(contents.items()):
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), 0o644, 0
            archive.addfile(info, io.BytesIO(data))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'artifacts'/'release'/'vrcx-cloud-framework.tar.gz')
    args = parser.parse_args()
    manifest = build(args.output)
    print(f'{args.output}: {len(manifest["files"])} runtime files; runtime_dirty={manifest["runtime_dirty"]}')
