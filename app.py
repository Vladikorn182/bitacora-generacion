import streamlit as st
import pandas as pd
from datetime import date, datetime
from urllib.parse import quote
from db import init_db, get_db, upsert_config_defaults
from ocr import extract_ranking
from analytics import (
    get_executives_for_date, calculate_executive_metrics,
    calculate_day_awards, get_month_history, get_available_months
)

st.set_page_config(page_title="Bitácora Diaria de Generación", page_icon="📊", layout="wide")
init_db()
upsert_config_defaults()

st.title("📊 Bitácora Diaria de Generación")
st.caption("Carga una foto del ranking, corrige el OCR y guarda el resultado. El histórico se calcula desde SQLite.")

def wa_url(phone, message):
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if not digits:
        return None
    return f"https://wa.me/{digits}?text={quote(message)}"

def status_message(m):
    if m["zero_streak"] >= 3:
        return f"🚨 Alerta crítica: {m['zero_streak']} días consecutivos sin generar."
    if m["zero_streak"] == 2:
        return "🚨 Alerta: 2 días consecutivos sin generar."
    if m["generated_today"] and m["generate_streak"] >= m["streak_threshold"]:
        return "🟢 Excelente / Buen ritmo"
    if m["generated_today"]:
        return "🟡 Generando"
    return "🔴 Hoy no generó"

def alert_text(m):
    name=m["ejecutivo"]; z=m["zero_streak"]
    if z >= 3:
        return (f"Hola {name}, llevas {z} días consecutivos sin registrar generación. "
                f"Necesitamos una recuperación inmediata. Por favor indícame hoy qué está "
                f"bloqueando tu producción y coordinemos una reunión o llamada para definir "
                f"acciones concretas. Necesito tu compromiso de recuperación desde hoy.")
    return (f"Hola {name}, revisamos tu generación de los últimos días y vemos que llevas "
            f"{z} días sin registrar ventas. Necesitamos recuperar generación. Por favor "
            f"indícame qué dificultades estás teniendo y qué acciones realizarás hoy.")

def recognition_text(m, award_phrase):
    return (f"¡Excelente trabajo, {m['ejecutivo']}! 👏 Hoy generaste {m['today']} y alcanzaste "
            f"{m['mtd']} MTD. {award_phrase}. Mantén este ritmo.")

with st.sidebar:
    st.header("Configuración")
    threshold=st.number_input("Umbral de racha para 🟢", min_value=2, max_value=10, value=3)
    st.caption("Se usa para distinguir una racha sólida de una racha corta.")
    st.divider()
    st.info("Los teléfonos y metas se pueden editar en la sección Configuración de la aplicación.")

tab1, tab2, tab3, tab4 = st.tabs(["📷 Cargar ranking", "📅 Bitácora / hoy", "📈 Histórico", "⚙️ Configuración"])

