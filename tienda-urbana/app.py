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
    # Solo para desarrollo local.
    # En Railway configura SECRET_KEY en Variables.
    app.secret_key = secrets.token_hex(32)


# =========================================================
# CONFIGURACIÓN MYSQL: RAILWAY Y LOCAL
# =========================================================

DB_HOST = os.environ.get(
    "MYSQLHOST", os.environ.get("DB_HOST", "localhost")
)

DB_PORT = int(os.environ.get(
    "MYSQLPORT", os.environ.get("DB_PORT", "3306")
))

DB_USER = os.environ.get(
    "MYSQLUSER", os.environ.get("DB_USER", "root")
)

DB_PASSWORD = os.environ.get(
    "MYSQLPASSWORD", os.environ.get("DB_PASSWORD", "")
)

DB_NAME = os.environ.get(
    "MYSQLDATABASE", os.environ.get("DB_NAME", "logyn_db")
)


# Cuenta de administrador principal (se crea/actualiza al arrancar).
# En Railway define ADMIN_EMAIL y ADMIN_PASSWORD en Variables.
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@tienda.com").strip().lower()
ADMIN_PASSWORD_ENV = os.environ.get("ADMIN_PASSWORD")
ADMIN_PASSWORD = ADMIN_PASSWORD_ENV or "admin123"


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
    ("Hoodie Oversize Concreto", "Ropa", 129000, 20,
     "Buzo con capucha, algodón pesado 420 g."),
    ("Camiseta Boxy Paradero", "Ropa", 69000, 35,
     "Camiseta de corte ancho, estampado serigráfico."),
    ("Cargo Pants Esquina", "Ropa", 149000, 15,
     "Pantalón cargo con seis bolsillos."),
    ("Chaqueta Bomber Ruta 7", "Ropa", 219000, 10,
     "Bomber ligera con forro interior."),
    ("Tenis Block Runner", "Zapatos", 289000, 18,
     "Suela gruesa, parte superior en malla y cuero sintético."),
    ("Botas Asfalto Hi", "Zapatos", 329000, 8,
     "Bota alta con suela de goma antideslizante."),
    ("Zapatilla Skate Muro", "Zapatos", 199000, 25,
     "Lona reforzada, puntera doble costura."),
    ("Gorra Trucker Barrio", "Accesorios", 59000, 40,
     "Gorra con malla trasera y ajuste snapback."),
]


def now():
    return datetime.now().isoformat(timespec="seconds")


def init_db():
    """
    Crea las tablas dentro de la base de datos configurada.
    Railway debe tener creada su base de datos MySQL.
    """
    conn = create_connection()

    try:
        with conn.cursor() as cursor:
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    cursor.execute(statement)

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
            elif ADMIN_PASSWORD_ENV:
                # Si defines ADMIN_PASSWORD en Railway, se restablece
                # la contraseña de esa cuenta en cada arranque.
                cursor.execute(
                    "UPDATE users SET password_hash=%s, role=%s WHERE id=%s",
                    (
                        generate_password_hash(ADMIN_PASSWORD),
                        "admin",
                        existing["id"],
                    ),
                )
            elif existing["role"] != "admin":
                cursor.execute(
                    "UPDATE users SET role=%s WHERE id=%s",
                    ("admin", existing["id"]),
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
                return err(
                    "Solo el administrador puede hacer esto.", 403
                )

            return func(*args, **kwargs)

        return wrapper

    return decorator


def get_json():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return None

    return data


# =========================================================
# PÁGINA PRINCIPAL
# =========================================================

@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# =========================================================
# REGISTRO
# =========================================================

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

    if (
        not email
        or "@" not in email
        or len(email) > 255
    ):
        return err("Introduce un correo electrónico válido.")

    if not isinstance(password, str) or len(password) < 6:
        return err(
            "La contraseña debe tener al menos 6 caracteres."
        )

    conn = db()

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users
                (name, email, password_hash, role, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    name,
                    email,
                    generate_password_hash(password),
                    "customer",
                    now(),
                ),
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


# =========================================================
# INICIO DE SESIÓN
# =========================================================

@app.post("/api/login")
def login():
    data = get_json()

    if data is None:
        return err("La solicitud debe contener datos JSON.")

    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    result = rows(
        "SELECT * FROM users WHERE email = %s",
        (email,),
    )

    user = result[0] if result else None

    if (
        not user
        or not isinstance(password, str)
        or not check_password_hash(
            user["password_hash"], password
        )
    ):
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


# =========================================================
# PRODUCTOS
# =========================================================

@app.get("/api/products")
def products():
    return jsonify(
        rows("SELECT * FROM products ORDER BY id DESC")
    )


def product_fields(data):
    try:
        if not isinstance(data, dict):
            return None

        name = data["name"].strip()
        category = data["category"].strip()
        price = int(data["price"])
        stock = int(data["stock"])
        image = data.get("image", "").strip()
        description = data.get("description", "").strip()

        if (
            not name
            or not category
            or price < 0
            or stock < 0
            or len(name) > 255
            or len(category) > 100
        ):
            return None

        return (
            name, category, price, stock, image, description
        )

    except (KeyError, ValueError, TypeError, AttributeError):
        return None


@app.post("/api/products")
@login_required(admin=True)
def product_create():
    data = get_json()
    fields = product_fields(data)

    if not fields:
        return err("Completa correctamente los datos del producto.")

    conn = db()

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO products
                (name, category, price, stock, image, description)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                fields,
            )

            product_id = cursor.lastrowid

        conn.commit()

        return jsonify(ok=True, id=product_id), 201

    except pymysql.MySQLError:
        conn.rollback()
        app.logger.exception("Error creando producto")
        return err("No se pudo crear el producto.", 500)


