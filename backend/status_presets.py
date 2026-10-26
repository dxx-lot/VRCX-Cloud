"""F-18 状态预设存储（上游 useStatusPresets.js：本地存储、MAX 10、去重、删除）"""
import sqlite3


class StatusPresetStore:
    MAX = 10

    def __init__(self, db_path):
        self.db = sqlite3.connect(str(db_path))
        self.db.execute("""CREATE TABLE IF NOT EXISTS status_presets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL,
            desc TEXT NOT NULL,
            UNIQUE(status, desc))""")

    def list(self):
        return [{"status": r[0], "desc": r[1]}
                for r in self.db.execute("SELECT status, desc FROM status_presets ORDER BY id")]

    def add(self, status, desc):
        if self.count() >= self.MAX:
            return "limit"
        try:
            self.db.execute("INSERT INTO status_presets (status, desc) VALUES (?,?)",
                            (status, desc))
            self.db.commit()
            return "ok"
        except sqlite3.IntegrityError:
            return "exists"

    def count(self):
        return self.db.execute("SELECT count(*) FROM status_presets").fetchone()[0]

    def remove(self, index):
        row = self.db.execute("SELECT id FROM status_presets ORDER BY id LIMIT 1 OFFSET ?",
                              (index,)).fetchone()
        if row:
            self.db.execute("DELETE FROM status_presets WHERE id=?", (row[0],))
            self.db.commit()
