"""Tienda urbana: Flask + MySQL (Conectado a logyn_db)."""
import os, secrets, functools
from datetime import datetime
from flask import Flask, g, request, session, jsonify, send_from_directory
import pymysql
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__, static_folder="static", static_url_path="")
app.secret_key = os.environ.get("SECRET_KEY", "cambia-esta-clave-en-produccion")

# Configuración de conexión a MySQL apuntando a logyn_db
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", 3306))
DB_USER = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_NAME = os.environ.get("DB_NAME", "login_db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(255) NOT NULL,
  email VARCHAR(255) UNIQUE NOT NULL, password_hash VARCHAR(255) NOT NULL,
  role VARCHAR(50) NOT NULL DEFAULT 'customer', created_at VARCHAR(50) NOT NULL);
CREATE TABLE IF NOT EXISTS products(
  id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(255) NOT NULL, category VARCHAR(100) NOT NULL,
  price INT NOT NULL, stock INT NOT NULL DEFAULT 0,
  image TEXT DEFAULT '', description TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS orders(
  id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, total INT NOT NULL,
  status VARCHAR(50) NOT NULL, payment_ref VARCHAR(255), address TEXT, created_at VARCHAR(50) NOT NULL);
CREATE TABLE IF NOT EXISTS order_items(
  id INT AUTO_INCREMENT PRIMARY KEY, order_id INT NOT NULL,
  product_id INT NOT NULL, name VARCHAR(255) NOT NULL, price INT NOT NULL, qty INT NOT NULL);
"""

SEED = [
  ("Hoodie Oversize Concreto","Ropa",129000,20,"Buzo con capucha, algodón pesado 420 g."),
  ("Camiseta Boxy Paradero","Ropa",69000,35,"Camiseta de corte ancho, estampado serigráfico."),
  ("Cargo Pants Esquina","Ropa",149000,15,"Pantalón cargo con seis bolsillos."),
  ("Chaqueta Bomber Ruta 7","Ropa",219000,10,"Bomber ligera con forro interior."),
  ("Tenis Block Runner","Zapatos",289000,18,"Suela gruesa, parte superior en malla y cuero sintético."),
  ("Botas Asfalto Hi","Zapatos",329000,8,"Bota alta con suela de goma antideslizante."),
  ("Zapatilla Skate Muro","Zapatos",199000,25,"Lona reforzada, puntera doble costura."),
  ("Gorra Trucker Barrio","Accesorios",59000,40,"Gorra con malla trasera y ajuste snapback."),
]

def db():
    if "db" not in g:
        g.db = pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            cursorclass=pymysql.cursors.DictCursor
        )
    return g.db

@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d: d.close()

def init_db():
    conn = pymysql.connect(host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD)
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}`")
        conn.select_db(DB_NAME)
        
        with conn.cursor() as cursor:
            for statement in SCHEMA.strip().split(";"):
                if statement.strip():
                    cursor.execute(statement)
        
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM users WHERE role='admin'")
            if not cursor.fetchone():
                cursor.execute("INSERT INTO users(name,email,password_hash,role,created_at) VALUES(%s,%s,%s,%s,%s)",
                               ("Administrador", "admin@tienda.com", generate_password_hash("admin123"), "admin", now()))
            
            cursor.execute("SELECT 1 FROM products")
            if not cursor.fetchone():
                cursor.executemany("INSERT INTO products(name,category,price,stock,description) VALUES(%s,%s,%s,%s,%s)", SEED)
        
        conn.commit()
    finally:
        conn.close()

def now(): return datetime.now().isoformat(timespec="seconds")
def rows(q, a=()): 
    cur = db().cursor()
    cur.execute(q, a)
    res = cur.fetchall()
    cur.close()
    return res

def err(msg, code=400): return jsonify(error=msg), code

def current_user():
    uid = session.get("uid")
    if not uid: return None
    cur = db().cursor()
    cur.execute("SELECT id,name,email,role FROM users WHERE id=%s", (uid,))
    r = cur.fetchone()
    cur.close()
    return r if r else None

def login_required(admin=False):
    def deco(f):
        @functools.wraps(f)
        def wrap(*a, **k):
            u = current_user()
            if not u: return err("Inicia sesión para continuar.", 401)
            if admin and u["role"] != "admin": return err("Solo el administrador puede hacer esto.", 403)
            return f(*a, **k)
        return wrap
    return deco

@app.get("/")
def index(): return send_from_directory("static", "index.html")

# ---------- Cuentas ----------
@app.post("/api/register")
def register():
    d = request.get_json(force=True)
    name, email, pw = d.get("name","").strip(), d.get("email","").strip().lower(), d.get("password","")
    if not name or "@" not in email or len(pw) < 6:
        return err("Revisa tu nombre, correo y una contraseña de mínimo 6 caracteres.")
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO users(name,email,password_hash,created_at) VALUES(%s,%s,%s,%s)",
                        (name, email, generate_password_hash(pw), now()))
            uid = cur.lastrowid
        conn.commit()
    except pymysql.err.IntegrityError:
        return err("Ese correo ya tiene una cuenta.")
    session["uid"] = uid
    return jsonify(user=current_user())

@app.post("/api/login")
def login():
    d = request.get_json(force=True)
    cur = db().cursor()
    cur.execute("SELECT * FROM users WHERE email=%s", (d.get("email","").strip().lower(),))
    r = cur.fetchone()
    cur.close()
    if not r or not check_password_hash(r["password_hash"], d.get("password","")):
        return err("Correo o contraseña incorrectos.", 401)
    session["uid"] = r["id"]
    return jsonify(user=current_user())

@app.post("/api/logout")
def logout(): session.clear(); return jsonify(ok=True)

@app.get("/api/me")
def me(): return jsonify(user=current_user())

# ---------- Productos ----------
@app.get("/api/products")
def products(): return jsonify(rows("SELECT * FROM products ORDER BY id DESC"))

def product_fields(d):
    try:
        return (d["name"].strip(), d["category"].strip(), int(d["price"]), int(d["stock"]),
                d.get("image","").strip(), d.get("description","").strip())
    except (KeyError, ValueError, AttributeError):
        return None

@app.post("/api/products")
@login_required(admin=True)
def product_create():
    f = product_fields(request.get_json(force=True))
    if not f or not f[0]: return err("Completa nombre, categoría, precio y stock.")
    conn = db()
    with conn.cursor() as cur:
        cur.execute("INSERT INTO products(name,category,price,stock,image,description) VALUES(%s,%s,%s,%s,%s,%s)", f)
    conn.commit()
    return jsonify(ok=True)

@app.put("/api/products/<int:pid>")
@login_required(admin=True)
def product_update(pid):
    f = product_fields(request.get_json(force=True))
    if not f: return err("Completa nombre, categoría, precio y stock.")
    conn = db()
    with conn.cursor() as cur:
        cur.execute("UPDATE products SET name=%s,category=%s,price=%s,stock=%s,image=%s,description=%s WHERE id=%s", (*f, pid))
    conn.commit()
    return jsonify(ok=True)

@app.delete("/api/products/<int:pid>")
@login_required(admin=True)
def product_delete(pid):
    conn = db()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM products WHERE id=%s", (pid,))
    conn.commit()
    return jsonify(ok=True)

# ---------- Pasarela de pago ficticia ----------
def fake_gateway(card, exp, cvc, amount):
    digits = "".join(ch for ch in card if ch.isdigit())
    if len(digits) != 16 or len(cvc) not in (3, 4) or "/" not in exp:
        return False, "Datos de tarjeta inválidos."
    if digits.endswith("0000"): return False, "Tarjeta rechazada por el banco (simulado)."
    return True, "PAY-" + secrets.token_hex(4).upper()

@app.post("/api/checkout")
@login_required()
def checkout():
    d = request.get_json(force=True); items = d.get("items", [])
    if not items: return err("Tu carrito está vacío.")
    conn = db()
    lines, total = [], 0
    with conn.cursor() as cur:
        for it in items:
            cur.execute("SELECT * FROM products WHERE id=%s", (it.get("id"),))
            p = cur.fetchone()
            qty = int(it.get("qty", 0))
            if not p or qty < 1: return err("Hay un producto inválido en el carrito.")
            if p["stock"] < qty: return err(f"No hay stock suficiente de {p['name']}.")
            lines.append((p, qty)); total += p["price"] * qty
            
    ok, ref_or_msg = fake_gateway(d.get("card",""), d.get("exp",""), d.get("cvc",""), total)
    if not ok: return err(ref_or_msg, 402)
    
    with conn.cursor() as cur:
        cur.execute("INSERT INTO orders(user_id,total,status,payment_ref,address,created_at) VALUES(%s,%s,%s,%s,%s,%s)",
                    (session["uid"], total, "pagado", ref_or_msg, d.get("address",""), now()))
        order_id = cur.lastrowid
        for p, qty in lines:
            cur.execute("INSERT INTO order_items(order_id,product_id,name,price,qty) VALUES(%s,%s,%s,%s,%s)",
                        (order_id, p["id"], p["name"], p["price"], qty))
            cur.execute("UPDATE products SET stock=stock-%s WHERE id=%s", (qty, p["id"]))
    conn.commit()
    return jsonify(order_id=order_id, payment_ref=ref_or_msg, total=total)

def with_items(orders):
    for o in orders:
        o["items"] = rows("SELECT name,price,qty FROM order_items WHERE order_id=%s", (o["id"],))
    return orders

@app.get("/api/orders")
@login_required()
def my_orders():
    return jsonify(with_items(rows("SELECT * FROM orders WHERE user_id=%s ORDER BY id DESC", (session["uid"],))))

@app.get("/api/admin/orders")
@login_required(admin=True)
def all_orders():
    return jsonify(with_items(rows("""SELECT o.*, u.name AS customer, u.email FROM orders o
                                    JOIN users u ON u.id=o.user_id ORDER BY o.id DESC""")))

@app.get("/api/admin/users")
@login_required(admin=True)
def all_users():
    return jsonify(rows("SELECT id,name,email,role,created_at FROM users ORDER BY id DESC"))

# ---------- Ejecución de la aplicación ----------
if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)