with tab1:
    st.subheader("Cargar ranking")
    uploaded=st.file_uploader("Sube UNA foto/captura del ranking diario", type=["png","jpg","jpeg","webp"])
    selected_date=st.date_input("Fecha del ranking", value=st.session_state.get("suggested_date", date.today()), key="ranking_date")
    if uploaded:
        image_bytes=uploaded.getvalue()
        st.image(image_bytes, caption="Imagen cargada", width=900)
        if st.button("🔎 Ejecutar OCR", type="primary"):
            rows, raw_text, warnings, suggested_day=extract_ranking(image_bytes)
            if suggested_day:
                try:
                    st.session_state["suggested_date"]=date(date.today().year,date.today().month,suggested_day)
                except ValueError:
                    pass
            st.session_state["ocr_rows"]=rows
            st.session_state["ocr_raw"]=raw_text
            st.session_state["ocr_warnings"]=warnings
            st.session_state["ocr_filename"]=uploaded.name
            st.success(f"OCR terminado: {len(rows)} filas candidatas.")
            if suggested_day:
                st.info(f"El encabezado de la imagen sugiere Día {suggested_day}. Revisa la fecha y corrígela si la foto fue subida tarde.")
                if st.button(f"Usar fecha detectada: {suggested_day:02d}/{date.today().month:02d}/{date.today().year}"):
                    st.session_state["suggested_date"]=date(date.today().year,date.today().month,suggested_day)
                    st.session_state["ranking_date"]=st.session_state["suggested_date"]
                    st.rerun()
        if "ocr_rows" in st.session_state:
            st.markdown("### Revisar y corregir antes de guardar")
            rows=st.session_state["ocr_rows"]
            df=pd.DataFrame(rows if rows else [{"ejecutivo":"","monto_generado":0,"fuente":"manual"}])
            if "fuente" not in df.columns: df["fuente"]="ocr"
            edited=st.data_editor(
                df[["ejecutivo","monto_generado","fuente"]],
                num_rows="dynamic", use_container_width=True,
                column_config={
                    "ejecutivo": st.column_config.TextColumn("Ejecutivo", required=True),
                    "monto_generado": st.column_config.NumberColumn("Generación", min_value=0, step=1, required=True),
                    "fuente": st.column_config.SelectboxColumn("Fuente", options=["ocr","manual"], default="ocr"),
                }, hide_index=True, key="ranking_editor"
            )
            if st.session_state.get("ocr_warnings"):
                with st.expander("Advertencias del OCR"):
                    for w in st.session_state["ocr_warnings"]: st.warning(w)
            with st.expander("Texto OCR bruto"):
                st.code(st.session_state.get("ocr_raw","") or "(vacío)")
            clean=[]
            for _,r in edited.iterrows():
                name=str(r["ejecutivo"]).strip()
                if not name: continue
                try: amount=max(0,int(float(r["monto_generado"])))
                except: amount=0
                clean.append((name,amount,str(r["fuente"])))
            if st.button("💾 Confirmar y guardar", type="primary", disabled=not clean):
                db=get_db()
                existing=db.execute("SELECT COUNT(*) c FROM generacion_diaria WHERE fecha=?", (selected_date.isoformat(),)).fetchone()["c"]
                st.session_state["pending_save"]={"date":selected_date.isoformat(),"rows":clean,"existing":existing}
                if existing:
                    st.warning(f"Ya existen {existing} registros para {selected_date.strftime('%d/%m/%Y')}. Para evitar duplicados debes decidir qué hacer.")
                else:
                    db.executemany("INSERT INTO generacion_diaria(ejecutivo,fecha,monto_generado,fuente,creado_en) VALUES(?,?,?,?,?)",
                                    [(n,selected_date.isoformat(),a,s,datetime.now().isoformat(timespec="seconds")) for n,a,s in clean])
                    db.commit()
                    st.success("Ranking guardado correctamente.")
                    st.session_state.pop("pending_save",None)
                    st.rerun()
            pending=st.session_state.get("pending_save")
            if pending and pending["existing"]:
                c1,c2=st.columns(2)
                if c1.button("♻️ Reemplazar registros de ese día"):
                    db=get_db()
                    db.execute("DELETE FROM generacion_diaria WHERE fecha=?", (pending["date"],))
                    db.executemany("INSERT INTO generacion_diaria(ejecutivo,fecha,monto_generado,fuente,creado_en) VALUES(?,?,?,?,?)",
                                    [(n,pending["date"],a,s,datetime.now().isoformat(timespec="seconds")) for n,a,s in pending["rows"]])
                    db.commit(); st.session_state.pop("pending_save",None)
                    st.success("Registros del día reemplazados con la carga corregida.")
                    st.rerun()
                if c2.button("❌ Cancelar carga"):
                    st.session_state.pop("pending_save",None)
                    st.info("Carga cancelada; el histórico no fue modificado.")

