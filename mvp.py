import streamlit as st
import streamlit.components.v1 as components
import sqlite3
import pandas as pd
from datetime import datetime, date
import urllib.parse

# ----------------------------------------------------
# Database (SQLite)
# ----------------------------------------------------
@st.cache_resource
def get_connection():
    conn = sqlite3.connect("supplify.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    return conn


def add_column_if_not_exists(conn, table, column, definition):
    c = conn.cursor()
    c.execute(f"PRAGMA table_info({table})")
    # row structure: (cid, name, type, notnull, dflt_value, pk)
    existing_columns = [row[1] for row in c.fetchall()]
    if column not in existing_columns:
        try:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")
            conn.commit()
        except Exception as e:
            print(f"Error adding column {column} to {table}: {e}")


def create_tables(conn):
    c = conn.cursor()

    # Users with address fields
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            address TEXT,
            city TEXT,
            postal_code TEXT,
            country TEXT,
            phone TEXT
        );
        """
    )

    # Ensure new columns exist on old DBs
    add_column_if_not_exists(conn, "users", "address", "TEXT")
    add_column_if_not_exists(conn, "users", "city", "TEXT")
    add_column_if_not_exists(conn, "users", "postal_code", "TEXT")
    add_column_if_not_exists(conn, "users", "country", "TEXT")
    add_column_if_not_exists(conn, "users", "phone", "TEXT")

    # Products with stock
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            category TEXT,
            price REAL NOT NULL,
            unit TEXT,
            stock REAL DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            FOREIGN KEY (supplier_id) REFERENCES users(id)
        );
        """
    )
    add_column_if_not_exists(conn, "products", "stock", "REAL DEFAULT 0")

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            discount_percent REAL NOT NULL,
            start_date TEXT,
            end_date TEXT,
            description TEXT,
            FOREIGN KEY (supplier_id) REFERENCES users(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        );
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id INTEGER NOT NULL,
            supplier_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            total_amount REAL NOT NULL,
            FOREIGN KEY (shop_id) REFERENCES users(id),
            FOREIGN KEY (supplier_id) REFERENCES users(id)
        );
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity REAL NOT NULL,
            unit_price REAL NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        );
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS favorites (
            shop_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            PRIMARY KEY (shop_id, product_id),
            FOREIGN KEY (shop_id) REFERENCES users(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        );
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id INTEGER NOT NULL,
            supplier_id INTEGER NOT NULL,
            order_id INTEGER,
            rating INTEGER NOT NULL,
            comment TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (shop_id) REFERENCES users(id),
            FOREIGN KEY (supplier_id) REFERENCES users(id),
            FOREIGN KEY (order_id) REFERENCES orders(id)
        );
        """
    )
    add_column_if_not_exists(conn, "ratings", "order_id", "INTEGER")

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            order_id INTEGER,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            FOREIGN KEY (sender_id) REFERENCES users(id),
            FOREIGN KEY (receiver_id) REFERENCES users(id),
            FOREIGN KEY (order_id) REFERENCES orders(id)
        );
        """
    )

    conn.commit()


# ----------------------------------------------------
# Helper functions
# ----------------------------------------------------
def get_user_by_email(conn, email):
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE email = ?", (email,))
    return c.fetchone()


def get_user_by_id(conn, user_id):
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    return c.fetchone()


def create_user(conn, name, email, password, role):
    c = conn.cursor()
    c.execute(
        "INSERT INTO users (name, email, password, role) VALUES (?,?,?,?)",
        (name, email, password, role),
    )
    conn.commit()
    return c.lastrowid


def get_suppliers(conn):
    c = conn.cursor()
    c.execute("SELECT id, name FROM users WHERE role='supplier' ORDER BY name")
    return c.fetchall()


def get_products_for_supplier(conn, supplier_id):
    c = conn.cursor()
    c.execute(
        """
        SELECT p.*, u.name as supplier_name
        FROM products p
        JOIN users u ON u.id = p.supplier_id
        WHERE p.supplier_id = ?
        ORDER BY p.name
        """,
        (supplier_id,),
    )
    return c.fetchall()


def get_all_products(conn, supplier_id=None, category=None, search=None):
    c = conn.cursor()
    query = """
        SELECT p.*, u.name as supplier_name
        FROM products p
        JOIN users u ON u.id = p.supplier_id
        WHERE p.is_active = 1
    """
    params = []

    if supplier_id:
        query += " AND p.supplier_id = ?"
        params.append(supplier_id)

    if category:
        query += " AND (p.category = ?)"
        params.append(category)

    if search:
        query += " AND (p.name LIKE ?)"
        params.append(f"%{search}%")

    query += " ORDER BY p.name"
    c.execute(query, params)
    return c.fetchall()


def get_active_offers_for_products(conn, product_ids):
    if not product_ids:
        return {}

    c = conn.cursor()
    today_str = date.today().isoformat()
    placeholders = ",".join("?" * len(product_ids))
    query = f"""
        SELECT * FROM offers
        WHERE product_id IN ({placeholders})
          AND (start_date IS NULL OR start_date <= ?)
          AND (end_date IS NULL OR end_date >= ?)
    """
    c.execute(query, (*product_ids, today_str, today_str))
    rows = c.fetchall()

    offers_by_product = {}
    for r in rows:
        offers_by_product[r["product_id"]] = r
    return offers_by_product


def get_shop_favorites(conn, shop_id):
    c = conn.cursor()
    c.execute(
        """
        SELECT f.product_id, p.name, p.category, p.price, p.unit, u.name as supplier_name
        FROM favorites f
        JOIN products p ON p.id = f.product_id
        JOIN users u ON u.id = p.supplier_id
        WHERE f.shop_id = ?
        ORDER BY p.name
        """,
        (shop_id,),
    )
    return c.fetchall()


