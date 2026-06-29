#!/usr/bin/env python3
"""Repositorio de Recursos Tecnicos - Cash Today & Prosegur TM"""

import os, json, subprocess, webbrowser, threading, time
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify, send_file, abort
from werkzeug.utils import secure_filename

BASE_DIR    = Path(__file__).parent.resolve()
CONFIG_PATH = BASE_DIR / "config.json"

# ── Base de datos: PostgreSQL en Render, SQLite en local ──────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
USE_PG = bool(DATABASE_URL)

if not USE_PG:
    import sqlite3
    DB_PATH = BASE_DIR / "repositorio.db"

ALLOWED_EXT = {
    ".pdf", ".docx", ".xlsx", ".pptx", ".txt",
    ".exe", ".msi", ".bat", ".cmd", ".ps1",
    ".zip", ".rar", ".7z", ".iso", ".tib",
    ".png", ".jpg", ".jpeg", ".gif", ".mp4", ".avi",
}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024

# ── Config ────────────────────────────────────────────────────────────────────
def load_config():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"storage_path": "", "onedrive_configured": False}

def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

def get_files_dir():
    cfg = load_config()
    p = Path(cfg["storage_path"]) if cfg.get("storage_path") else BASE_DIR / "archivos"
    p.mkdir(parents=True, exist_ok=True)
    (p / "cash_today").mkdir(exist_ok=True)
    (p / "prosegur_atm").mkdir(exist_ok=True)
    return p

def detect_onedrive():
    candidates = []
    try:
        for d in Path.home().iterdir():
            if d.is_dir() and "onedrive" in d.name.lower():
                candidates.append(str(d))
    except Exception:
        pass
    return candidates

# ── Base de datos ─────────────────────────────────────────────────────────────
def get_db():
    if USE_PG:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        return conn
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

def ph():
    return "%s" if USE_PG else "?"