with tab2:
    st.subheader(f"Bitácora del día — {date.today().strftime('%d/%m/%Y')}")
    day=date.today()
    execs=get_executives_for_date(day)
    if not execs:
        st.info("Todavía no hay un ranking guardado para hoy.")
    else:
        awards=calculate_day_awards(day)
        for name in execs:
            m=calculate_executive_metrics(name,day,threshold)
            st.markdown(f"### {m['ejecutivo']}")
            cols=st.columns([1,1,1,1,2,1.2])
            cols[0].metric("Hoy",m["today"])
            cols[1].metric("MTD",m["mtd"])
            cols[2].metric("Promedio",f"{m['avg']:.2f}")
            cols[3].metric("Ranking",f"#{m['rank']}")
            cols[4].write(status_message(m))
            phone=m["phone"]
            award=[]
            if awards["best_today"]==name: award.append("mejor generación del día")
            if awards["best_growth"]==name: award.append("mayor crecimiento vs. su promedio")
            if awards["best_streak"]==name: award.append("gran racha")
            if awards["recovery"].get(name): award.append("gran recuperación")
            if m["target"] is not None and m["target"]>0 and m["mtd"]>=m["target"]: award.append("objetivo mensual cumplido")
            if award:
                phrase=" y ".join(award)
                st.success(f"🏆 Reconocimiento: {phrase}.")
                msg=recognition_text(m, phrase)
                url=wa_url(phone,msg)
                if url: st.link_button("Enviar WhatsApp",url)
                else: st.caption("Añade el teléfono en Configuración para habilitar WhatsApp.")
            elif m["zero_streak"]>=2:
                msg=alert_text(m)
                url=wa_url(phone,msg)
                if url: st.error(status_message(m))
                if url: st.link_button("Enviar WhatsApp",url)
                else: st.caption("Añade el teléfono en Configuración para habilitar WhatsApp.")
            else:
                st.write(status_message(m))
            st.divider()

with tab3:
    st.subheader("Histórico")
    months=get_available_months()
    if not months:
        st.info("No hay datos históricos todavía.")
    else:
        month=st.selectbox("Mes",months)
        names=["Todos"]+get_executives_for_date(date.fromisoformat(month+"-01"))
        # get all names in month
        db=get_db()
        names=["Todos"]+[r["ejecutivo"] for r in db.execute(
            "SELECT DISTINCT ejecutivo FROM generacion_diaria WHERE substr(fecha,1,7)=? ORDER BY ejecutivo",(month,)).fetchall()]
        who=st.selectbox("Ejecutivo",names)
        history=get_month_history(month, None if who=="Todos" else who)
        if not history: st.info("Sin registros para ese filtro.")
        for h in history:
            st.markdown(f"### {h['ejecutivo'].upper()}")
            st.write(f"**MTD:** {h['mtd']} | **Promedio diario:** {h['avg']:.2f} | "
                     f"**Mejor día:** {h['best_day']} | **Días generando:** {h['days_generating']} | "
                     f"**Días en cero:** {h['days_zero']}")
            maxv=max([x["monto"] for x in h["daily"]] or [1])
            for x in reversed(h["daily"]):
                bar="█"*max(1,round(x["monto"]/maxv*20)) if x["monto"] else "·"
                st.write(f"{date.fromisoformat(x['fecha']).strftime('%d %b'):>7} {bar} {x['monto']}")

with tab4:
    st.subheader("Configuración de ejecutivos")
    db=get_db()
    rows=db.execute("SELECT nombre,telefono,meta_mensual FROM ejecutivos ORDER BY nombre").fetchall()
    df=pd.DataFrame([dict(r) for r in rows] or [{"nombre":"","telefono":"","meta_mensual":None}])
    edited=st.data_editor(df[["nombre","telefono","meta_mensual"]],num_rows="dynamic",use_container_width=True,hide_index=True,
        column_config={"nombre":st.column_config.TextColumn("Ejecutivo",required=True),
                       "telefono":st.column_config.TextColumn("WhatsApp (con código país)",help="Ej.: 59170000000"),
                       "meta_mensual":st.column_config.NumberColumn("Meta mensual",min_value=0,step=1)})
    if st.button("Guardar configuración",type="primary"):
        db.execute("DELETE FROM ejecutivos")
        for _,r in edited.iterrows():
            n=str(r["nombre"]).strip()
            if n:
                phone=str(r["telefono"]).strip()
                meta=None if pd.isna(r["meta_mensual"]) else float(r["meta_mensual"])
                db.execute("INSERT INTO ejecutivos(nombre,telefono,meta_mensual) VALUES(?,?,?)",(n,phone,meta))
        db.commit(); st.success("Configuración guardada.")
