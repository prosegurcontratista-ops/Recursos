#!/usr/bin/env python3
"""Repositorio de Recursos Tecnicos - Cash Today & Prosegur TM"""

import os, json, sqlite3
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify, send_file, abort
from werkzeug.utils import secure_filename

BASE_DIR    = Path(__file__).parent.resolve()
DB_PATH     = BASE_DIR / "repositorio.db"
CONFIG_PATH = BASE_DIR / "config.json"

ALLOWED_EXT = {
    ".pdf", ".docx", ".xlsx", ".pptx", ".txt",
    ".exe", ".msi", ".bat", ".cmd", ".ps1",
    ".zip", ".rar", ".7z", ".iso", ".tib",
    ".png", ".jpg", ".jpeg", ".gif", ".mp4", ".avi",
}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024

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
    p = BASE_DIR / "archivos"
    p.mkdir(parents=True, exist_ok=True)
    (p / "cash_today").mkdir(exist_ok=True)
    (p / "prosegur_atm").mkdir(exist_ok=True)
    return p

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa TEXT NOT NULL, categoria TEXT NOT NULL,
                titulo TEXT NOT NULL, descripcion TEXT, contenido TEXT,
                archivo_path TEXT, archivo_nombre TEXT,
                fecha TEXT NOT NULL, tags TEXT)
        """)
        db.commit()

@app.route("/api/items", methods=["GET"])
def get_items():
    empresa=request.args.get("empresa",""); categoria=request.args.get("categoria","")
    busqueda=request.args.get("busqueda","")
    sql="SELECT * FROM items WHERE 1=1"; params=[]
    if empresa: sql+=" AND empresa=?"; params.append(empresa)
    if categoria: sql+=" AND categoria=?"; params.append(categoria)
    if busqueda: sql+=" AND (titulo LIKE ? OR descripcion LIKE ? OR tags LIKE ?)"; params+=[f"%{busqueda}%"]*3
    sql+=" ORDER BY fecha DESC"
    with get_db() as db: rows=db.execute(sql,params).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/items", methods=["POST"])
def add_item():
    empresa=request.form.get("empresa","").strip(); categoria=request.form.get("categoria","").strip()
    titulo=request.form.get("titulo","").strip(); desc=request.form.get("descripcion","").strip()
    contenido=request.form.get("contenido","").strip(); tags=request.form.get("tags","").strip()
    fecha=datetime.now().strftime("%Y-%m-%d %H:%M")
    if not (empresa and categoria and titulo):
        return jsonify({"error":"Faltan campos obligatorios"}),400
    archivo_path=archivo_nombre=None
    f=request.files.get("archivo")
    if f and f.filename:
        ext=Path(f.filename).suffix.lower()
        if ext not in ALLOWED_EXT: return jsonify({"error":f"Tipo no permitido: {ext}"}),400
        ns=secure_filename(f.filename); fd2=get_files_dir()/empresa; fd2.mkdir(parents=True,exist_ok=True)
        dest=fd2/ns
        if dest.exists():
            ts=datetime.now().strftime("%Y%m%d%H%M%S"); dest=fd2/f"{Path(ns).stem}_{ts}{ext}"
        f.save(str(dest)); archivo_path=str(dest); archivo_nombre=dest.name
    with get_db() as db:
        cur=db.execute("INSERT INTO items (empresa,categoria,titulo,descripcion,contenido,archivo_path,archivo_nombre,fecha,tags) VALUES (?,?,?,?,?,?,?,?,?)",
            (empresa,categoria,titulo,desc,contenido,archivo_path,archivo_nombre,fecha,tags))
        db.commit(); new_id=cur.lastrowid
    with get_db() as db: row=db.execute("SELECT * FROM items WHERE id=?",(new_id,)).fetchone()
    return jsonify(dict(row)),201

@app.route("/api/items/<int:i>", methods=["DELETE"])
def delete_item(i):
    with get_db() as db:
        row=db.execute("SELECT * FROM items WHERE id=?",(i,)).fetchone()
        if not row: return jsonify({"error":"No encontrado"}),404
        if row["archivo_path"]:
            try: Path(row["archivo_path"]).unlink(missing_ok=True)
            except: pass
        db.execute("DELETE FROM items WHERE id=?",(i,)); db.commit()
    return jsonify({"ok":True})

@app.route("/api/open/<int:i>")
def open_file(i):
    with get_db() as db: row=db.execute("SELECT * FROM items WHERE id=?",(i,)).fetchone()
    if not row or not row["archivo_path"]: return jsonify({"error":"Sin archivo"}),404
    path=Path(row["archivo_path"])
    if not path.exists(): return jsonify({"error":"No encontrado"}),404
    return send_file(str(path), as_attachment=False, download_name=row["archivo_nombre"])

@app.route("/api/download/<int:i>")
def download_file(i):
    with get_db() as db: row=db.execute("SELECT * FROM items WHERE id=?",(i,)).fetchone()
    if not row or not row["archivo_path"]: abort(404)
    path=Path(row["archivo_path"])
    if not path.exists(): abort(404)
    return send_file(str(path),as_attachment=True,download_name=row["archivo_nombre"])

@app.route("/api/config", methods=["GET"])
def get_config():
    cfg=load_config(); cfg["detected_onedrives"]=[]
    cfg["storage_path_effective"]=str(get_files_dir()); return jsonify(cfg)

@app.route("/api/config", methods=["POST"])
def set_config():
    data=request.get_json(); path_str=(data.get("storage_path") or "").strip()
    cfg=load_config(); cfg["storage_path"]=path_str; cfg["onedrive_configured"]=bool(path_str)
    save_config(cfg); return jsonify({"ok":True,"storage_path":path_str})

@app.route("/api/stats")
def stats():
    with get_db() as db:
        total=db.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        ct=db.execute("SELECT COUNT(*) FROM items WHERE empresa='cash_today'").fetchone()[0]
        ps=db.execute("SELECT COUNT(*) FROM items WHERE empresa='prosegur_atm'").fetchone()[0]
    return jsonify({"total":total,"cash_today":ct,"prosegur_atm":ps})

@app.route("/")
def index():
    return open(Path(__file__).parent / "ui.html", encoding="utf-8").read()

init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=False)