def get_orders_for_supplier(conn, supplier_id):
    c = conn.cursor()
    c.execute(
        """
        SELECT o.*, s.name as shop_name
        FROM orders o
        JOIN users s ON s.id = o.shop_id
        WHERE o.supplier_id = ?
        ORDER BY o.created_at DESC
        """,
        (supplier_id,),
    )
    return c.fetchall()


def get_orders_for_shop(conn, shop_id):
    c = conn.cursor()
    c.execute(
        """
        SELECT o.*, u.name as supplier_name
        FROM orders o
        JOIN users u ON u.id = o.supplier_id
        WHERE o.shop_id = ?
        ORDER BY o.created_at DESC
        """,
        (shop_id,),
    )
    return c.fetchall()


def get_order_items(conn, order_id):
    c = conn.cursor()
    c.execute(
        """
        SELECT oi.*, p.name, p.unit
        FROM order_items oi
        JOIN products p ON p.id = oi.product_id
        WHERE oi.order_id = ?
        """,
        (order_id,),
    )
    return c.fetchall()


def send_message(conn, sender_id, receiver_id, content, order_id=None):
    c = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    c.execute(
        """
        INSERT INTO messages (sender_id, receiver_id, order_id, content, created_at)
        VALUES (?,?,?,?,?)
        """,
        (sender_id, receiver_id, order_id, content, now_str),
    )
    conn.commit()


def get_conversation(conn, user1_id, user2_id):
    c = conn.cursor()
    c.execute(
        """
        SELECT m.*, s.name as sender_name, r.name as receiver_name
        FROM messages m
        JOIN users s ON s.id = m.sender_id
        JOIN users r ON r.id = m.receiver_id
        WHERE (sender_id = ? AND receiver_id = ?)
           OR (sender_id = ? AND receiver_id = ?)
        ORDER BY created_at ASC
        """,
        (user1_id, user2_id, user2_id, user1_id),
    )
    return c.fetchall()


# ----------------------------------------------------
# Map helper
# ----------------------------------------------------
def show_google_map(full_address):
    if not full_address:
        st.info("Δεν έχει οριστεί διεύθυνση.")
        return
    query = urllib.parse.quote(full_address)
    url = f"https://www.google.com/maps?q={query}&output=embed"
    components.iframe(url, height=400)


# ----------------------------------------------------
# Authentication UI
# ----------------------------------------------------
def show_auth_screen(conn):
    st.title("Προμηθέας – B2B Πλατφόρμα Καφέ")

    tab_login, tab_register = st.tabs(["🔑 Σύνδεση", "🆕 Εγγραφή"])

    with tab_login:
        st.subheader("Σύνδεση")
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Κωδικός", type="password", key="login_password")
        if st.button("Σύνδεση"):
            user = get_user_by_email(conn, email)
            if not user or user["password"] != password:
                st.error("Λάθος email ή κωδικός.")
            else:
                st.session_state["user"] = {
                    "id": user["id"],
                    "name": user["name"],
                    "role": user["role"],
                }
                st.success("Επιτυχής σύνδεση!")
                st.rerun()

    with tab_register:
        st.subheader("Εγγραφή νέου χρήστη")

        role_label = st.radio(
            "Ρόλος",
            ["Προμηθευτής", "Μαγαζί (Καφέ)"],
        )
        role_map = {
            "Προμηθευτής": "supplier",
            "Μαγαζί (Καφέ)": "shop",
        }
        role_value = role_map[role_label]

        name = st.text_input("Επωνυμία / Όνομα", key="reg_name")
        email = st.text_input("Email", key="reg_email")
        password = st.text_input("Κωδικός", type="password", key="reg_password")
        password2 = st.text_input("Επαλήθευση Κωδικού", type="password", key="reg_password2")

        if st.button("Δημιουργία Λογαριασμού"):
            if not name or not email or not password:
                st.error("Συμπλήρωσε όλα τα πεδία.")
            elif password != password2:
                st.error("Οι κωδικοί δεν ταιριάζουν.")
            elif get_user_by_email(conn, email):
                st.error("Υπάρχει ήδη λογαριασμός με αυτό το email.")
            else:
                user_id = create_user(conn, name, email, password, role_value)
                st.session_state["user"] = {
                    "id": user_id,
                    "name": name,
                    "role": role_value,
                }
                st.success("Ο λογαριασμός δημιουργήθηκε!")
                st.rerun()


# ----------------------------------------------------
# Profile Page
# ----------------------------------------------------
def profile_page(conn, user):
    st.header("👤 Το Προφίλ μου")

    u = get_user_by_id(conn, user["id"])

    with st.form("profile_form"):
        address = st.text_input("Διεύθυνση", value=u["address"] or "")
        city = st.text_input("Πόλη", value=u["city"] or "")
        postal_code = st.text_input("Τ.Κ.", value=u["postal_code"] or "")
        country = st.text_input("Χώρα", value=u["country"] or "Ελλάδα")
        phone = st.text_input("Τηλέφωνο", value=u["phone"] or "")
        submitted = st.form_submit_button("Αποθήκευση προφίλ")

        if submitted:
            c = conn.cursor()
            c.execute(
                """
                UPDATE users
                SET address = ?, city = ?, postal_code = ?, country = ?, phone = ?
                WHERE id = ?
                """,
                (address, city, postal_code, country, phone, user["id"]),
            )
            conn.commit()
            st.success("Το προφίλ ενημερώθηκε.")
            st.rerun()

    full_address = ", ".join(
        part
        for part in [u["address"], u["city"], u["postal_code"], u["country"]]
        if part
    )
    st.subheader("📍 Τοποθεσία στο χάρτη")
    show_google_map(full_address)


