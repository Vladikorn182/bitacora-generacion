# Bitácora Diaria de Generación

Aplicación independiente Streamlit + SQLite.

## Ejecución

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```

### OCR
`pytesseract` es opcional a nivel de aplicación, pero para OCR real debes tener instalado también el ejecutable Tesseract en el sistema. Si no está disponible, la app no bloquea el flujo: puedes cargar/corregir las filas manualmente.

## Archivos
- `app.py`: interfaz Streamlit.
- `db.py`: SQLite independiente.
- `ocr.py`: punto aislado y reemplazable del motor OCR.
- `analytics.py`: cálculos derivados por queries.
- `requirements.txt`: dependencias.

La base `bitacora.db` se crea automáticamente junto a la aplicación.