@app.put("/api/products/<int:pid>")
@login_required(admin=True)
def product_update(pid):
    fields = product_fields(get_json())

    if not fields:
        return err("Completa correctamente los datos del producto.")

    conn = db()

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE products
                SET name=%s, category=%s, price=%s, stock=%s,
                    image=%s, description=%s
                WHERE id=%s
                """,
                (*fields, pid),
            )

            if cursor.rowcount == 0:
                cursor.execute(
                    "SELECT id FROM products WHERE id=%s", (pid,)
                )

                if not cursor.fetchone():
                    conn.rollback()
                    return err("Producto no encontrado.", 404)

        conn.commit()
        return jsonify(ok=True)

    except pymysql.MySQLError:
        conn.rollback()
        app.logger.exception("Error actualizando producto")
        return err("No se pudo actualizar el producto.", 500)


@app.delete("/api/products/<int:pid>")
@login_required(admin=True)
def product_delete(pid):
    conn = db()

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM products WHERE id=%s", (pid,)
            )

            if cursor.rowcount == 0:
                conn.rollback()
                return err("Producto no encontrado.", 404)

        conn.commit()
        return jsonify(ok=True)

    except pymysql.MySQLError:
        conn.rollback()
        app.logger.exception("Error eliminando producto")
        return err("No se pudo eliminar el producto.", 500)


# =========================================================
# PAGO SIMULADO
# =========================================================

def fake_gateway(card, exp, cvc, amount):
    digits = "".join(ch for ch in card if ch.isdigit())

    if (
        len(digits) != 16
        or len(cvc) not in (3, 4)
        or not exp
        or "/" not in exp
    ):
        return False, "Datos de tarjeta inválidos."

    if digits.endswith("0000"):
        return False, "Tarjeta rechazada por el banco (simulado)."

    return True, "PAY-" + secrets.token_hex(4).upper()


@app.post("/api/checkout")
@login_required()
def checkout():
    data = get_json()

    if data is None:
        return err("La solicitud debe contener datos JSON.")

    items = data.get("items", [])

    if not isinstance(items, list) or not items:
        return err("Tu carrito está vacío o no es válido.")

    if len(items) > 100:
        return err("Demasiados productos en el carrito.")

    address = data.get("address", "")
    card = data.get("card", "")
    exp = data.get("exp", "")
    cvc = data.get("cvc", "")

    if not all(
        isinstance(value, str)
        for value in (address, card, exp, cvc)
    ):
        return err("Los datos de compra no son válidos.")

    conn = db()

    try:
        lines = []
        total = 0

        with conn.cursor() as cursor:
            for item in items:
                if not isinstance(item, dict):
                    conn.rollback()
                    return err("Hay un producto inválido en el carrito.")

                try:
                    product_id = int(item.get("id"))
                    qty = int(item.get("qty"))
                except (ValueError, TypeError):
                    conn.rollback()
                    return err("Hay un producto inválido en el carrito.")

                if product_id < 1 or qty < 1:
                    conn.rollback()
                    return err("La cantidad de un producto no es válida.")

                # Bloquea la fila para comprobar y descontar stock
                # sin permitir que otra compra use las mismas unidades.
                cursor.execute(
                    "SELECT * FROM products WHERE id=%s FOR UPDATE",
                    (product_id,),
                )

                product = cursor.fetchone()

                if not product:
                    conn.rollback()
                    return err("Hay un producto que ya no existe.")

                if product["stock"] < qty:
                    conn.rollback()
                    return err(
                        f"No hay stock suficiente de {product['name']}."
                    )

                lines.append((product, qty))
                total += product["price"] * qty

            if total <= 0:
                conn.rollback()
                return err("El total de la compra no es válido.")

            ok, reference = fake_gateway(
                card, exp, cvc, total
            )

            if not ok:
                conn.rollback()
                return err(reference, 402)

            cursor.execute(
                """
                INSERT INTO orders
                (user_id, total, status, payment_ref, address, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    session["uid"],
                    total,
                    "pagado",
                    reference,
                    address,
                    now(),
                ),
            )

            order_id = cursor.lastrowid

            for product, qty in lines:
                cursor.execute(
                    """
                    INSERT INTO order_items
                    (order_id, product_id, name, price, qty)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        order_id,
                        product["id"],
                        product["name"],
                        product["price"],
                        qty,
                    ),
                )

                cursor.execute(
                    """
                    UPDATE products
                    SET stock = stock - %s
                    WHERE id = %s
                    """,
                    (qty, product["id"]),
                )

        conn.commit()

        return jsonify(
            order_id=order_id,
            payment_ref=reference,
            total=total,
        ), 201

    except pymysql.MySQLError:
        conn.rollback()
        app.logger.exception("Error procesando la compra")
        return err("No se pudo procesar la compra.", 500)


# =========================================================
# PEDIDOS DEL CLIENTE Y ADMINISTRACIÓN
# =========================================================

def with_items(orders):
    for order in orders:
        order["items"] = rows(
            """
            SELECT name, price, qty
            FROM order_items
            WHERE order_id=%s
            """,
            (order["id"],),
        )

    return orders


@app.get("/api/orders")
@login_required()
def my_orders():
    orders = rows(
        """
        SELECT * FROM orders
        WHERE user_id=%s
        ORDER BY id DESC
        """,
        (session["uid"],),
    )

    return jsonify(with_items(orders))


@app.get("/api/admin/orders")
@login_required(admin=True)
def all_orders():
    orders = rows(
        """
        SELECT o.*, u.name AS customer, u.email
        FROM orders o
        JOIN users u ON u.id = o.user_id
        ORDER BY o.id DESC
        """
    )

    return jsonify(with_items(orders))


@app.get("/api/admin/users")
@login_required(admin=True)
def all_users():
    return jsonify(
        rows(
            """
            SELECT id, name, email, role, created_at
            FROM users ORDER BY id DESC
            """
        )
    )


@app.post("/api/admin/users")
@login_required(admin=True)
def admin_create_user():
    """Crea un administrador nuevo o promueve a un usuario existente."""
    data = get_json()

    if data is None:
        return err("La solicitud debe contener datos JSON.")

    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = data.get("password", "")

    if not email or "@" not in email or len(email) > 255:
        return err("Introduce un correo electrónico válido.")

    conn = db()

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, role FROM users WHERE email = %s", (email,)
            )
            existing = cursor.fetchone()

            if existing:
                if existing["role"] == "admin":
                    conn.rollback()
                    return err("Ese correo ya es administrador.", 409)

                cursor.execute(
                    "UPDATE users SET role=%s WHERE id=%s",
                    ("admin", existing["id"]),
                )
                conn.commit()
                return jsonify(ok=True, promoted=True)

            if not name or len(name) > 255:
                conn.rollback()
                return err("Introduce un nombre válido.")

            if not isinstance(password, str) or len(password) < 6:
                conn.rollback()
                return err("La contraseña debe tener al menos 6 caracteres.")

            cursor.execute(
                """
                INSERT INTO users
                (name, email, password_hash, role, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    name,
                    email,
                    generate_password_hash(password),
                    "admin",
                    now(),
                ),
            )

        conn.commit()
        return jsonify(ok=True, promoted=False), 201

    except pymysql.err.IntegrityError:
        conn.rollback()
        return err("Ese correo ya tiene una cuenta.", 409)

    except pymysql.MySQLError:
        conn.rollback()
        app.logger.exception("Error creando administrador")
        return err("No se pudo crear el administrador.", 500)


