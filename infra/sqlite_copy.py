"""Consistent SQLite copy for backup/restore: python sqlite_copy.py SRC DST. Stop the API first."""
import sqlite3
import sys

src, dst = sys.argv[1], sys.argv[2]
with sqlite3.connect(src) as a, sqlite3.connect(dst) as b:
    a.backup(b)
with sqlite3.connect(dst) as c:
    status = c.execute("pragma integrity_check").fetchone()[0]
print(dst, status)
sys.exit(0 if status == "ok" else 1)
