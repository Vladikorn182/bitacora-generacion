import streamlit as st
import pandas as pd
from datetime import date, datetime
from urllib.parse import quote

from db import init_db, get_db, upsert_config_defaults
from ocr import extract_ranking
from analytics import (
    get_executives_for_date,
    calculate_executive_metrics,
    calculate_day_awards,
    get_month_history,
    get_available_months,
)

st.set_page_config(
    page_title="Bitácora Diaria de Generación",
    page_icon="📊",
    layout="wide",
)

init_db()
upsert_config_defaults()

st.title("📊 Bitácora Diaria de Generación")
st.caption(
    "Sube el ranking diario → corrige OCR → guarda → la aplicación calcula "
    "avance, rachas, tendencia, reconocimientos y alertas."
)


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
    name = m["ejecutivo"]
    z = m["zero_streak"]
    if z >= 3:
        return (
            f"Hola {name}, llevas {z} días consecutivos sin registrar generación. "
            "Necesitamos una recuperación inmediata. Por favor indícame hoy qué "
            "está bloqueando tu producción y coordinemos una reunión o llamada "
            "para definir acciones concretas. Necesito tu compromiso de recuperación desde hoy."
        )
    return (
        f"Hola {name}, revisamos tu generación de los últimos días y vemos que llevas "
        f"{z} días sin registrar ventas. Necesitamos recuperar generación. Por favor "
        "indícame qué dificultades estás teniendo y qué acciones realizarás hoy."
    )


def recognition_text(m, phrase):
    return (
        f"¡Excelente trabajo, {m['ejecutivo']}! 👏 Hoy generaste {m['today']} y alcanzaste "
        f"{m['mtd']} MTD. {phrase}. Mantén este ritmo."
    )


def progress_text(m):
    return (
        f"Hola {m['ejecutivo']}, este es tu avance de hoy: generaste {m['today']}, "
        f"llevas {m['mtd']} MTD, tu promedio diario es {m['avg']:.2f}, "
        f"estás en el puesto #{m['rank']} y llevas {m['generate_streak']} día(s) "
        f"consecutivo(s) generando. Tendencia: {m['trend']}."
    )


def recognition_phrase(m, awards):
    phrases = []
    if awards["best_today"] == m["ejecutivo"]:
        phrases.append("liderando la generación del día")
    if awards["best_growth"] == m["ejecutivo"]:
        phrases.append("con el mayor crecimiento frente a tu propio promedio")
    if awards["recovery"].get(m["ejecutivo"]):
        phrases.append("con una gran recuperación")
    if awards["best_streak"] == m["ejecutivo"] and m["generate_streak"] >= 2:
        phrases.append("manteniendo una gran racha")
    if m["target"] is not None and m["target"] > 0 and m["mtd"] >= m["target"]:
        phrases.append("cumpliendo tu objetivo mensual")
    if not phrases:
        phrases.append(f"manteniendo {m['generate_streak']} días consecutivos generando")
    return " y ".join(phrases)


with st.sidebar:
    st.header("Configuración rápida")
    threshold = st.number_input(
        "Racha para 🟢 Excelente",
        min_value=2,
        max_value=10,
        value=3,
        step=1,
        help="Por defecto: 3 días consecutivos generando.",
    )
    st.divider()
    st.info(
        "Los teléfonos y las metas mensuales se configuran en ⚙️ Configuración. "
        "Sin teléfono, el mensaje se mostrará pero no habrá botón de WhatsApp."
    )


tab1, tab2, tab3, tab4 = st.tabs(
    ["📷 Cargar ranking", "📅 Bitácora / hoy", "📈 Histórico", "⚙️ Configuración"]
)

