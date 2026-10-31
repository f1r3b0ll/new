import os
import uuid
import sqlite3
from datetime import datetime

from flask import (Flask, render_template, request, redirect,
                   url_for, session, send_from_directory, flash)
from werkzeug.utils import secure_filename
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

# ==================== НАСТРОЙКИ ====================
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "228128")

DB_PATH = "leads.db"
UPLOAD_DIR = os.path.join(app.root_path, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXT = {"png", "jpg", "jpeg", "webp", "gif"}
MAX_CONTENT_LENGTH = 8 * 1024 * 1024       # 8 МБ на файл
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# ==================== БАЗА ====================
def init_db():
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS tiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                section TEXT NOT NULL,          -- home / services / projects
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                price TEXT DEFAULT '',
                image TEXT NOT NULL,            -- имя файла в /uploads
                created_at TEXT NOT NULL
            )
        """)

def get_tiles(section):
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        return con.execute(
            "SELECT * FROM tiles WHERE section=? ORDER BY id DESC", (section,)
        ).fetchall()

def add_tile(section, title, desc, price, image):
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT INTO tiles (section, title, description, price, image, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (section, title, desc, price, image,
             datetime.now().strftime("%d.%m.%Y %H:%M"))
        )

def delete_tile(tile_id):
    with sqlite3.connect(DB_PATH) as con:
        row = con.execute("SELECT image FROM tiles WHERE id=?", (tile_id,)).fetchone()
        con.execute("DELETE FROM tiles WHERE id=?", (tile_id,))
        if row:
            path = os.path.join(UPLOAD_DIR, row[0])
            if os.path.exists(path):
                os.remove(path)

def save_lead(name, email, message):
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT INTO leads (name, email, message, created_at) VALUES (?,?,?,?)",
            (name, email, message, datetime.now().strftime("%d.%m.%Y %H:%M"))
        )

def get_leads():
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        return con.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()

# ==================== ЗАГРУЗКА ФОТО ====================
def save_upload(file):
    """Сохраняет картинку в /uploads, сжимает большие и возвращает имя файла."""
    if not file or file.filename == "":
        return None
    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXT:
        return None

    filename = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(UPLOAD_DIR, filename)
    file.save(path)

    # сжимаем, чтобы страница летала
    try:
        img = Image.open(path)
        img.thumbnail((1200, 1200))
        if img.mode in ("RGBA", "P") and ext == "jpg":
            img = img.convert("RGB")
        img.save(path, optimize=True, quality=85)
    except Exception:
        pass

    return filename

# ==================== ПРОСТЫЕ МАРШРУТЫ ====================
@app.route("/")
def index():
    return render_template("index.html", tiles=get_tiles("home"), active="home")

@app.route("/services")
def services():
    return render_template("services.html", tiles=get_tiles("services"), active="services")

@app.route("/projects")
def projects():
    return render_template("projects.html", tiles=get_tiles("projects"), active="projects")

@app.route("/contacts", methods=["GET", "POST"])
def contacts():
    sent = False
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        message = request.form.get("message", "").strip()
        if name and email and message:
            save_lead(name, email, message)
            sent = True
    return render_template("contacts.html", tiles=[], active="contacts", sent=sent)

# ==================== ОТДАЧА ЗАГРУЖЕННЫХ ФАЙЛОВ ====================
@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)

# ==================== АДМИНКА ====================
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin"))
        error = "Неверный пароль"
    return render_template("admin_login.html", error=error)

@app.route("/admin")
def admin():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    return render_template("admin.html", leads=get_leads())

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_login"))

# ---------- Управление плитками ----------
@app.route("/admin/tiles", methods=["GET", "POST"])
def admin_tiles():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        section = request.form.get("section", "home")
        title = request.form.get("title", "").strip()
        desc = request.form.get("description", "").strip()
        price = request.form.get("price", "").strip()
        image = save_upload(request.files.get("image"))

        if section in ("home", "services", "projects") and title and desc and image:
            add_tile(section, title, desc, price, image)
            flash("Плитка добавлена ✨", "ok")
        else:
            flash("Заполни название, описание и выбери фото (png/jpg/webp/gif)", "err")

        return redirect(url_for("admin_tiles"))

    return render_template(
        "admin_tiles.html",
        home=get_tiles("home"),
        services=get_tiles("services"),
        projects=get_tiles("projects"),
    )

@app.route("/admin/tiles/delete/<int:tile_id>", methods=["POST"])
def admin_tiles_delete(tile_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    delete_tile(tile_id)
    flash("Плитка удалена 🗑️", "ok")
    return redirect(url_for("admin_tiles"))

# ==================== СТАРТ ====================
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)