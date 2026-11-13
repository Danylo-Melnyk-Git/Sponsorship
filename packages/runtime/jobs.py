"""Durable drafts with idempotency, reservations, cancellation and no auto-retry."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid


class JobStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,username TEXT NOT NULL,idem TEXT NOT NULL,
                    request_hash TEXT NOT NULL,research_id TEXT NOT NULL,revision INTEGER NOT NULL,kind TEXT NOT NULL,
                    state TEXT NOT NULL,created REAL NOT NULL,started REAL,finished REAL,input TEXT NOT NULL,output TEXT,
                    UNIQUE(username,idem));
                CREATE INDEX IF NOT EXISTS jobs_scope ON jobs(research_id,kind);
                CREATE INDEX IF NOT EXISTS jobs_created ON jobs(created);
            """)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, username, idem, state, kind, payload, daily_limit, search_used=0, search_limit=0):
        if not isinstance(idem, str) or not 8 <= len(idem) <= 100:
            raise ValueError("Нужен Idempotency-Key длиной 8–100 символов")
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True)
        if len(encoded.encode("utf-8")) > 100000:
            raise ValueError("Контекст слишком большой; сократите материалы для внешнего провайдера")
        signature = hashlib.sha256(encoded.encode()).hexdigest()
        now = time.time()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM jobs WHERE username=? AND idem=?", (username, idem)).fetchone()
            if old:
                if old["request_hash"] != signature or old["research_id"] != state["id"] or old["revision"] != state["revision"] or old["kind"] != kind:
                    raise ValueError("Этот Idempotency-Key относится к другому запросу")
                return self.public(old)
            count = db.execute("SELECT COUNT(*) FROM jobs WHERE created>? AND state!='cancelled'", (now-86400,)).fetchone()[0]
            if count >= daily_limit:
                raise ValueError("Общий лимит заданий за последние 24 часа исчерпан")
            if kind == "search":
                # Finished jobs are already in search_log (search_used); interrupted calls may have been billed.
                reserved = db.execute("SELECT COUNT(*) FROM jobs WHERE research_id=? AND kind='search' AND state IN ('queued','running','interrupted')", (state["id"],)).fetchone()[0]
                if search_used + reserved >= search_limit:
                    raise ValueError("Лимит поиска исчерпан с учётом резервов очереди")
            job_id = "job-" + uuid.uuid4().hex
            db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,'queued',?,NULL,NULL,?,NULL)",
                       (job_id, username, idem, signature, state["id"], state["revision"], kind, now, encoded))
            return self.public(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    @staticmethod
    def public(row):
        result = {k: row[k] for k in ("id", "username", "research_id", "revision", "kind", "state", "created", "started", "finished")}
        result["output"] = json.loads(row["output"]) if row["output"] else None
        return result

    def list(self, research_id):
        with self.db() as db:
            return [self.public(row) for row in db.execute("SELECT * FROM jobs WHERE research_id=? ORDER BY created DESC LIMIT 100", (research_id,))]

    def get(self, job_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError("Задание не найдено")
        return {**self.public(row), "input": json.loads(row["input"])}

    def active_inputs(self, research_id, kind):
        with self.db() as db:
            return [json.loads(row["input"]) for row in db.execute(
                "SELECT input FROM jobs WHERE research_id=? AND kind=? AND state IN ('queued','running','interrupted')",
                (research_id, kind))]

    def cancel(self, job_id, research_id):
        with self.db() as db:
            changed = db.execute("UPDATE jobs SET state='cancelled',finished=? WHERE id=? AND research_id=? AND state='queued'",
                                 (time.time(), job_id, research_id)).rowcount
            if not changed:
                raise ValueError("Отмена возможна только до начала внешнего запроса")

    def claim(self):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            # A crashed/timed-out call may have been billed. Never resend automatically.
            db.execute("UPDATE jobs SET state='interrupted',finished=? WHERE state='running' AND started<?", (time.time(), time.time()-300))
            row = db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
            if row is None:
                return None
            db.execute("UPDATE jobs SET state='running',started=? WHERE id=?", (time.time(), row["id"]))
            return {**dict(row), "input": json.loads(row["input"])}

    def finish(self, job_id, state, output):
        if state not in ("completed", "failed", "import_rejected"):
            raise ValueError("Недопустимый итог")
        with self.db() as db:
            db.execute("UPDATE jobs SET state=?,finished=?,output=? WHERE id=? AND state='running'",
                       (state, time.time(), json.dumps(output, ensure_ascii=False, allow_nan=False), job_id))