# ============================================================
# CARGAR RANKING
# ============================================================
with tab1:
    st.subheader("Cargar ranking")
    uploaded = st.file_uploader(
        "Sube UNA foto/captura del ranking diario",
        type=["png", "jpg", "jpeg", "webp"],
    )
    selected_date = st.date_input(
        "Fecha del ranking",
        value=st.session_state.get("suggested_date", date.today()),
        key="ranking_date",
    )

    if uploaded:
        image_bytes = uploaded.getvalue()
        st.image(image_bytes, caption="Imagen cargada", width=900)

        if st.button("🔎 Ejecutar OCR", type="primary"):
            rows, raw_text, warnings, suggested_day = extract_ranking(image_bytes)
            if suggested_day:
                try:
                    st.session_state["suggested_date"] = date(
                        date.today().year, date.today().month, suggested_day
                    )
                except ValueError:
                    pass
            st.session_state["ocr_rows"] = rows
            st.session_state["ocr_raw"] = raw_text
            st.session_state["ocr_warnings"] = warnings
            st.session_state["ocr_filename"] = uploaded.name
            st.success(f"OCR terminado: {len(rows)} filas candidatas.")
            if suggested_day:
                st.info(
                    f"El encabezado de la imagen sugiere Día {suggested_day}. "
                    "Revisa la fecha antes de guardar."
                )

        if "ocr_rows" in st.session_state:
            st.markdown("### Revisar y corregir antes de guardar")
            rows = st.session_state["ocr_rows"]
            df = pd.DataFrame(
                rows
                if rows
                else [{"ejecutivo": "", "monto_generado": 0, "fuente": "manual"}]
            )
            if "fuente" not in df.columns:
                df["fuente"] = "ocr"

            edited = st.data_editor(
                df[["ejecutivo", "monto_generado", "fuente"]],
                num_rows="dynamic",
                use_container_width=True,
                column_config={
                    "ejecutivo": st.column_config.TextColumn("Ejecutivo", required=True),
                    "monto_generado": st.column_config.NumberColumn(
                        "Generación del día", min_value=0, step=1, required=True
                    ),
                    "fuente": st.column_config.SelectboxColumn(
                        "Fuente", options=["ocr", "manual"], default="ocr"
                    ),
                },
                hide_index=True,
                key="ranking_editor",
            )

            if st.session_state.get("ocr_warnings"):
                with st.expander("⚠️ Advertencias del OCR"):
                    for warning in st.session_state["ocr_warnings"]:
                        st.warning(warning)

            with st.expander("Texto OCR bruto"):
                st.code(st.session_state.get("ocr_raw", "") or "(vacío)")

            clean = []
            for _, row in edited.iterrows():
                name = str(row["ejecutivo"]).strip()
                if not name:
                    continue
                try:
                    amount = max(0, int(float(row["monto_generado"])))
                except Exception:
                    amount = 0
                source = str(row["fuente"])
                if source not in ("ocr", "manual"):
                    source = "manual"
                clean.append((name, amount, source))

            if st.button("💾 Confirmar y guardar", type="primary", disabled=not clean):
                db = get_db()
                existing = db.execute(
                    "SELECT COUNT(*) AS c FROM generacion_diaria WHERE fecha=?",
                    (selected_date.isoformat(),),
                ).fetchone()["c"]

                st.session_state["pending_save"] = {
                    "date": selected_date.isoformat(),
                    "rows": clean,
                    "existing": existing,
                }

                if existing:
                    st.warning(
                        f"Ya existen {existing} registros para {selected_date.strftime('%d/%m/%Y')}. "
                        "Elige reemplazar o cancelar."
                    )
                else:
                    db.executemany(
                        """
                        INSERT INTO generacion_diaria
                        (ejecutivo, fecha, monto_generado, fuente, creado_en)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                name,
                                selected_date.isoformat(),
                                amount,
                                source,
                                datetime.now().isoformat(timespec="seconds"),
                            )
                            for name, amount, source in clean
                        ],
                    )
                    db.commit()
                    st.session_state.pop("pending_save", None)
                    st.success(
                        f"Ranking del {selected_date.strftime('%d/%m/%Y')} guardado. "
                        "Ahora abre 📅 Bitácora / hoy para ver mensajes y WhatsApp."
                    )

            pending = st.session_state.get("pending_save")
            if pending and pending["existing"]:
                c1, c2 = st.columns(2)
                if c1.button("♻️ Reemplazar registros de ese día"):
                    db = get_db()
                    db.execute("DELETE FROM generacion_diaria WHERE fecha=?", (pending["date"],))
                    db.executemany(
                        """
                        INSERT INTO generacion_diaria
                        (ejecutivo, fecha, monto_generado, fuente, creado_en)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                name,
                                pending["date"],
                                amount,
                                source,
                                datetime.now().isoformat(timespec="seconds"),
                            )
                            for name, amount, source in pending["rows"]
                        ],
                    )
                    db.commit()
                    st.session_state.pop("pending_save", None)
                    st.success("Registros del día reemplazados correctamente.")

                if c2.button("❌ Cancelar carga"):
                    st.session_state.pop("pending_save", None)
                    st.info("Carga cancelada; el histórico no fue modificado.")

