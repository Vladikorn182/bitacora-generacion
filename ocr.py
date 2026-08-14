import io, re
from PIL import Image, ImageOps, ImageEnhance

def extract_ranking(image_bytes):
    """
    Punto de extracción OCR reemplazable.
    Devuelve: (filas, texto_bruto, advertencias).
    """
    warnings=[]
    try:
        import pytesseract
    except ImportError:
        return [], "", ["pytesseract no está instalado. Puedes instalar requirements.txt o introducir las filas manualmente."], None

    try:
        img=Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img=ImageOps.grayscale(img)
        img=ImageEnhance.Contrast(img).enhance(2.0)
        # OCR de bloque de texto; psm 6 suele funcionar bien para capturas tabulares.
        text=pytesseract.image_to_string(img, config="--psm 6", lang="spa+eng")
    except Exception as e:
        return [], "", [f"No se pudo ejecutar OCR: {e}"], None

    rows=[]
    suggested_day=None
    # Intenta detectar la columna del día desde el encabezado (ej. "Dia 13").
    for h in text.splitlines():
        mh=re.search(r"\bD[IÍ]A\s*(\d{1,2})\b", h, re.I)
        if mh:
            suggested_day=int(mh.group(1)); break

    for line in text.splitlines():
        line=line.strip()
        if not line or re.search(r"(TOTAL|EJECUTIVO|MTD|D[IÍ]A|RANKING)",line,re.I):
            continue
        nums=re.findall(r"(?<!\d)(\d+(?:[.,]\d+)?)(?!\d)",line)
        if not nums: continue
        # En un ranking como "1 Adriana 31 4 3...": rank, MTD, Dia actual...
        # Si hay varias cifras, se toma la primera cifra diaria después de rank+MTD.
        if re.match(r"^\s*\d+\s", line) and len(nums)>=3:
            amount=nums[2]
        elif len(nums)>=2:
            amount=nums[-1]
        else:
            amount=nums[0]
        amount=amount.replace(',','.')
        try: amount=int(float(amount))
        except: continue
        name=re.sub(r"^\s*\d+\s*[.\-)]?\s*","",line)
        # Elimina las columnas numéricas al final, conservando el nombre.
        name=re.sub(r"\s+(?:\d+(?:[.,]\d+)?\s*)+$","",name).strip(" -|:")
        if len(name)>=2:
            rows.append({"ejecutivo":name.title(),"monto_generado":amount,"fuente":"ocr"})
    if not rows:
        warnings.append("No se detectaron filas con confianza. Agrega manualmente las filas en la tabla de revisión.")
    if suggested_day and not (1 <= suggested_day <= 31):
        suggested_day=None
    return rows,text,warnings,suggested_day

