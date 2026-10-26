"""Static assets and a content-based version shared by HTML and UI polling."""
import hashlib
import mimetypes
from pathlib import Path


class Assets:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.root = (self.directory / "static").resolve()
        self.template = self.directory / "templates" / "index.html"
        self._stamp = None
        self._version = None

    def version(self):
        paths = [self.directory / "web.py", self.template]
        if (self.directory / "vrc_watch.py").exists():
            paths.append(self.directory / "vrc_watch.py")
        paths += sorted(self.root.rglob("*.js")) + sorted(self.root.rglob("*.css"))
        paths += sorted((self.directory / "services").glob("*.py"))
        stamp = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in paths)
        if stamp != self._stamp:
            digest = hashlib.sha256()
            for p in paths:
                digest.update(p.relative_to(self.directory).as_posix().encode())
                digest.update(p.read_bytes())
            self._version = digest.hexdigest()[:16]
            self._stamp = stamp
        return self._version

    def page(self):
        return self.template.read_text(encoding="utf-8").replace("__UI_VER__", self.version()).encode("utf-8")

    def resolve(self, relative):
        target = (self.root / relative).resolve()
        if self.root not in target.parents or not target.is_file():
            return None
        if target.suffix not in (".js", ".css"):
            return None
        return target, mimetypes.guess_type(str(target))[0] or "application/octet-stream"