# ============================================================
# BITÁCORA / MENSAJES
# ============================================================
with tab2:
    st.subheader(f"Bitácora del día — {date.today().strftime('%d/%m/%Y')}")
    day = date.today()
    execs = get_executives_for_date(day)

    if not execs:
        st.info(
            "Todavía no hay un ranking guardado para hoy. "
            "Primero confirma y guarda la carga en 📷 Cargar ranking."
        )
    else:
        awards = calculate_day_awards(day)
        metrics_list = [calculate_executive_metrics(name, day, threshold) for name in execs]

        # Resumen ejecutivo
        total_today = sum(m["today"] for m in metrics_list)
        generating = sum(m["generated_today"] for m in metrics_list)
        alerts = sum(m["zero_streak"] >= 2 for m in metrics_list)
        critical = sum(m["zero_streak"] >= 3 for m in metrics_list)
        strong = sum(
            m["generated_today"] and m["generate_streak"] >= threshold
            for m in metrics_list
        )

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Generación hoy", total_today)
        c2.metric("Generando", generating)
        c3.metric("🟢 Buen ritmo", strong)
        c4.metric("🚨 Alertas", alerts)
        c5.metric("🚨 Críticas", critical)

        st.divider()
        st.markdown("### 📱 Mensajes personalizados")
        st.caption(
            "Aquí se genera el mensaje real para cada ejecutivo. "
            "El botón abre WhatsApp con el texto precargado; la aplicación nunca envía automáticamente."
        )

        for m in metrics_list:
            name = m["ejecutivo"]
            award_phrase = recognition_phrase(m, awards)
            is_strong = m["generated_today"] and m["generate_streak"] >= threshold
            is_recovery = awards["recovery"].get(name, False)

            if m["zero_streak"] >= 3:
                category = "🚨 ALERTA CRÍTICA"
                message = alert_text(m)
                box = st.error
            elif m["zero_streak"] == 2:
                category = "🚨 ALERTA"
                message = alert_text(m)
                box = st.warning
            elif is_strong or is_recovery or awards["best_today"] == name or awards["best_growth"] == name:
                category = "🟢 FELICITACIÓN"
                message = recognition_text(m, award_phrase)
                box = st.success
            elif m["generated_today"]:
                category = "🟡 AVANCE"
                message = progress_text(m)
                box = st.info
            else:
                category = "🔴 HOY NO GENERÓ"
                message = progress_text(m)
                box = st.info

            with st.container(border=True):
                left, right = st.columns([2.3, 1])
                with left:
                    st.markdown(f"#### {name} — {category}")
                    st.write(
                        f"Hoy: **{m['today']}** | MTD: **{m['mtd']}** | "
                        f"Promedio: **{m['avg']:.2f}** | Ranking: **#{m['rank']}** | "
                        f"Racha generando: **{m['generate_streak']}** | "
                        f"Racha cero: **{m['zero_streak']}** | Tendencia: **{m['trend']}**"
                    )
                    box("**Mensaje:**\n\n" + message)
                with right:
                    url = wa_url(m["phone"], message)
                    if url:
                        st.link_button("📲 Enviar WhatsApp", url, use_container_width=True)
                        st.caption(f"Número: {m['phone']}")
                    else:
                        st.warning("Falta teléfono")
                        st.caption(
                            "Ve a ⚙️ Configuración y agrega el número con código de país."
                        )

        st.divider()
        st.markdown("### 🏆 Reconocimientos del día")
        st.write(f"🥇 Mejor generación del día: **{awards['best_today'] or '—'}**")
        st.write(f"📈 Mayor crecimiento vs. promedio propio: **{awards['best_growth'] or '—'}**")
        st.write(f"🔥 Racha más larga: **{awards['best_streak'] or '—'}**")
        recovered = [n for n, yes in awards["recovery"].items() if yes]
        st.write(f"🔄 Recuperación (2+ ceros → genera): **{', '.join(recovered) if recovered else '—'}**")