# ----------------------------------------------------
# Supplier Pages
# ----------------------------------------------------
def supplier_dashboard(conn, user):
    st.header("📊 Dashboard Προμηθευτή")

    c = conn.cursor()

    c.execute("SELECT COUNT(*) as cnt FROM products WHERE supplier_id = ?", (user["id"],))
    products_count = c.fetchone()["cnt"]

    c.execute(
        "SELECT COUNT(*) as cnt, COALESCE(SUM(total_amount), 0) as total_revenue "
        "FROM orders WHERE supplier_id = ?",
        (user["id"],),
    )
    res = c.fetchone()
    orders_count = res["cnt"]
    total_revenue = res["total_revenue"]

    c.execute(
        "SELECT AVG(rating) as avg_rating, COUNT(*) as cnt FROM ratings WHERE supplier_id = ?",
        (user["id"],),
    )
    r = c.fetchone()
    avg_rating = r["avg_rating"] or 0
    ratings_count = r["cnt"] or 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Προϊόντα", products_count)
    col2.metric("Παραγγελίες", orders_count)
    col3.metric("Συνολικά Έσοδα (€)", round(total_revenue, 2))
    col4.metric("Μέση αξιολόγηση", f"{avg_rating:.1f} / 5" if ratings_count else "N/A")

    st.caption(f"Σύνολο αξιολογήσεων: {ratings_count}")

    st.subheader("Πρόσφατες Παραγγελίες")
    orders = get_orders_for_supplier(conn, user["id"])
    if not orders:
        st.info("Δεν υπάρχουν παραγγελίες ακόμη.")
    else:
        for o in orders[:5]:
            with st.expander(
                f"Παραγγελία #{o['id']} από {o['shop_name']} – {o['status']} – {o['created_at']}"
            ):
                st.write(f"Σύνολο: {o['total_amount']:.2f} €")
                items = get_order_items(conn, o["id"])
                df_items = pd.DataFrame(
                    [
                        {
                            "Προϊόν": it["name"],
                            "Ποσότητα": it["quantity"],
                            "Τιμή Μονάδας": it["unit_price"],
                            "Μονάδα": it["unit"],
                        }
                        for it in items
                    ]
                )
                st.table(df_items)


def supplier_products_page(conn, user):
    st.header("📦 Τα Προϊόντα μου")

    st.subheader("Προσθήκη / Ενημέρωση Προϊόντος")
    with st.form("product_form", clear_on_submit=True):
        name = st.text_input("Όνομα προϊόντος")
        category = st.text_input("Κατηγορία (π.χ. Καφές, Ποτήρια, Γάλα)")
        price = st.number_input("Τιμή (€)", min_value=0.0, step=0.1)
        unit = st.text_input("Μονάδα (π.χ. kg, τεμ.)", value="τεμ.")
        stock = st.number_input("Διαθέσιμο stock", min_value=0.0, step=1.0, value=0.0)
        submitted = st.form_submit_button("Αποθήκευση")

        if submitted:
            if not name or price <= 0:
                st.error("Συμπλήρωσε όνομα και θετική τιμή.")
            else:
                c = conn.cursor()
                c.execute(
                    "INSERT INTO products (supplier_id, name, category, price, unit, stock) VALUES (?,?,?,?,?,?)",
                    (user["id"], name, category, price, unit, stock),
                )
                conn.commit()
                st.success("Το προϊόν αποθηκεύτηκε.")

    st.subheader("Λίστα Προϊόντων")
    products = get_products_for_supplier(conn, user["id"])
    if not products:
        st.info("Δεν υπάρχουν προϊόντα ακόμη.")
        return

    for p in products:
        cols = st.columns([3, 2, 2, 2, 1, 1])
        cols[0].write(f"**{p['name']}**")
        cols[1].write(p["category"] or "-")
        cols[2].write(f"{p['price']:.2f} € / {p['unit']}")
        cols[3].write(f"Stock: {p['stock']:.0f}")
        is_active = "Ναι" if p["is_active"] else "Όχι"
        cols[4].write(f"Ενεργό: {is_active}")
        if cols[5].button("Απενεργοποίηση" if p["is_active"] else "Ενεργοποίηση", key=f"toggle_{p['id']}"):
            new_val = 0 if p["is_active"] else 1
            c = conn.cursor()
            c.execute(
                "UPDATE products SET is_active = ? WHERE id = ?", (new_val, p["id"])
            )
            conn.commit()
            st.rerun()


