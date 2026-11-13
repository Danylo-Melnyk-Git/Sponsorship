"""Argon2id passwords, opaque revocable sessions and durable login throttling."""
from contextlib import contextmanager
import hashlib
import re
import secrets
import sqlite3
import time

from argon2 import PasswordHasher, Type
from argon2.exceptions import VerificationError, InvalidHashError

ROLES = ("admin", "approver", "reviewer", "researcher", "viewer")
HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1, type=Type.ID)
DUMMY = HASHER.hash(secrets.token_urlsafe(32))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class AccessError(Exception):
    def __init__(self, message="Недостаточно прав", status=403):
        super().__init__(message)
        self.status = status


class AuthStore:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY,password TEXT NOT NULL,role TEXT NOT NULL,active INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,username TEXT NOT NULL,csrf TEXT NOT NULL,expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts(at REAL NOT NULL,account TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS attempts_at ON attempts(at);
                CREATE TABLE IF NOT EXISTS audit(at REAL NOT NULL,username TEXT NOT NULL,event TEXT NOT NULL,reference TEXT NOT NULL);
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

    def audit(self, username, event, reference=""):
        with self.db() as db:
            db.execute("INSERT INTO audit VALUES(?,?,?,?)", (time.time(), username, event, reference[:200]))

    def add_user(self, username, password, role):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,63}", username) or role not in ROLES:
            raise ValueError("Имя: 3–64 строчных латинских символа/цифры/_.-; роль должна быть известна")
        if not isinstance(password, str) or not 15 <= len(password) <= 256:
            raise ValueError("Пароль: от 15 до 256 символов")
        encoded = HASHER.hash(password)
        with self.db() as db:
            db.execute("INSERT INTO users VALUES(?,?,?,1)", (username, encoded, role))
        self.audit(username, "account_created_by_operator")

    def change_user(self, username, *, role=None, active=None, password=None):
        if role is not None and role not in ROLES:
            raise ValueError("Неизвестная роль")
        if password is not None and not 15 <= len(password) <= 256:
            raise ValueError("Пароль: от 15 до 256 символов")
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            if old is None:
                raise ValueError("Пользователь не найден")
            new_role = role or old["role"]
            new_active = old["active"] if active is None else int(active)
            if old["role"] == "admin" and old["active"] and (new_role != "admin" or not new_active):
                if db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0] <= 1:
                    raise ValueError("Нельзя отключить/понизить последнего активного администратора")
            db.execute("UPDATE users SET password=?,role=?,active=? WHERE username=?",
                       (HASHER.hash(password) if password is not None else old["password"], new_role, new_active, username))
            db.execute("DELETE FROM sessions WHERE username=?", (username,))
        self.audit(username, "account_changed_sessions_revoked_by_operator")

    def login(self, username, password, hours):
        if not isinstance(username, str) or not isinstance(password, str) or len(username) > 64 or len(password) > 256:
            raise AccessError("Неверные данные входа", 401)
        now, account = time.time(), digest(username)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM attempts WHERE at<?", (now-900,))
            count = db.execute("SELECT COUNT(*) FROM attempts WHERE account=?", (account,)).fetchone()[0]
            total = db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
            if count >= 8 or total >= 100:
                raise AccessError("Слишком много попыток. Повторите позднее", 429)
            db.execute("INSERT INTO attempts VALUES(?,?)", (now, account))
            user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        try:
            valid = HASHER.verify(user["password"] if user else DUMMY, password)
        except (VerificationError, InvalidHashError):
            valid = False
        if not valid or user is None or not user["active"]:
            self.audit("unauthenticated", "login_failed", account)
            raise AccessError("Неверные данные входа", 401)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.db() as db:
            # Recheck inside the write transaction: disable/reset must win races.
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            if current is None or not current["active"] or current["password"] != user["password"] or current["role"] != user["role"]:
                raise AccessError("Повторите вход", 401)
            db.execute("DELETE FROM sessions WHERE expires<?", (now,))
            db.execute("INSERT INTO sessions VALUES(?,?,?,?)", (digest(token), username, csrf, now+3600*hours))
        self.audit(username, "login")
        return token, csrf

    def session(self, token):
        if not token or len(token) > 200:
            raise AccessError("Войдите в кабинет", 401)
        with self.db() as db:
            row = db.execute("SELECT u.username,u.role,s.csrf FROM sessions s JOIN users u ON u.username=s.username "
                             "WHERE s.token=? AND s.expires>? AND u.active=1", (digest(token), time.time())).fetchone()
        if row is None:
            raise AccessError("Войдите в кабинет", 401)
        return dict(row)

    def logout(self, token):
        with self.db() as db:
            db.execute("DELETE FROM sessions WHERE token=?", (digest(token),))
