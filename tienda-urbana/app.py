"""Tienda urbana: Flask + SQLite. La base de datos se crea sola al arrancar."""
import os, sqlite3, secrets, functools
from datetime import datetime
from flask import Flask, g, request, session, jsonify, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("DB_PATH", os.path.join(BASE, "tienda.db"))
app = Flask(__name__, static_folder="static", static_url_path="")
app.secret_key = os.environ.get("SECRET_KEY", "cambia-esta-clave-en-produccion")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
  email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'customer', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS products(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, category TEXT NOT NULL,
  price INTEGER NOT NULL, stock INTEGER NOT NULL DEFAULT 0,
  image TEXT DEFAULT '', description TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, total INTEGER NOT NULL,
  status TEXT NOT NULL, payment_ref TEXT, address TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS order_items(
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL,
  product_id INTEGER NOT NULL, name TEXT NOT NULL, price INTEGER NOT NULL, qty INTEGER NOT NULL);
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
        g.db = sqlite3.connect(DB); g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d: d.close()

def init_db():
    c = sqlite3.connect(DB); c.executescript(SCHEMA)
    if not c.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
        c.execute("INSERT INTO users(name,email,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                  ("Administrador","admin@tienda.com",generate_password_hash("admin123"),"admin",now()))
    if not c.execute("SELECT 1 FROM products").fetchone():
        c.executemany("INSERT INTO products(name,category,price,stock,description) VALUES(?,?,?,?,?)", SEED)
    c.commit(); c.close()

def now(): return datetime.now().isoformat(timespec="seconds")
def rows(q, a=()): return [dict(r) for r in db().execute(q, a).fetchall()]
def err(msg, code=400): return jsonify(error=msg), code

def current_user():
    uid = session.get("uid")
    if not uid: return None
    r = db().execute("SELECT id,name,email,role FROM users WHERE id=?", (uid,)).fetchone()
    return dict(r) if r else None

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
    try:
        cur = db().execute("INSERT INTO users(name,email,password_hash,created_at) VALUES(?,?,?,?)",
                           (name,email,generate_password_hash(pw),now()))
        db().commit()
    except sqlite3.IntegrityError:
        return err("Ese correo ya tiene una cuenta.")
    session["uid"] = cur.lastrowid
    return jsonify(user=current_user())

@app.post("/api/login")
def login():
    d = request.get_json(force=True)
    r = db().execute("SELECT * FROM users WHERE email=?", (d.get("email","").strip().lower(),)).fetchone()
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
    db().execute("INSERT INTO products(name,category,price,stock,image,description) VALUES(?,?,?,?,?,?)", f)
    db().commit(); return jsonify(ok=True)

@app.put("/api/products/<int:pid>")
@login_required(admin=True)
def product_update(pid):
    f = product_fields(request.get_json(force=True))
    if not f: return err("Completa nombre, categoría, precio y stock.")
    db().execute("UPDATE products SET name=?,category=?,price=?,stock=?,image=?,description=? WHERE id=?", (*f, pid))
    db().commit(); return jsonify(ok=True)

@app.delete("/api/products/<int:pid>")
@login_required(admin=True)
def product_delete(pid):
    db().execute("DELETE FROM products WHERE id=?", (pid,)); db().commit(); return jsonify(ok=True)

# ---------- Pasarela de pago ficticia ----------
def fake_gateway(card, exp, cvc, amount):
    """Simula una pasarela. Nunca se guarda el número de tarjeta."""
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
    lines, total = [], 0
    for it in items:
        p = db().execute("SELECT * FROM products WHERE id=?", (it.get("id"),)).fetchone()
        qty = int(it.get("qty", 0))
        if not p or qty < 1: return err("Hay un producto inválido en el carrito.")
        if p["stock"] < qty: return err(f"No hay stock suficiente de {p['name']}.")
        lines.append((p, qty)); total += p["price"] * qty
    ok, ref_or_msg = fake_gateway(d.get("card",""), d.get("exp",""), d.get("cvc",""), total)
    if not ok: return err(ref_or_msg, 402)
    cur = db().execute("INSERT INTO orders(user_id,total,status,payment_ref,address,created_at) VALUES(?,?,?,?,?,?)",
                       (session["uid"], total, "pagado", ref_or_msg, d.get("address",""), now()))
    for p, qty in lines:
        db().execute("INSERT INTO order_items(order_id,product_id,name,price,qty) VALUES(?,?,?,?,?)",
                     (cur.lastrowid, p["id"], p["name"], p["price"], qty))
        db().execute("UPDATE products SET stock=stock-? WHERE id=?", (qty, p["id"]))
    db().commit()
    return jsonify(order_id=cur.lastrowid, payment_ref=ref_or_msg, total=total)

def with_items(orders):
    for o in orders:
        o["items"] = rows("SELECT name,price,qty FROM order_items WHERE order_id=?", (o["id"],))
    return orders

@app.get("/api/orders")
@login_required()
def my_orders():
    return jsonify(with_items(rows("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC", (session["uid"],))))

@app.get("/api/admin/orders")
@login_required(admin=True)
def all_orders():
    return jsonify(with_items(rows("""SELECT o.*, u.name AS customer, u.email FROM orders o
                                      JOIN users u ON u.id=o.user_id ORDER BY o.id DESC""")))

@app.get("/api/admin/users")
@login_required(admin=True)
def all_users():
    return jsonify(rows("SELECT id,name,email,role,created_at FROM users ORDER BY id DESC"))


    init_db()
    
    if __name__ == "__main__":
        app.run(debug=True, port=5000)