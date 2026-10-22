"""Small SQLite repository. No keys, account credentials or HTTP bodies in logs."""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import json
import sqlite3
from quantlab.config import DATA, SHANGHAI


def encode(value):
    return json.dumps(value, ensure_ascii=False, default=str, allow_nan=False)


class Store:
    def __init__(self, path=None):
        self.path = Path(path or DATA / "quantlab.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS experiments (
              id INTEGER PRIMARY KEY, created TEXT NOT NULL, name TEXT NOT NULL,
              config TEXT NOT NULL, metrics TEXT NOT NULL, curve TEXT NOT NULL,
              trades TEXT NOT NULL, rejections TEXT NOT NULL, fingerprint TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reports (
              id INTEGER PRIMARY KEY, created TEXT NOT NULL, kind TEXT NOT NULL,
              content TEXT NOT NULL, experiment_id INTEGER);
            CREATE TABLE IF NOT EXISTS api_usage (
              id INTEGER PRIMARY KEY, created TEXT NOT NULL, model TEXT NOT NULL,
              status TEXT NOT NULL, input_tokens INTEGER, output_tokens INTEGER,
              estimated_usd REAL, note TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit (
              id INTEGER PRIMARY KEY, created TEXT NOT NULL, action TEXT NOT NULL,
              details TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS watchlist (symbol TEXT PRIMARY KEY, name TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def now(self):
        return datetime.now(SHANGHAI).isoformat()

    def audit(self, action, details):
        with self.connect() as db:
            db.execute("INSERT INTO audit(created,action,details) VALUES(?,?,?)",
                       (self.now(), action, encode(details)))

    def setting(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def save_setting(self, key, value):
        # New setting and its audit event are committed atomically.
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, encode(value)))
            db.execute("INSERT INTO audit(created,action,details) VALUES(?,?,?)",
                       (self.now(), "setting_changed", encode({"key": key, "value": value})))

    def save_experiment(self, name, config, result, fingerprint):
        with self.connect() as db:
            cursor = db.execute('''INSERT INTO experiments
              (created,name,config,metrics,curve,trades,rejections,fingerprint)
              VALUES(?,?,?,?,?,?,?,?)''', (self.now(), name, encode(config),
              encode(result.metrics), result.curve.to_json(orient="records", date_format="iso"),
              encode(result.trades), encode(result.rejections), fingerprint))
            return cursor.lastrowid

    def rows(self, table, limit=200):
        if table not in {"experiments", "reports", "api_usage", "audit", "watchlist"}:
            raise ValueError("Unsupported table")
        ordering = "symbol" if table == "watchlist" else "id DESC"
        with self.connect() as db:
            return [dict(r) for r in db.execute(f"SELECT * FROM {table} ORDER BY {ordering} LIMIT ?", (limit,))]

    def watch(self, symbol, name, remove=False):
        with self.connect() as db:
            if remove:
                db.execute("DELETE FROM watchlist WHERE symbol=?", (symbol,))
            else:
                db.execute("INSERT OR REPLACE INTO watchlist VALUES(?,?)", (symbol, name))

    def report(self, kind, content, experiment_id=None):
        with self.connect() as db:
            return db.execute("INSERT INTO reports(created,kind,content,experiment_id) VALUES(?,?,?,?)",
                              (self.now(), kind, encode(content), experiment_id)).lastrowid

    def usage(self, model, status, input_tokens=None, output_tokens=None, estimated_usd=None, note=""):
        with self.connect() as db:
            db.execute('''INSERT INTO api_usage
             (created,model,status,input_tokens,output_tokens,estimated_usd,note) VALUES(?,?,?,?,?,?,?)''',
             (self.now(), model, status, input_tokens, output_tokens, estimated_usd, note))
