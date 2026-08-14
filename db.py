import sqlite3, os
from datetime import datetime
DB_PATH=os.path.join(os.path.dirname(__file__),"bitacora.db")

def get_db():
    conn=sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory=sqlite3.Row
    return conn

def init_db():
    db=get_db()
    db.execute("""CREATE TABLE IF NOT EXISTS generacion_diaria(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ejecutivo TEXT NOT NULL,
        fecha TEXT NOT NULL,
        monto_generado REAL NOT NULL DEFAULT 0,
        fuente TEXT NOT NULL CHECK(fuente IN ('ocr','manual')),
        creado_en TEXT NOT NULL
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_gen_fecha_exec ON generacion_diaria(fecha,ejecutivo)")
    db.execute("CREATE TABLE IF NOT EXISTS ejecutivos(nombre TEXT PRIMARY KEY, telefono TEXT DEFAULT '', meta_mensual REAL)")
    db.execute("CREATE TABLE IF NOT EXISTS configuracion(clave TEXT PRIMARY KEY, valor TEXT NOT NULL)")
    db.commit()

def upsert_config_defaults():
    db=get_db()
    defaults={"streak_threshold":"3"}
    for k,v in defaults.items():
        db.execute("INSERT OR IGNORE INTO configuracion(clave,valor) VALUES(?,?)",(k,v))
    db.commit()