def supplier_offers_page(conn, user):
    st.header("💥 Προσφορές & Προωθητικές Ενέργειες")

    products = get_products_for_supplier(conn, user["id"])
    if not products:
        st.info("Πρέπει πρώτα να δημιουργήσεις προϊόντα.")
        return

    product_options = {f"{p['name']} ({p['price']:.2f} €)": p["id"] for p in products}

    with st.form("offer_form", clear_on_submit=True):
        product_label = st.selectbox("Προϊόν", list(product_options.keys()))
        discount = st.slider("Έκπτωση (%)", min_value=5, max_value=80, value=10, step=5)
        col1, col2 = st.columns(2)
        start = col1.date_input("Έναρξη προσφοράς", value=date.today())
        end = col2.date_input("Λήξη προσφοράς", value=date.today())
        description = st.text_area("Περιγραφή / Σχόλιο", value="Ειδική προσφορά")
        submitted = st.form_submit_button("Δημιουργία Προσφοράς")

        if submitted:
            if end < start:
                st.error("Η ημερομηνία λήξης δεν μπορεί να είναι πριν την έναρξη.")
            else:
                c = conn.cursor()
                c.execute(
                    """
                    INSERT INTO offers (supplier_id, product_id, discount_percent, start_date, end_date, description)
                    VALUES (?,?,?,?,?,?)
                    """,
                    (
                        user["id"],
                        product_options[product_label],
                        discount,
                        start.isoformat(),
                        end.isoformat(),
                        description,
                    ),
                )
                conn.commit()
                st.success("Η προσφορά δημιουργήθηκε.")

    st.subheader("Ενεργές / Προγραμματισμένες Προσφορές")
    c = conn.cursor()
    c.execute(
        """
        SELECT o.*, p.name as product_name
        FROM offers o
        JOIN products p ON p.id = o.product_id
        WHERE o.supplier_id = ?
        ORDER BY o.start_date DESC
        """,
        (user["id"],),
    )
    offers = c.fetchall()
    if not offers:
        st.info("Δεν υπάρχουν προσφορές ακόμη.")
    else:
        for off in offers:
            st.write(
                f"**{off['product_name']}** – {off['discount_percent']}% "
                f"({off['start_date']} έως {off['end_date']})"
            )
            if off["description"]:
                st.caption(off["description"])


def supplier_orders_page(conn, user):
    st.header("📥 Παραγγελίες")

    orders = get_orders_for_supplier(conn, user["id"])
    if not orders:
        st.info("Δεν υπάρχουν παραγγελίες.")
        return

    for o in orders:
        with st.expander(
            f"Παραγγελία #{o['id']} – {o['shop_name']} – {o['status']} – {o['created_at']}"
        ):
            st.write(f"Σύνολο: {o['total_amount']:.2f} €")

            items = get_order_items(conn, o["id"])
            df_items = pd.DataFrame(
                [
                    {
                        "Προϊόν": it["name"],
                        "Ποσότητα": it["quantity"],
                        "Τιμή/Μονάδα": it["unit_price"],
                        "Μονάδα": it["unit"],
                    }
                    for it in items
                ]
            )
            st.table(df_items)

            new_status = st.selectbox(
                "Κατάσταση",
                ["Νέα", "Σε εξέλιξη", "Ολοκληρωμένη", "Ακυρωμένη"],
                index=["Νέα", "Σε εξέλιξη", "Ολοκληρωμένη", "Ακυρωμένη"].index(
                    o["status"]
                ),
                key=f"status_{o['id']}",
            )
            if st.button("Ενημέρωση κατάστασης", key=f"update_{o['id']}"):
                c = conn.cursor()
                c.execute(
                    "UPDATE orders SET status = ? WHERE id = ?", (new_status, o["id"])
                )
                conn.commit()
                st.success("Η κατάσταση ενημερώθηκε.")
                st.rerun()


def supplier_analytics_page(conn, user):
    st.header("📈 Αναφορές & Στατιστικά Προμηθευτή")

    orders = get_orders_for_supplier(conn, user["id"])
    orders_list = [dict(o) for o in orders]

    if not orders_list:
        st.info("Δεν υπάρχουν δεδομένα ακόμη.")
        return

    df = pd.DataFrame(orders_list)
    df["created_at"] = pd.to_datetime(df["created_at"])
    df["month"] = df["created_at"].dt.to_period("M").astype(str)

    revenue_per_month = df.groupby("month")["total_amount"].sum().reset_index()

    st.subheader("Έσοδα ανά μήνα")
    st.bar_chart(revenue_per_month.set_index("month")["total_amount"])

    df_customers = df.groupby("shop_id").agg(
        total_amount=("total_amount", "sum"),
        orders=("id", "count"),
    )
    df_customers = df_customers.sort_values("total_amount", ascending=False)
    st.subheader("Κορυφαίοι Πελάτες (με βάση έσοδα)")
    st.dataframe(df_customers)


def supplier_messages_page(conn, user):
    st.header("💬 Επικοινωνία με πελάτες (καφέ)")

    c = conn.cursor()
    c.execute(
        """
        SELECT DISTINCT o.shop_id, u.name
        FROM orders o
        JOIN users u ON u.id = o.shop_id
        WHERE o.supplier_id = ?
        ORDER BY u.name
        """,
        (user["id"],),
    )
    shops = c.fetchall()
    if not shops:
        st.info("Δεν υπάρχουν ακόμη πελάτες με παραγγελίες.")
        return

    shop_map = {f"{s['name']} (ID {s['shop_id']})": s["shop_id"] for s in shops}
    choice = st.selectbox("Επίλεξε πελάτη", list(shop_map.keys()))
    shop_id = shop_map[choice]

    st.subheader("Συνομιλία")
    messages = get_conversation(conn, user["id"], shop_id)
    for m in messages:
        if m["sender_id"] == user["id"]:
            st.markdown(f"**Εσύ ({m['created_at']}):** {m['content']}")
        else:
            st.markdown(f"**{m['sender_name']} ({m['created_at']}):** {m['content']}")

    st.markdown("---")
    with st.form("send_message_supplier"):
        content = st.text_area("Νέο μήνυμα")
        submitted = st.form_submit_button("Αποστολή")
        if submitted and content.strip():
            send_message(conn, user["id"], shop_id, content.strip())
            st.success("Το μήνυμα στάλθηκε.")
            st.rerun()


# ----------------------------------------------------
# Shop Pages
# ----------------------------------------------------
def init_cart():
    if "cart" not in st.session_state:
        st.session_state["cart"] = {}
    if "cart_supplier" not in st.session_state:
        st.session_state["cart_supplier"] = None


