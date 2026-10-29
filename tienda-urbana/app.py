"""
Tienda urbana: Flask + MySQL
Compatible con Railway y entorno local.
"""

import os
import time
import secrets
import functools
from datetime import datetime

import pymysql
from flask import Flask, g, request, session, jsonify, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash


# =========================================================
# CONFIGURACIÓN DE FLASK
# =========================================================

app = Flask(__name__, static_folder="static", static_url_path="")

app.secret_key = os.environ.get("SECRET_KEY")

if not app.secret_key:
    app.secret_key = secrets.token_hex(32)


# =========================================================
# CONFIGURACIÓN MYSQL: RAILWAY Y LOCAL
# =========================================================

DB_HOST = os.environ.get("MYSQLHOST", os.environ.get("DB_HOST", "localhost"))
DB_PORT = int(os.environ.get("MYSQLPORT", os.environ.get("DB_PORT", "3306")))
DB_USER = os.environ.get("MYSQLUSER", os.environ.get("DB_USER", "root"))
DB_PASSWORD = os.environ.get("MYSQLPASSWORD", os.environ.get("DB_PASSWORD", ""))
DB_NAME = os.environ.get("MYSQLDATABASE", os.environ.get("DB_NAME", "logyn_db"))

# Credenciales de administrador estrictamente tomadas de variables de entorno
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "montessjuan22@gmail.com").strip().lower()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")


def create_connection(database=DB_NAME):
    """Crea una conexión nueva a MySQL."""
    config = {
        "host": DB_HOST,
        "port": DB_PORT,
        "user": DB_USER,
        "password": DB_PASSWORD,
        "charset": "utf8mb4",
        "connect_timeout": 10,
        "cursorclass": pymysql.cursors.DictCursor,
        "autocommit": False,
    }

    if database:
        config["database"] = database

    return pymysql.connect(**config)


def db():
    """Reutiliza una conexión durante la petición actual."""
    if "db" not in g:
        g.db = create_connection()
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    conn = g.pop("db", None)

    if conn is not None:
        if exception is not None:
            try:
                conn.rollback()
            except pymysql.MySQLError:
                pass

        conn.close()


