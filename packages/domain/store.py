"""Transactional SQLite document store with revision checks and snapshots."""

from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3

from .models import ConflictError, ValidationError, identifier, utcnow


class Store:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise ValidationError("База создана более новой версией приложения")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS research (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, document TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS history (
                    research_id TEXT NOT NULL, revision INTEGER NOT NULL, at TEXT NOT NULL,
                    action TEXT NOT NULL, actor TEXT NOT NULL, payload TEXT NOT NULL,
                    snapshot TEXT NOT NULL, PRIMARY KEY (research_id, revision),
                    FOREIGN KEY (research_id) REFERENCES research(id)
                );
                PRAGMA user_version = 1;
            """)
            db.commit()

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def create(self, state):
        value = deepcopy(state)
        value["id"] = identifier("research")
        value["revision"] = 1
        value["created_at"] = value["updated_at"] = utcnow()
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        with closing(self.connect()) as db, db:
            db.execute("INSERT INTO research VALUES (?,?,?,?,?,?)",
                       (value["id"], value["title"], 1, value["created_at"], value["updated_at"], encoded))
            db.execute("INSERT INTO history VALUES (?,?,?,?,?,?,?)",
                       (value["id"], 1, value["created_at"], "create", "owner", "{}", encoded))
        return value

    def get(self, research_id):
        with closing(self.connect()) as db:
            row = db.execute("SELECT document FROM research WHERE id=?", (research_id,)).fetchone()
        if row is None:
            raise KeyError("Исследование не найдено")
        return json.loads(row["document"])

    def list(self):
        with closing(self.connect()) as db:
            rows = db.execute("SELECT document FROM research ORDER BY updated_at DESC").fetchall()
        return [json.loads(row["document"]) for row in rows]

    def update(self, research_id, revision, action, actor, payload, mutate):
        with closing(self.connect()) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT document,revision FROM research WHERE id=?", (research_id,)).fetchone()
                if row is None:
                    raise KeyError("Исследование не найдено")
                if row["revision"] != revision:
                    raise ConflictError("Данные изменились. Обновите исследование перед сохранением.")
                state = json.loads(row["document"])
                mutate(state)
                state["revision"] += 1
                state["updated_at"] = utcnow()
                encoded = json.dumps(state, ensure_ascii=False, allow_nan=False)
                db.execute("UPDATE research SET title=?,revision=?,updated_at=?,document=? WHERE id=?",
                           (state["title"], state["revision"], state["updated_at"], encoded, research_id))
                db.execute("INSERT INTO history VALUES (?,?,?,?,?,?,?)",
                           (research_id, state["revision"], state["updated_at"], action, actor,
                            json.dumps(payload, ensure_ascii=False, allow_nan=False), encoded))
                db.commit()
            except BaseException:
                db.rollback()
                raise
        return state

    def history(self, research_id):
        self.get(research_id)
        with closing(self.connect()) as db:
            rows = db.execute("SELECT revision,at,action,actor,payload FROM history WHERE research_id=? ORDER BY revision",
                              (research_id,)).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]

    def snapshot(self, research_id, revision):
        with closing(self.connect()) as db:
            row = db.execute("SELECT snapshot FROM history WHERE research_id=? AND revision=?",
                              (research_id, revision)).fetchone()
        if row is None:
            raise KeyError("Версия не найдена")
        return json.loads(row["snapshot"])