def shop_dashboard(conn, user):
    st.header("🏪 Dashboard Μαγαζιού")

    favorites = get_shop_favorites(conn, user["id"])
    orders = get_orders_for_shop(conn, user["id"])

    col1, col2 = st.columns(2)
    col1.metric("Αγαπημένα προϊόντα", len(favorites))
    col2.metric("Σύνολο παραγγελιών", len(orders))

    st.subheader("Αγαπημένα προϊόντα")
    if not favorites:
        st.info("Δεν έχεις προσθέσει αγαπημένα ακόμη.")
    else:
        df_fav = pd.DataFrame(
            [
                {
                    "Προϊόν": f["name"],
                    "Προμηθευτής": f["supplier_name"],
                    "Κατηγορία": f["category"],
                    "Τιμή": f["price"],
                    "Μονάδα": f["unit"],
                }
                for f in favorites
            ]
        )
        st.table(df_fav)

    st.subheader("Πρόσφατες παραγγελίες")
    if not orders:
        st.info("Δεν υπάρχουν παραγγελίες.")
    else:
        for o in orders[:5]:
            st.write(
                f"#{o['id']} – {o['supplier_name']} – {o['status']} – {o['created_at']} – {o['total_amount']:.2f} €"
            )


def shop_browse_and_order_page(conn, user):
    st.header("🛒 Περιήγηση & Παραγγελία")

    init_cart()

    suppliers = get_suppliers(conn)
    supplier_names = ["Όλοι"] + [s["name"] for s in suppliers]
    supplier_choice = st.selectbox("Φίλτρο Προμηθευτή", supplier_names)
    supplier_id = None
    if supplier_choice != "Όλοι":
        supplier_id = next(s["id"] for s in suppliers if s["name"] == supplier_choice)

    category_filter = st.text_input("Φίλτρο κατηγορίας (προαιρετικό)")
    search = st.text_input("Αναζήτηση προϊόντος (όνομα)")

    products = get_all_products(
        conn,
        supplier_id=supplier_id,
        category=category_filter if category_filter else None,
        search=search if search else None,
    )

    if not products:
        st.info("Δεν βρέθηκαν προϊόντα με αυτά τα φίλτρα.")
        return

    product_ids = [p["id"] for p in products]
    offers = get_active_offers_for_products(conn, product_ids)

    st.subheader("Διαθέσιμα προϊόντα")
    data = []
    for p in products:
        discount = 0
        final_price = p["price"]
        if p["id"] in offers:
            discount = offers[p["id"]]["discount_percent"]
            final_price = p["price"] * (1 - discount / 100.0)
        data.append(
            {
                "ID": p["id"],
                "Προϊόν": p["name"],
                "Προμηθευτής": p["supplier_name"],
                "Κατηγορία": p["category"],
                "Τιμή (€)": p["price"],
                "Έκπτωση (%)": discount,
                "Τελική Τιμή (€)": round(final_price, 2),
                "Μονάδα": p["unit"],
                "Stock": p["stock"],
            }
        )
    st.dataframe(pd.DataFrame(data))

    st.markdown("---")
    st.subheader("Προσθήκη στο καλάθι")

    product_id_to_add = st.number_input(
        "ID προϊόντος", min_value=1, step=1, format="%d"
    )
    quantity = st.number_input(
        "Ποσότητα", min_value=0.0, step=0.5, format="%.1f", value=1.0
    )

    if st.button("Προσθήκη στο καλάθι"):
        selected = None
        for p in products:
            if p["id"] == product_id_to_add:
                selected = p
                break
        if selected is None:
            st.error("Το ID προϊόντος δεν αντιστοιχεί στη λίστα παραπάνω.")
        elif quantity <= 0:
            st.error("Η ποσότητα πρέπει να είναι θετική.")
        else:
            current_supplier = st.session_state["cart_supplier"]
            if current_supplier and current_supplier != selected["supplier_id"]:
                st.error(
                    "Στο τρέχον MVP επιτρέπεται ένας προμηθευτής ανά παραγγελία. "
                    "Ολοκλήρωσε την τρέχουσα παραγγελία ή άδεισε το καλάθι."
                )
            else:
                st.session_state["cart_supplier"] = selected["supplier_id"]
                st.session_state["cart"].setdefault(product_id_to_add, 0.0)
                st.session_state["cart"][product_id_to_add] += quantity
                st.success("Το προϊόν προστέθηκε στο καλάθι.")

    st.markdown("---")
    show_cart_and_checkout(conn, user)