@app.put("/api/admin/users/<int:uid>/role")
@login_required(admin=True)
def admin_set_role(uid):
    """Convierte a un usuario en admin o lo regresa a cliente."""
    data = get_json() or {}
    role = data.get("role")

    if role not in ("admin", "customer"):
        return err("Rol no válido.")

    if uid == session["uid"] and role != "admin":
        return err("No puedes quitarte a ti mismo el rol de administrador.")

    conn = db()

    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM users WHERE id = %s", (uid,))

            if not cursor.fetchone():
                conn.rollback()
                return err("Usuario no encontrado.", 404)

            cursor.execute(
                "UPDATE users SET role=%s WHERE id=%s", (role, uid)
            )

        conn.commit()
        return jsonify(ok=True)

    except pymysql.MySQLError:
        conn.rollback()
        app.logger.exception("Error cambiando el rol")
        return err("No se pudo cambiar el rol.", 500)


# =========================================================
# ERRORES DE CONEXIÓN
# =========================================================

@app.errorhandler(pymysql.MySQLError)
def handle_mysql_error(error):
    app.logger.exception("Error de base de datos: %s", error)

    return jsonify(
        error="Error de conexión o consulta a la base de datos."
    ), 500


# =========================================================
# ARRANQUE
# =========================================================

def init_db_safe(retries=5, delay=3):
    """
    Crea tablas, admin y productos al importar la app (gunicorn en Railway).
    Reintenta por si MySQL aún no está listo al arrancar.
    """
    for attempt in range(1, retries + 1):
        try:
            init_db()
            app.logger.info("Base de datos inicializada correctamente.")
            return
        except Exception:
            app.logger.exception(
                "No se pudo inicializar la base de datos "
                "(intento %s de %s)", attempt, retries
            )
            if attempt < retries:
                time.sleep(delay)


# Se ejecuta tanto con `python app.py` como con `gunicorn app:app`.
init_db_safe()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )