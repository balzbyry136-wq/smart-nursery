from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from pathlib import Path
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os


# =========================
# إعداد التطبيق
# =========================

BASE = Path(__file__).resolve().parent
DB = BASE / "nursery.db"

app = Flask(__name__)

# استخدم SECRET_KEY من Render إذا كانت موجودة،
# وإلا استخدم مفتاحًا افتراضيًا للتجربة.
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "smart-nursery-secret-key-change-me"
)


# =========================
# قاعدة البيانات
# =========================

def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()

    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('admin','teacher','parent'))
    );

    CREATE TABLE IF NOT EXISTS classes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        teacher TEXT,
        capacity INTEGER DEFAULT 30
    );

    CREATE TABLE IF NOT EXISTS children(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        age INTEGER NOT NULL,
        parent_id INTEGER,
        class_id INTEGER,
        FOREIGN KEY(parent_id) REFERENCES users(id),
        FOREIGN KEY(class_id) REFERENCES classes(id)
    );

    CREATE TABLE IF NOT EXISTS attendance(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        child_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('present','absent')),
        check_in TEXT,
        check_out TEXT,
        FOREIGN KEY(child_id) REFERENCES children(id),
        UNIQUE(child_id,date)
    );

    CREATE TABLE IF NOT EXISTS payments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        child_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        date TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('paid','due')),
        FOREIGN KEY(child_id) REFERENCES children(id)
    );
    """)

    # إنشاء الحسابات والبيانات التجريبية أول مرة فقط
    user_count = conn.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    if user_count == 0:

        users = [
            (
                "مدير النظام",
                "admin@nursery.local",
                generate_password_hash("123456"),
                "admin"
            ),
            (
                "نورة أحمد",
                "teacher@nursery.local",
                generate_password_hash("123456"),
                "teacher"
            ),
            (
                "محمد علي",
                "parent@nursery.local",
                generate_password_hash("123456"),
                "parent"
            )
        ]

        conn.executemany(
            """
            INSERT INTO users(name,email,password,role)
            VALUES(?,?,?,?)
            """,
            users
        )

        conn.executemany(
            """
            INSERT INTO classes(name,teacher,capacity)
            VALUES(?,?,?)
            """,
            [
                ("الفراشات", "نورة أحمد", 40),
                ("النجوم", "ريم علي", 40),
                ("الألوان", "سلمى حسن", 40)
            ]
        )

        parent = conn.execute(
            "SELECT id FROM users WHERE role='parent' LIMIT 1"
        ).fetchone()

        first_class = conn.execute(
            "SELECT id FROM classes LIMIT 1"
        ).fetchone()

        if parent and first_class:
            conn.executemany(
                """
                INSERT INTO children(name,age,parent_id,class_id)
                VALUES(?,?,?,?)
                """,
                [
                    (
                        "أحمد محمد",
                        4,
                        parent["id"],
                        first_class["id"]
                    ),
                    (
                        "سارة خالد",
                        3,
                        parent["id"],
                        first_class["id"]
                    ),
                    (
                        "ليان أحمد",
                        5,
                        parent["id"],
                        first_class["id"]
                    )
                ]
            )

    conn.commit()
    conn.close()


# =========================
# الحماية والصلاحيات
# =========================

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):

        if "user_id" not in session:
            return redirect(url_for("login"))

        return fn(*args, **kwargs)

    return wrapper


def roles(*allowed):
    def deco(fn):

        @wraps(fn)
        def wrapper(*args, **kwargs):

            if session.get("role") not in allowed:
                flash(
                    "ليس لديك صلاحية للوصول إلى هذه الصفحة.",
                    "error"
                )

                return redirect(url_for("dashboard"))

            return fn(*args, **kwargs)

        return wrapper

    return deco


# =========================
# بيانات المستخدم للقوالب
# =========================

@app.context_processor
def context():
    return {
        "current_user": session.get("name"),
        "role": session.get("role")
    }


# =========================
# الصفحة الرئيسية
# =========================

@app.route("/")
def index():

    if "user_id" in session:
        return redirect(url_for("dashboard"))

    return redirect(url_for("login"))


# =========================
# تسجيل الدخول
# =========================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = db()

        user = conn.execute(
            "SELECT * FROM users WHERE email=?",
            (email,)
        ).fetchone()

        conn.close()

        if user and check_password_hash(
            user["password"],
            password
        ):

            session.update({
                "user_id": user["id"],
                "name": user["name"],
                "role": user["role"]
            })

            return redirect(url_for("dashboard"))

        flash(
            "البريد الإلكتروني أو كلمة المرور غير صحيحة.",
            "error"
        )

    return render_template("login.html")


# =========================
# تسجيل الخروج
# =========================

@app.get("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))


# =========================
# لوحة التحكم
# =========================

@app.get("/dashboard")
@login_required
def dashboard():

    conn = db()

    stats = {
        "children": conn.execute(
            "SELECT COUNT(*) c FROM children"
        ).fetchone()["c"],

        "teachers": conn.execute(
            "SELECT COUNT(*) c FROM users WHERE role='teacher'"
        ).fetchone()["c"],

        "classes": conn.execute(
            "SELECT COUNT(*) c FROM classes"
        ).fetchone()["c"],

        "paid": conn.execute(
            """
            SELECT COALESCE(SUM(amount),0) s
            FROM payments
            WHERE status='paid'
            """
        ).fetchone()["s"],
    }

    recent = conn.execute(
        """
        SELECT
            a.*,
            c.name child
        FROM attendance a
        JOIN children c
            ON c.id = a.child_id
        ORDER BY a.date DESC, a.id DESC
        LIMIT 6
        """
    ).fetchall()

    conn.close()

    return render_template(
        "dashboard.html",
        stats=stats,
        recent=recent
    )


# =========================
# الأطفال
# =========================

@app.get("/children")
@login_required
@roles("admin", "teacher")
def children():

    conn = db()

    rows = conn.execute(
        """
        SELECT
            c.*,
            cl.name class_name,
            u.name parent_name
        FROM children c
        LEFT JOIN classes cl
            ON cl.id = c.class_id
        LEFT JOIN users u
            ON u.id = c.parent_id
        ORDER BY c.id DESC
        """
    ).fetchall()

    classes = conn.execute(
        "SELECT * FROM classes"
    ).fetchall()

    parents = conn.execute(
        "SELECT * FROM users WHERE role='parent'"
    ).fetchall()

    conn.close()

    return render_template(
        "children.html",
        children=rows,
        classes=classes,
        parents=parents
    )


@app.post("/children/add")
@login_required
@roles("admin")
def add_child():

    conn = db()

    conn.execute(
        """
        INSERT INTO children(
            name,
            age,
            parent_id,
            class_id
        )
        VALUES(?,?,?,?)
        """,
        (
            request.form["name"],
            int(request.form["age"]),
            request.form.get("parent_id") or None,
            request.form.get("class_id") or None
        )
    )

    conn.commit()
    conn.close()

    flash(
        "تمت إضافة الطفل بنجاح.",
        "success"
    )

    return redirect(url_for("children"))


@app.post("/children/delete/<int:child_id>")
@login_required
@roles("admin")
def delete_child(child_id):

    conn = db()

    conn.execute(
        "DELETE FROM attendance WHERE child_id=?",
        (child_id,)
    )

    conn.execute(
        "DELETE FROM payments WHERE child_id=?",
        (child_id,)
    )

    conn.execute(
        "DELETE FROM children WHERE id=?",
        (child_id,)
    )

    conn.commit()
    conn.close()

    flash(
        "تم حذف الطفل.",
        "success"
    )

    return redirect(url_for("children"))


# =========================
# الحضور
# =========================

@app.route("/attendance", methods=["GET", "POST"])
@login_required
@roles("admin", "teacher")
def attendance():

    from datetime import date

    day = request.args.get(
        "date"
    ) or date.today().isoformat()

    conn = db()

    children = conn.execute(
        """
        SELECT
            c.*,
            a.status,
            a.check_in,
            a.check_out
        FROM children c
        LEFT JOIN attendance a
            ON a.child_id = c.id
            AND a.date = ?
        ORDER BY c.name
        """,
        (day,)
    ).fetchall()

    if request.method == "POST":

        for child in children:

            status = request.form.get(
                f"status_{child['id']}",
                "absent"
            )

            check_in = request.form.get(
                f"in_{child['id']}"
            ) or None

            check_out = request.form.get(
                f"out_{child['id']}"
            ) or None

            conn.execute(
                """
                INSERT INTO attendance(
                    child_id,
                    date,
                    status,
                    check_in,
                    check_out
                )
                VALUES(?,?,?,?,?)

                ON CONFLICT(child_id,date)
                DO UPDATE SET
                    status=excluded.status,
                    check_in=excluded.check_in,
                    check_out=excluded.check_out
                """,
                (
                    child["id"],
                    day,
                    status,
                    check_in,
                    check_out
                )
            )

        conn.commit()
        conn.close()

        flash(
            "تم حفظ سجل الحضور.",
            "success"
        )

        return redirect(
            url_for(
                "attendance",
                date=day
            )
        )

    conn.close()

    return render_template(
        "attendance.html",
        children=children,
        day=day
    )


# =========================
# المدفوعات
# =========================

@app.route("/payments", methods=["GET", "POST"])
@login_required
@roles("admin")
def payments():

    conn = db()

    if request.method == "POST":

        conn.execute(
            """
            INSERT INTO payments(
                child_id,
                amount,
                date,
                status
            )
            VALUES(?,?,date('now'),?)
            """,
            (
                request.form["child_id"],
                float(request.form["amount"]),
                request.form["status"]
            )
        )

        conn.commit()

        flash(
            "تم تسجيل العملية المالية.",
            "success"
        )

    rows = conn.execute(
        """
        SELECT
            p.*,
            c.name child
        FROM payments p
        JOIN children c
            ON c.id = p.child_id
        ORDER BY p.id DESC
        """
    ).fetchall()

    children = conn.execute(
        """
        SELECT id,name
        FROM children
        ORDER BY name
        """
    ).fetchall()

    totals = conn.execute(
        """
        SELECT
            COALESCE(
                SUM(
                    CASE
                        WHEN status='paid'
                        THEN amount
                        ELSE 0
                    END
                ),0
            ) paid,

            COALESCE(
                SUM(
                    CASE
                        WHEN status='due'
                        THEN amount
                        ELSE 0
                    END
                ),0
            ) due

        FROM payments
        """
    ).fetchone()

    conn.close()

    return render_template(
        "payments.html",
        payments=rows,
        children=children,
        totals=totals
    )


# =========================
# بوابة ولي الأمر
# =========================

@app.get("/parent")
@login_required
@roles("parent")
def parent_portal():

    conn = db()

    children = conn.execute(
        """
        SELECT
            c.*,
            cl.name class_name
        FROM children c
        LEFT JOIN classes cl
            ON cl.id = c.class_id
        WHERE c.parent_id=?
        """,
        (session["user_id"],)
    ).fetchall()

    rows = conn.execute(
        """
        SELECT
            a.*,
            c.name child
        FROM attendance a
        JOIN children c
            ON c.id = a.child_id
        WHERE c.parent_id=?
        ORDER BY a.date DESC
        LIMIT 12
        """,
        (session["user_id"],)
    ).fetchall()

    payment_rows = conn.execute(
        """
        SELECT
            p.*,
            c.name child
        FROM payments p
        JOIN children c
            ON c.id = p.child_id
        WHERE c.parent_id=?
        ORDER BY p.id DESC
        LIMIT 12
        """,
        (session["user_id"],)
    ).fetchall()

    conn.close()

    return render_template(
        "parent.html",
        children=children,
        attendance=rows,
        payments=payment_rows
    )


# =========================
# التقارير
# =========================

@app.get("/reports")
@login_required
@roles("admin")
def reports():

    conn = db()

    by_class = conn.execute(
        """
        SELECT
            cl.name,
            COUNT(c.id) total
        FROM classes cl
        LEFT JOIN children c
            ON c.class_id = cl.id
        GROUP BY cl.id
        """
    ).fetchall()

    attendance_data = conn.execute(
        """
        SELECT
            status,
            COUNT(*) total
        FROM attendance
        GROUP BY status
        """
    ).fetchall()

    conn.close()

    return render_template(
        "reports.html",
        by_class=by_class,
        attendance=attendance_data
    )


# =========================
# الإعدادات
# =========================

@app.get("/settings")
@login_required
@roles("admin")
def settings():

    return render_template(
        "settings.html"
    )


# =========================
# تهيئة قاعدة البيانات
# =========================

# مهم جدًا مع Gunicorn وRender:
# يتم تنفيذ هذا عند تحميل app.py.
init_db()


# =========================
# التشغيل المحلي
# =========================

if __name__ == "__main__":

    app.run(
        debug=True,
        host="127.0.0.1",
        port=5000
    )