def show_cart_and_checkout(conn, user):
    st.subheader("Καλάθι")

    cart = st.session_state.get("cart", {})
    if not cart:
        st.info("Το καλάθι είναι άδειο.")
        if st.button("Άδειασμα καλαθιού", disabled=True):
            pass
        return

    product_ids = list(cart.keys())
    c = conn.cursor()
    placeholders = ",".join("?" * len(product_ids))
    c.execute(
        f"""
        SELECT p.*, u.name as supplier_name
        FROM products p
        JOIN users u ON u.id = p.supplier_id
        WHERE p.id IN ({placeholders})
        """,
        product_ids,
    )
    rows = c.fetchall()
    products_by_id = {r["id"]: r for r in rows}

    offers = get_active_offers_for_products(conn, product_ids)

    cart_rows = []
    total = 0.0
    for pid, qty in cart.items():
        p = products_by_id[pid]
        base_price = p["price"]
        discount = 0
        final_price = base_price
        if pid in offers:
            discount = offers[pid]["discount_percent"]
            final_price = base_price * (1 - discount / 100.0)

        line_total = final_price * qty
        total += line_total
        cart_rows.append(
            {
                "ID": pid,
                "Προϊόν": p["name"],
                "Προμηθευτής": p["supplier_name"],
                "Ποσότητα": qty,
                "Τιμή Βάσης (€)": base_price,
                "Έκπτωση (%)": discount,
                "Τελική Τιμή (€)": round(final_price, 2),
                "Σύνολο Γραμμής (€)": round(line_total, 2),
            }
        )

    st.table(pd.DataFrame(cart_rows))
    st.write(f"**Σύνολο παραγγελίας:** {total:.2f} €")

    col1, col2, col3 = st.columns(3)
    if col1.button("Άδειασμα καλαθιού"):
        st.session_state["cart"] = {}
        st.session_state["cart_supplier"] = None
        st.success("Το καλάθι άδειασε.")
        st.rerun()

    col2.info("Στο MVP η παραγγελία γίνεται από έναν προμηθευτή. Ο αλγόριθμος κατανομής μπορεί να προστεθεί σε επόμενη φάση.")

    if col3.button("Ολοκλήρωση παραγγελίας"):
        supplier_id = st.session_state["cart_supplier"]
        if not supplier_id:
            st.error("Δεν έχει οριστεί προμηθευτής.")
            return

        # Έλεγχος stock
        for row in cart_rows:
            pid = row["ID"]
            qty = row["Ποσότητα"]
            c.execute("SELECT stock FROM products WHERE id = ?", (pid,))
            stock = c.fetchone()["stock"]
            if stock is not None and stock < qty:
                st.error(
                    f"Μη επαρκές stock για το προϊόν ID {pid}. Διαθέσιμο: {stock}, ζητάς: {qty}."
                )
                return

        # Δημιουργία παραγγελίας
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        c.execute(
            """
            INSERT INTO orders (shop_id, supplier_id, status, created_at, total_amount)
            VALUES (?,?,?,?,?)
            """,
            (user["id"], supplier_id, "Νέα", now_str, total),
        )
        order_id = c.lastrowid

        # Δημιουργία γραμμών παραγγελίας + μείωση stock
        for row in cart_rows:
            pid = row["ID"]
            qty = row["Ποσότητα"]
            final_unit_price = row["Τελική Τιμή (€)"]
            c.execute(
                """
                INSERT INTO order_items (order_id, product_id, quantity, unit_price)
                VALUES (?,?,?,?)
                """,
                (order_id, pid, qty, final_unit_price),
            )
            c.execute(
                "UPDATE products SET stock = stock - ? WHERE id = ?",
                (qty, pid),
            )

        conn.commit()
        st.session_state["cart"] = {}
        st.session_state["cart_supplier"] = None
        st.success(f"Η παραγγελία #{order_id} καταχωρήθηκε επιτυχώς!")


def shop_orders_page(conn, user):
    st.header("📦 Οι Παραγγελίες μου")

    orders = get_orders_for_shop(conn, user["id"])
    if not orders:
        st.info("Δεν υπάρχουν παραγγελίες.")
        return

    for o in orders:
        with st.expander(
            f"Παραγγελία #{o['id']} – {o['supplier_name']} – {o['status']} – {o['created_at']} – {o['total_amount']:.2f} €"
        ):
            items = get_order_items(conn, o["id"])
            df_items = pd.DataFrame(
                [
                    {
                        "Προϊόν": it["name"],
                        "Ποσότητα": it["quantity"],
                        "Τιμή/Μονάδα": it["unit_price"],
                        "Μονάδα": it["unit"],
                    }
                    for it in items
                ]
            )
            st.table(df_items)

            # Ratings
            c = conn.cursor()
            c.execute(
                "SELECT * FROM ratings WHERE shop_id = ? AND supplier_id = ? AND order_id = ?",
                (user["id"], o["supplier_id"], o["id"]),
            )
            existing = c.fetchone()

            st.subheader("Αξιολόγηση προμηθευτή")
            default_rating = existing["rating"] if existing else 5
            default_comment = existing["comment"] if existing else ""

            rating = st.slider(
                "Βαθμολογία (1–5)",
                min_value=1,
                max_value=5,
                value=default_rating,
                key=f"rating_{o['id']}",
            )
            comment = st.text_area(
                "Σχόλιο",
                value=default_comment,
                key=f"comment_{o['id']}",
            )

            if st.button("Αποθήκευση αξιολόγησης", key=f"save_rating_{o['id']}"):
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                if existing:
                    c.execute(
                        "UPDATE ratings SET rating = ?, comment = ?, created_at = ? WHERE id = ?",
                        (rating, comment, now_str, existing["id"]),
                    )
                else:
                    c.execute(
                        """
                        INSERT INTO ratings (shop_id, supplier_id, order_id, rating, comment, created_at)
                        VALUES (?,?,?,?,?,?)
                        """,
                        (user["id"], o["supplier_id"], o["id"], rating, comment, now_str),
                    )
                conn.commit()
                st.success("Η αξιολόγηση αποθηκεύτηκε.")
                st.rerun()