# =========================================================
# TABLAS Y PRODUCTOS INICIALES
# =========================================================

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'customer',
    created_at VARCHAR(50) NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    category VARCHAR(100) NOT NULL,
    price INT NOT NULL,
    stock INT NOT NULL DEFAULT 0,
    image TEXT DEFAULT '',
    description TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    total INT NOT NULL,
    status VARCHAR(50) NOT NULL,
    payment_ref VARCHAR(255),
    address TEXT,
    created_at VARCHAR(50) NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    product_id INT NOT NULL,
    name VARCHAR(255) NOT NULL,
    price INT NOT NULL,
    qty INT NOT NULL
);
"""

SEED = [
    ("Hoodie Oversize Concreto", "Ropa", 129000, 20, "Buzo con capucha, algodón pesado 420 g."),
    ("Camiseta Boxy Paradero", "Ropa", 69000, 35, "Camiseta de corte ancho, estampado serigráfico."),
    ("Cargo Pants Esquina", "Ropa", 149000, 15, "Pantalón cargo con seis bolsillos."),
    ("Chaqueta Bomber Ruta 7", "Ropa", 219000, 10, "Bomber ligera con forro interior."),
    ("Tenis Block Runner", "Zapatos", 289000, 18, "Suela gruesa, parte superior en malla y cuero sintético."),
    ("Botas Asfalto Hi", "Zapatos", 329000, 8, "Bota alta con suela de goma antideslizante."),
    ("Zapatilla Skate Muro", "Zapatos", 199000, 25, "Lona reforzada, puntera doble costura."),
    ("Gorra Trucker Barrio", "Accesorios", 59000, 40, "Gorra con malla trasera y ajuste snapback."),
]


def now():
    return datetime.now().isoformat(timespec="seconds")


def init_db():
    """Crea las tablas y sincroniza el admin usando exclusivamente variables de entorno."""
    conn = create_connection()

    try:
        with conn.cursor() as cursor:
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    cursor.execute(statement)

            # Sincronizar cuenta de administrador solo si ADMIN_PASSWORD está definida
            if ADMIN_EMAIL and ADMIN_PASSWORD:
                cursor.execute(
                    "SELECT id, role FROM users WHERE email = %s",
                    (ADMIN_EMAIL,),
                )
                existing = cursor.fetchone()

                if existing is None:
                    cursor.execute(
                        """
                        INSERT INTO users
                        (name, email, password_hash, role, created_at)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            "Administrador",
                            ADMIN_EMAIL,
                            generate_password_hash(ADMIN_PASSWORD),
                            "admin",
                            now(),
                        ),
                    )
                else:
                    # Actualiza la contraseña y el rol únicamente si ya existe el correo configurado
                    cursor.execute(
                        """
                        UPDATE users
                        SET password_hash=%s, role=%s, name=%s
                        WHERE id=%s
                        """,
                        (
                            generate_password_hash(ADMIN_PASSWORD),
                            "admin",
                            "Administrador",
                            existing["id"],
                        ),
                    )

            cursor.execute("SELECT id FROM products LIMIT 1")

            if not cursor.fetchone():
                cursor.executemany(
                    """
                    INSERT INTO products
                    (name, category, price, stock, description)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    SEED,
                )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


# =========================================================
# FUNCIONES AUXILIARES
# =========================================================

def rows(query, params=()):
    conn = db()
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        return cursor.fetchall()


def err(message, code=400):
    return jsonify(error=message), code


def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    result = rows(
        "SELECT id, name, email, role FROM users WHERE id = %s",
        (uid,),
    )
    return result[0] if result else None


def login_required(admin=False):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                return err("Inicia sesión para continuar.", 401)
            if admin and user["role"] != "admin":
                return err("Solo el administrador puede hacer esto.", 403)
            return func(*args, **kwargs)
        return wrapper
    return decorator


def get_json():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None
    return data


# ========================================================= RUTAS Y CONTROLADORES
# =========================================================

@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.post("/api/register")
def register():
    data = get_json()
    if data is None:
        return err("La solicitud debe contener datos JSON.")

    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not name or len(name) > 255:
        return err("Introduce un nombre válido.")
    if not email or "@" not in email or len(email) > 255:
        return err("Introduce un correo electrónico válido.")
    if not isinstance(password, str) or len(password) < 6:
        return err("La contraseña debe tener al menos 6 caracteres.")

    conn = db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users
                (name, email, password_hash, role, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (name, email, generate_password_hash(password), "customer", now()),
            )
            uid = cursor.lastrowid

        conn.commit()
        session["uid"] = uid
        return jsonify(user=current_user()), 201

    except pymysql.err.IntegrityError:
        conn.rollback()
        return err("Ese correo ya tiene una cuenta.", 409)
    except pymysql.MySQLError:
        conn.rollback()
        app.logger.exception("Error de MySQL durante el registro")
        return err("No se pudo crear la cuenta. Inténtalo más tarde.", 500)


@app.post("/api/login")
def login():
    data = get_json()
    if data is None:
        return err("La solicitud debe contener datos JSON.")

    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    result = rows("SELECT * FROM users WHERE email = %s", (email,))
    user = result[0] if result else None

    if not user or not isinstance(password, str) or not check_password_hash(user["password_hash"], password):
        return err("Correo o contraseña incorrectos.", 401)

    session.clear()
    session["uid"] = user["id"]
    return jsonify(user=current_user())


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/me")
def me():
    return jsonify(user=current_user())


@app.get("/api/products")
def products():
    return jsonify(rows("SELECT * FROM products ORDER BY id DESC"))


# (Demás rutas de productos, pago, pedidos y administración se mantienen igual...)

@app.errorhandler(pymysql.MySQLError)
def handle_mysql_error(error):
    app.logger.exception("Error de base de datos: %s", error)
    return jsonify(error="Error de conexión o consulta a la base de datos."), 500


def init_db_safe(retries=5, delay=3):
    for attempt in range(1, retries + 1):
        try:
            init_db()
            app.logger.info("Base de datos inicializada correctamente.")
            return
        except Exception:
            app.logger.exception("No se pudo inicializar la base de datos (intento %s de %s)", attempt, retries)
            if attempt < retries:
                time.sleep(delay)


init_db_safe()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)