def init_db():
    conn = get_db()
    cur = conn.cursor()
    if USE_PG:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id SERIAL PRIMARY KEY,
                empresa TEXT NOT NULL, categoria TEXT NOT NULL,
                titulo TEXT NOT NULL, descripcion TEXT, contenido TEXT,
                archivo_path TEXT, archivo_nombre TEXT,
                fecha TEXT NOT NULL, tags TEXT)
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa TEXT NOT NULL, categoria TEXT NOT NULL,
                titulo TEXT NOT NULL, descripcion TEXT, contenido TEXT,
                archivo_path TEXT, archivo_nombre TEXT,
                fecha TEXT NOT NULL, tags TEXT)
        """)
    conn.commit()
    conn.close()

# ── Rutas API ─────────────────────────────────────────────────────────────────
@app.route("/api/items", methods=["GET"])
def get_items():
    empresa  = request.args.get("empresa", "")
    categoria = request.args.get("categoria", "")
    busqueda = request.args.get("busqueda", "")
    p = ph()
    sql = "SELECT * FROM items WHERE 1=1"; params = []
    if empresa:   sql += f" AND empresa={p}";   params.append(empresa)
    if categoria: sql += f" AND categoria={p}"; params.append(categoria)
    if busqueda:
        sql += f" AND (titulo LIKE {p} OR descripcion LIKE {p} OR tags LIKE {p})"
        params += [f"%{busqueda}%"] * 3
    sql += " ORDER BY fecha DESC"
    conn = get_db(); cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall(); conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/items", methods=["POST"])
def add_item():
    empresa   = request.form.get("empresa", "").strip()
    categoria = request.form.get("categoria", "").strip()
    titulo    = request.form.get("titulo", "").strip()
    desc      = request.form.get("descripcion", "").strip()
    contenido = request.form.get("contenido", "").strip()
    tags      = request.form.get("tags", "").strip()
    fecha     = datetime.now().strftime("%Y-%m-%d %H:%M")
    if not (empresa and categoria and titulo):
        return jsonify({"error": "Faltan campos obligatorios"}), 400
    archivo_path = archivo_nombre = None
    f = request.files.get("archivo")
    if f and f.filename:
        ext = Path(f.filename).suffix.lower()
        if ext not in ALLOWED_EXT:
            return jsonify({"error": f"Tipo no permitido: {ext}"}), 400
        ns = secure_filename(f.filename)
        fd2 = get_files_dir() / empresa; fd2.mkdir(parents=True, exist_ok=True)
        dest = fd2 / ns
        if dest.exists():
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            dest = fd2 / f"{Path(ns).stem}_{ts}{ext}"
        f.save(str(dest)); archivo_path = str(dest); archivo_nombre = dest.name
    p = ph()
    conn = get_db(); cur = conn.cursor()
    if USE_PG:
        cur.execute(
            f"INSERT INTO items (empresa,categoria,titulo,descripcion,contenido,archivo_path,archivo_nombre,fecha,tags) VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p}) RETURNING id",
            (empresa, categoria, titulo, desc, contenido, archivo_path, archivo_nombre, fecha, tags))
        new_id = cur.fetchone()["id"]
    else:
        cur.execute(
            f"INSERT INTO items (empresa,categoria,titulo,descripcion,contenido,archivo_path,archivo_nombre,fecha,tags) VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p})",
            (empresa, categoria, titulo, desc, contenido, archivo_path, archivo_nombre, fecha, tags))
        new_id = cur.lastrowid
    conn.commit()
    cur.execute(f"SELECT * FROM items WHERE id={p}", (new_id,))
    row = cur.fetchone(); conn.close()
    return jsonify(dict(row)), 201

@app.route("/api/items/<int:i>", methods=["DELETE"])
def delete_item(i):
    p = ph(); conn = get_db(); cur = conn.cursor()
    cur.execute(f"SELECT * FROM items WHERE id={p}", (i,))
    row = cur.fetchone()
    if not row: conn.close(); return jsonify({"error": "No encontrado"}), 404
    if row["archivo_path"]:
        try: Path(row["archivo_path"]).unlink(missing_ok=True)
        except: pass
    cur.execute(f"DELETE FROM items WHERE id={p}", (i,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/open/<int:i>")
def open_file(i):
    p = ph(); conn = get_db(); cur = conn.cursor()
    cur.execute(f"SELECT * FROM items WHERE id={p}", (i,))
    row = cur.fetchone(); conn.close()
    if not row or not row["archivo_path"]: return jsonify({"error": "Sin archivo"}), 404
    path = Path(row["archivo_path"])
    if not path.exists(): return jsonify({"error": "No encontrado: " + str(path)}), 404
    try: os.startfile(str(path))
    except AttributeError: subprocess.Popen(["xdg-open", str(path)])
    return jsonify({"ok": True})

@app.route("/api/download/<int:i>")
def download_file(i):
    p = ph(); conn = get_db(); cur = conn.cursor()
    cur.execute(f"SELECT * FROM items WHERE id={p}", (i,))
    row = cur.fetchone(); conn.close()
    if not row or not row["archivo_path"]: abort(404)
    path = Path(row["archivo_path"])
    if not path.exists(): abort(404)
    return send_file(str(path), as_attachment=True, download_name=row["archivo_nombre"])

@app.route("/api/config", methods=["GET"])
def get_config():
    cfg = load_config()
    cfg["detected_onedrives"] = detect_onedrive()
    cfg["storage_path_effective"] = str(get_files_dir())
    return jsonify(cfg)

@app.route("/api/config", methods=["POST"])
def set_config():
    data = request.get_json()
    path_str = (data.get("storage_path") or "").strip()
    if path_str:
        try: Path(path_str).mkdir(parents=True, exist_ok=True)
        except Exception as e: return jsonify({"error": f"No se pudo crear: {e}"}), 400
    cfg = load_config(); cfg["storage_path"] = path_str; cfg["onedrive_configured"] = bool(path_str)
    save_config(cfg); get_files_dir()
    return jsonify({"ok": True, "storage_path": path_str})

@app.route("/api/stats")
def stats():
    p = ph(); conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as c FROM items"); total = cur.fetchone()["c"]
    cur.execute(f"SELECT COUNT(*) as c FROM items WHERE empresa={p}", ("cash_today",)); ct = cur.fetchone()["c"]
    cur.execute(f"SELECT COUNT(*) as c FROM items WHERE empresa={p}", ("prosegur_atm",)); ps = cur.fetchone()["c"]
    conn.close()
    return jsonify({"total": total, "cash_today": ct, "prosegur_atm": ps})

@app.route("/")
def index():
    return open(Path(__file__).parent / "ui.html", encoding="utf-8").read()

def open_browser():
    time.sleep(1.2)
    webbrowser.open("http://127.0.0.1:5050")

if __name__ == "__main__":
    init_db()
    print("=" * 55)
    print("  Repositorio Tecnico - Cash Today & Prosegur ATM")
    print("  http://127.0.0.1:5050")
    print("  Presiona Ctrl+C para cerrar")
    print("=" * 55)
    if not USE_PG:
        threading.Thread(target=open_browser, daemon=True).start()
    app.run(host="0.0.0.0", port=5050, debug=False)