def shop_favorites_page(conn, user):
    st.header("⭐ Αγαπημένα")

    favorites = get_shop_favorites(conn, user["id"])
    if not favorites:
        st.info("Δεν υπάρχουν αγαπημένα.")
    else:
        df = pd.DataFrame(
            [
                {
                    "ID Προϊόντος": f["product_id"],
                    "Προϊόν": f["name"],
                    "Προμηθευτής": f["supplier_name"],
                    "Κατηγορία": f["category"],
                    "Τιμή": f["price"],
                    "Μονάδα": f["unit"],
                }
                for f in favorites
            ]
        )
        st.table(df)

    st.subheader("Προσθήκη / Αφαίρεση αγαπημένου")
    product_id = st.number_input(
        "ID προϊόντος", min_value=1, step=1, format="%d", key="fav_pid"
    )
    col1, col2 = st.columns(2)
    if col1.button("Προσθήκη στα αγαπημένα"):
        c = conn.cursor()
        try:
            c.execute(
                "INSERT INTO favorites (shop_id, product_id) VALUES (?,?)",
                (user["id"], product_id),
            )
            conn.commit()
            st.success("Προστέθηκε στα αγαπημένα.")
        except sqlite3.IntegrityError:
            st.warning("Είναι ήδη στα αγαπημένα ή το προϊόν δεν υπάρχει.")

    if col2.button("Αφαίρεση από αγαπημένα"):
        c = conn.cursor()
        c.execute(
            "DELETE FROM favorites WHERE shop_id = ? AND product_id = ?",
            (user["id"], product_id),
        )
        conn.commit()
        st.success("Αφαιρέθηκε από τα αγαπημένα (αν υπήρχε).")


def shop_analytics_page(conn, user):
    st.header("📊 Analytics Μαγαζιού")

    orders = get_orders_for_shop(conn, user["id"])
    orders_list = [dict(o) for o in orders]
    if not orders_list:
        st.info("Δεν υπάρχουν δεδομένα ακόμη.")
        return

    df = pd.DataFrame(orders_list)
    df["created_at"] = pd.to_datetime(df["created_at"])
    df["month"] = df["created_at"].dt.to_period("M").astype(str)

    st.subheader("Συνολικό κόστος ανά μήνα")
    spend_per_month = df.groupby("month")["total_amount"].sum().reset_index()
    st.bar_chart(spend_per_month.set_index("month")["total_amount"])

    st.subheader("Δαπάνη ανά προμηθευτή")
    spend_per_supplier = df.groupby("supplier_name")["total_amount"].sum().sort_values(ascending=False)
    st.dataframe(spend_per_supplier.rename("Σύνολο (€)"))

    c = conn.cursor()
    c.execute(
        """
        SELECT oi.quantity, oi.unit_price, p.name, p.category
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        JOIN products p ON p.id = oi.product_id
        WHERE o.shop_id = ?
        """,
        (user["id"],),
    )
    rows = c.fetchall()
    if rows:
        df_items = pd.DataFrame([dict(r) for r in rows])
        df_items["total"] = df_items["quantity"] * df_items["unit_price"]
        st.subheader("Top προϊόντα ανά κόστος")
        top_products = df_items.groupby("name")["total"].sum().sort_values(ascending=False).head(10)
        st.dataframe(top_products.rename("Σύνολο (€)"))


def shop_messages_page(conn, user):
    st.header("💬 Επικοινωνία με προμηθευτές")

    c = conn.cursor()
    c.execute(
        """
        SELECT DISTINCT o.supplier_id, u.name
        FROM orders o
        JOIN users u ON u.id = o.supplier_id
        WHERE o.shop_id = ?
        ORDER BY u.name
        """,
        (user["id"],),
    )
    suppliers = c.fetchall()
    if not suppliers:
        st.info("Δεν υπάρχουν ακόμη προμηθευτές με παραγγελίες για να επικοινωνήσεις.")
        return

    supplier_map = {f"{s['name']} (ID {s['supplier_id']})": s["supplier_id"] for s in suppliers}
    choice = st.selectbox("Επίλεξε προμηθευτή", list(supplier_map.keys()))
    supplier_id = supplier_map[choice]

    st.subheader("Συνομιλία")
    messages = get_conversation(conn, user["id"], supplier_id)
    for m in messages:
        if m["sender_id"] == user["id"]:
            st.markdown(f"**Εσύ ({m['created_at']}):** {m['content']}")
        else:
            st.markdown(f"**{m['sender_name']} ({m['created_at']}):** {m['content']}")

    st.markdown("---")
    with st.form("send_message_shop"):
        content = st.text_area("Νέο μήνυμα")
        submitted = st.form_submit_button("Αποστολή")
        if submitted and content.strip():
            send_message(conn, user["id"], supplier_id, content.strip())
            st.success("Το μήνυμα στάλθηκε.")
            st.rerun()


# ----------------------------------------------------
# Admin Pages
# ----------------------------------------------------
def admin_dashboard(conn):
    st.header("🛠 Admin Dashboard")

    c = conn.cursor()
    c.execute("SELECT role, COUNT(*) as cnt FROM users GROUP BY role")
    rows = c.fetchall()
    counts = {r["role"]: r["cnt"] for r in rows}

    c.execute("SELECT COUNT(*) as cnt, COALESCE(SUM(total_amount), 0) as total FROM orders")
    o = c.fetchone()

    col1, col2, col3 = st.columns(3)
    col1.metric("Σύνολο χρηστών", sum(counts.values()))
    col2.metric("Καφέδες", counts.get("shop", 0))
    col3.metric("Προμηθευτές", counts.get("supplier", 0))

    st.metric("Σύνολο παραγγελιών", o["cnt"])
    st.metric("Συνολικός τζίρος πλατφόρμας (€)", round(o["total"], 2))


def admin_users_map_page(conn):
    st.header("👥 Χρήστες & Χάρτης")

    c = conn.cursor()
    c.execute("SELECT * FROM users ORDER BY role, name")
    users = c.fetchall()
    if not users:
        st.info("Δεν υπάρχουν χρήστες.")
        return

    users_list = [dict(u) for u in users]
    df = pd.DataFrame(users_list)
    st.dataframe(df[["id", "name", "email", "role", "address", "city", "postal_code", "country", "phone"]])

    user_map = {f"{u['name']} (ID {u['id']} – {u['role']})": u["id"] for u in users_list}
    choice = st.selectbox("Επίλεξε χρήστη για τον χάρτη", list(user_map.keys()))
    selected_id = user_map[choice]
    u = next(u for u in users_list if u["id"] == selected_id)

    full_address = ", ".join(
        part
        for part in [u["address"], u["city"], u["postal_code"], u["country"]]
        if part
    )
    st.subheader(f"📍 Διεύθυνση: {full_address or '—'}")
    show_google_map(full_address)


