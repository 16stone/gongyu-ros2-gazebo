"""Append-only JSONL message bus shared by Webots controllers on one host."""
import fcntl
import json
import os


class Bus:
    def __init__(self, root):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def path(self, name):
        return os.path.join(self.root, name)

    def append(self, name, obj):
        p = self.path(name)
        with open(p, 'a', encoding='utf-8') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(json.dumps(obj, separators=(',', ':'), ensure_ascii=False) + '\n')
            f.flush()
            fcntl.flock(f, fcntl.LOCK_UN)

    def read(self, name):
        p = self.path(name)
        if not os.path.exists(p):
            return []
        out = []
        with open(p, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    def last(self, name):
        rows = self.read(name)
        return rows[-1] if rows else None