# ============================================================
# HISTÓRICO
# ============================================================
with tab3:
    st.subheader("Histórico")
    months = get_available_months()
    if not months:
        st.info("No hay datos históricos todavía.")
    else:
        month = st.selectbox("Mes", months)
        db = get_db()
        names = ["Todos"] + [
            r["ejecutivo"]
            for r in db.execute(
                "SELECT DISTINCT ejecutivo FROM generacion_diaria WHERE substr(fecha,1,7)=? ORDER BY ejecutivo",
                (month,),
            ).fetchall()
        ]
        who = st.selectbox("Ejecutivo", names)
        history = get_month_history(month, None if who == "Todos" else who)
        if not history:
            st.info("Sin registros para ese filtro.")
        for h in history:
            st.markdown(f"### {h['ejecutivo'].upper()}")
            st.write(
                f"**MTD:** {h['mtd']} | **Promedio diario:** {h['avg']:.2f} | "
                f"**Mejor día:** {h['best_day']} | **Días generando:** {h['days_generating']} | "
                f"**Días en cero:** {h['days_zero']}"
            )
            maxv = max([x["monto"] for x in h["daily"]] or [1])
            for x in reversed(h["daily"]):
                bar = "█" * max(1, round(x["monto"] / maxv * 20)) if x["monto"] else "·"
                st.write(
                    f"{date.fromisoformat(x['fecha']).strftime('%d %b'):>7} {bar} {x['monto']}"
                )

# ============================================================
# CONFIGURACIÓN
# ============================================================
with tab4:
    st.subheader("Configuración de ejecutivos")
    st.info(
        "Carga aquí el número de WhatsApp de cada ejecutivo. "
        "Formato recomendado: código de país + número, sin + ni espacios. "
        "Ejemplo Bolivia: 59170000000."
    )
    db = get_db()
    rows = db.execute(
        "SELECT nombre,telefono,meta_mensual FROM ejecutivos ORDER BY nombre"
    ).fetchall()
    df = pd.DataFrame(
        [dict(r) for r in rows]
        or [{"nombre": "", "telefono": "", "meta_mensual": None}]
    )
    edited = st.data_editor(
        df[["nombre", "telefono", "meta_mensual"]],
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={
            "nombre": st.column_config.TextColumn("Ejecutivo", required=True),
            "telefono": st.column_config.TextColumn("WhatsApp (con código país)"),
            "meta_mensual": st.column_config.NumberColumn("Meta mensual", min_value=0, step=1),
        },
    )
    if st.button("Guardar configuración", type="primary"):
        db.execute("DELETE FROM ejecutivos")
        for _, row in edited.iterrows():
            n = str(row["nombre"]).strip()
            if not n:
                continue
            phone = str(row["telefono"]).strip()
            meta = None if pd.isna(row["meta_mensual"]) else float(row["meta_mensual"])
            db.execute(
                "INSERT INTO ejecutivos(nombre,telefono,meta_mensual) VALUES(?,?,?)",
                (n, phone, meta),
            )
        db.commit()
        st.success("Configuración guardada. Los botones de WhatsApp ya usarán esos números.")