def admin_orders_page(conn):
    st.header("📦 Όλες οι παραγγελίες")

    c = conn.cursor()
    c.execute(
        """
        SELECT o.*, s.name as shop_name, p.name as supplier_name
        FROM orders o
        JOIN users s ON s.id = o.shop_id
        JOIN users p ON p.id = o.supplier_id
        ORDER BY o.created_at DESC
        """
    )
    orders = c.fetchall()
    if not orders:
        st.info("Δεν υπάρχουν παραγγελίες.")
        return

    for o in orders:
        with st.expander(
            f"#{o['id']} – Καφέ: {o['shop_name']} | Προμηθευτής: {o['supplier_name']} | {o['status']} | {o['created_at']} – {o['total_amount']:.2f} €"
        ):
            items = get_order_items(conn, o["id"])
            df_items = pd.DataFrame(
                [
                    {
                        "Προϊόν": it["name"],
                        "Ποσότητα": it["quantity"],
                        "Τιμή/Μονάδα": it["unit_price"],
                        "Μονάδα": it["unit"],
                    }
                    for it in items
                ]
            )
            st.table(df_items)


def admin_messages_page(conn):
    st.header("💬 Όλα τα μηνύματα")

    c = conn.cursor()
    c.execute(
        """
        SELECT m.*, s.name as sender_name, r.name as receiver_name
        FROM messages m
        JOIN users s ON s.id = m.sender_id
        JOIN users r ON r.id = m.receiver_id
        ORDER BY m.created_at DESC
        LIMIT 200
        """
    )
    msgs = c.fetchall()
    if not msgs:
        st.info("Δεν υπάρχουν μηνύματα.")
        return

    for m in msgs:
        st.markdown(
            f"**{m['created_at']} – {m['sender_name']} ➜ {m['receiver_name']}:** {m['content']}"
        )


# ----------------------------------------------------
# Main App
# ----------------------------------------------------
def main():
    st.set_page_config(
        page_title="Προμηθέας – Διασύνδεση Προμηθευτών & Μαγαζιών Καφέ",
        layout="wide",
    )

    conn = get_connection()

    if "user" not in st.session_state:
        show_auth_screen(conn)
        return

    user = st.session_state["user"]

    # Sidebar
    with st.sidebar:
        st.markdown("### 👤 Συνδεδεμένος χρήστης")
        st.write(f"**{user['name']}**")
        role_label = {
            "supplier": "Προμηθευτής",
            "shop": "Μαγαζί (Καφέ)",
            "admin": "Διαχειριστής",
        }.get(user["role"], user["role"])
        st.write("Ρόλος:", role_label)

        if st.button("Αποσύνδεση"):
            st.session_state.clear()
            st.rerun()

        st.markdown("---")
        st.caption("MVP βασισμένο στο business plan της πλατφόρμας Προμηθέας.")

    # Navigation per role
    if user["role"] == "supplier":
        menu = st.sidebar.radio(
            "Μενού",
            [
                "Dashboard",
                "Προϊόντα",
                "Προσφορές",
                "Παραγγελίες",
                "Αναφορές",
                "Επικοινωνία",
                "Προφίλ",
            ],
        )

        if menu == "Dashboard":
            supplier_dashboard(conn, user)
        elif menu == "Προϊόντα":
            supplier_products_page(conn, user)
        elif menu == "Προσφορές":
            supplier_offers_page(conn, user)
        elif menu == "Παραγγελίες":
            supplier_orders_page(conn, user)
        elif menu == "Αναφορές":
            supplier_analytics_page(conn, user)
        elif menu == "Επικοινωνία":
            supplier_messages_page(conn, user)
        elif menu == "Προφίλ":
            profile_page(conn, user)

    elif user["role"] == "shop":
        menu = st.sidebar.radio(
            "Μενού",
            [
                "Dashboard",
                "Περιήγηση & Παραγγελία",
                "Οι Παραγγελίες μου",
                "Αγαπημένα",
                "Analytics",
                "Προφίλ",
                "Επικοινωνία",
            ],
        )

        if menu == "Dashboard":
            shop_dashboard(conn, user)
        elif menu == "Περιήγηση & Παραγγελία":
            shop_browse_and_order_page(conn, user)
        elif menu == "Οι Παραγγελίες μου":
            shop_orders_page(conn, user)
        elif menu == "Αγαπημένα":
            shop_favorites_page(conn, user)
        elif menu == "Analytics":
            shop_analytics_page(conn, user)
        elif menu == "Προφίλ":
            profile_page(conn, user)
        elif menu == "Επικοινωνία":
            shop_messages_page(conn, user)

    elif user["role"] == "admin":
        menu = st.sidebar.radio(
            "Μενού",
            [
                "Dashboard",
                "Χρήστες & Χάρτης",
                "Όλες οι παραγγελίες",
                "Μηνύματα",
            ],
        )

        if menu == "Dashboard":
            admin_dashboard(conn)
        elif menu == "Χρήστες & Χάρτης":
            admin_users_map_page(conn)
        elif menu == "Όλες οι παραγγελίες":
            admin_orders_page(conn)
        elif menu == "Μηνύματα":
            admin_messages_page(conn)


if __name__ == "__main__":
    main()
