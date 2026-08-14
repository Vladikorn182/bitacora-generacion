from datetime import date, timedelta
from db import get_db


def business_days_elapsed(year, month, until_day):
    if until_day <= 0:
        return 0
    start = date(year, month, 1)
    end = date(year, month, until_day)
    return sum(
        1
        for i in range((end - start).days + 1)
        if (start + timedelta(days=i)).weekday() < 5
    )


def get_executives_for_date(day):
    db = get_db()
    return [
        r["ejecutivo"]
        for r in db.execute(
            "SELECT DISTINCT ejecutivo FROM generacion_diaria WHERE fecha=? ORDER BY ejecutivo",
            (day.isoformat(),),
        ).fetchall()
    ]


def _amount(db, name, day):
    row = db.execute(
        "SELECT COALESCE(SUM(monto_generado),0) AS v FROM generacion_diaria WHERE ejecutivo=? AND fecha=?",
        (name, day.isoformat()),
    ).fetchone()
    return float(row["v"])


def _exists(db, name, day):
    return db.execute(
        "SELECT 1 FROM generacion_diaria WHERE ejecutivo=? AND fecha=? LIMIT 1",
        (name, day.isoformat()),
    ).fetchone() is not None


def _streak(db, name, day, positive):
    streak = 0
    cursor = day
    while _exists(db, name, cursor):
        value = _amount(db, name, cursor)
        if (value > 0) != positive:
            break
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def calculate_executive_metrics(name, day, threshold=3):
    db = get_db()
    month_prefix = day.strftime("%Y-%m") + "%"
    mtd = float(
        db.execute(
            "SELECT COALESCE(SUM(monto_generado),0) AS v FROM generacion_diaria WHERE ejecutivo=? AND fecha LIKE ?",
            (name, month_prefix),
        ).fetchone()["v"]
    )
    elapsed = business_days_elapsed(day.year, day.month, day.day)
    avg = mtd / elapsed if elapsed else 0
    today = _amount(db, name, day)

    rank = int(
        db.execute(
            """
            SELECT 1 + COUNT(DISTINCT ejecutivo) AS rankpos
            FROM generacion_diaria
            WHERE fecha=? AND monto_generado>? AND ejecutivo<>?
            """,
            (day.isoformat(), today, name),
        ).fetchone()["rankpos"]
    )

    generate_streak = _streak(db, name, day, True) if today > 0 else 0
    zero_streak = _streak(db, name, day, False) if today == 0 else 0

    values = []
    for i in range(5):
        d = day - timedelta(days=i)
        if d.month != day.month:
            continue
        if _exists(db, name, d):
            values.append(_amount(db, name, d))

    if len(values) >= 3:
        recent = values[:3]
        prior = values[3:5] or values[2:3]
        recent_avg = sum(recent) / len(recent)
        prior_avg = sum(prior) / len(prior)
        if recent_avg > prior_avg * 1.05:
            trend = "subiendo"
        elif recent_avg < prior_avg * 0.95:
            trend = "bajando"
        else:
            trend = "estable"
    else:
        trend = "estable"

    er = db.execute(
        "SELECT telefono,meta_mensual FROM ejecutivos WHERE nombre=?",
        (name,),
    ).fetchone()

    return {
        "ejecutivo": name,
        "today": int(today) if today.is_integer() else today,
        "mtd": int(mtd) if mtd.is_integer() else mtd,
        "avg": avg,
        "rank": rank,
        "generate_streak": generate_streak,
        "zero_streak": zero_streak,
        "trend": trend,
        "phone": er["telefono"] if er else "",
        "target": er["meta_mensual"] if er else None,
        "streak_threshold": threshold,
        "generated_today": today > 0,
    }


def calculate_day_awards(day):
    names = get_executives_for_date(day)
    metrics = [calculate_executive_metrics(n, day) for n in names]
    if not metrics:
        return {
            "best_today": None,
            "best_growth": None,
            "best_streak": None,
            "recovery": {},
        }

    best_today = max(metrics, key=lambda x: x["today"])

    elapsed_before = business_days_elapsed(
        day.year, day.month, max(day.day - 1, 0)
    )
    growths = []
    for m in metrics:
        prior_mtd = m["mtd"] - m["today"]
        prior_avg = prior_mtd / elapsed_before if elapsed_before else 0
        if prior_avg > 0:
            growth = m["today"] / prior_avg - 1
        elif m["today"] > 0:
            growth = float("inf")
        else:
            growth = 0
        growths.append((growth, m["ejecutivo"]))

    best_growth = max(growths, key=lambda x: x[0])[1] if growths else None
    best_streak = max(metrics, key=lambda x: x["generate_streak"])

    db = get_db()
    recovery = {}
    for m in metrics:
        previous = []
        for offset in (1, 2):
            d = day - timedelta(days=offset)
            if d.month == day.month and _exists(db, m["ejecutivo"], d):
                previous.append(_amount(db, m["ejecutivo"], d))
        recovery[m["ejecutivo"]] = (
            len(previous) == 2
            and previous[0] == 0
            and previous[1] == 0
            and m["today"] > 0
        )

    return {
        "best_today": best_today["ejecutivo"],
        "best_growth": best_growth,
        "best_streak": best_streak["ejecutivo"],
        "recovery": recovery,
    }


def get_available_months():
    db = get_db()
    return [
        r["m"]
        for r in db.execute(
            "SELECT DISTINCT substr(fecha,1,7) AS m FROM generacion_diaria ORDER BY m DESC"
        ).fetchall()
    ]


def get_month_history(month, name=None):
    db = get_db()
    params = [month + "%"]
    query = """
        SELECT ejecutivo, fecha, SUM(monto_generado) AS monto
        FROM generacion_diaria
        WHERE fecha LIKE ?
    """
    if name:
        query += " AND ejecutivo=?"
        params.append(name)
    query += " GROUP BY ejecutivo, fecha ORDER BY ejecutivo, fecha"

    rows = db.execute(query, params).fetchall()
    grouped = {}
    for r in rows:
        grouped.setdefault(r["ejecutivo"], []).append(
            {"fecha": r["fecha"], "monto": float(r["monto"])}
        )

    import calendar

    year, month_number = map(int, month.split("-"))
    if date.today().strftime("%Y-%m") == month:
        elapsed = business_days_elapsed(year, month_number, date.today().day)
    else:
        elapsed = sum(
            1
            for d in range(1, calendar.monthrange(year, month_number)[1] + 1)
            if date(year, month_number, d).weekday() < 5
        )

    output = []
    for executive, daily in grouped.items():
        values = [item["monto"] for item in daily]
        total = sum(values)
        output.append(
            {
                "ejecutivo": executive,
                "mtd": total,
                "avg": total / elapsed if elapsed else 0,
                "best_day": max(values) if values else 0,
                "days_generating": sum(v > 0 for v in values),
                "days_zero": sum(v == 0 for v in values),
                "daily": daily,
            }
        )
    return output
