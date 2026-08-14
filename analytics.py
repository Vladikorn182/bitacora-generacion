from datetime import date, timedelta
from db import get_db

def business_days_elapsed(year,month,until_day):
    d=date(year,month,1); end=date(year,month,until_day)
    return sum(1 for i in range((end-d).days+1) if (d+timedelta(days=i)).weekday()<5)

def get_executives_for_date(day):
    db=get_db()
    return [r["ejecutivo"] for r in db.execute(
        "SELECT DISTINCT ejecutivo FROM generacion_diaria WHERE fecha=? ORDER BY ejecutivo",(day.isoformat(),)).fetchall()]

def _amount(db,name,d):
    r=db.execute("SELECT COALESCE(SUM(monto_generado),0) v FROM generacion_diaria WHERE ejecutivo=? AND fecha=?",(name,d.isoformat())).fetchone()
    return float(r["v"])

def _dates_for_month(name,day):
    start=date(day.year,day.month,1)
    return start

def calculate_executive_metrics(name, day, threshold=3):
    db=get_db()
    mtd=float(db.execute("SELECT COALESCE(SUM(monto_generado),0) v FROM generacion_diaria WHERE ejecutivo=? AND fecha LIKE ?",
                         (name,day.strftime("%Y-%m")+"%")).fetchone()["v"])
    elapsed=business_days_elapsed(day.year,day.month,day.day)
    avg=mtd/elapsed if elapsed else 0
    today=_amount(db,name,day)
    # Ranking: based on the day's generation, descending; ties share a position.
    rankrow=db.execute("""SELECT 1 + COUNT(DISTINCT ejecutivo) rankpos
                         FROM generacion_diaria
                         WHERE fecha=? AND monto_generado>?
                           AND ejecutivo<>?""",(day.isoformat(),today,name)).fetchone()
    rank=int(rankrow["rankpos"])
    # Consecutive streaks only traverse dates that exist for this executive.
    gen_streak=zero_streak=0
    cursor=day
    while True:
        rows=db.execute("SELECT COALESCE(SUM(monto_generado),0) v FROM generacion_diaria WHERE ejecutivo=? AND fecha=?",(name,cursor.isoformat())).fetchone()
        if rows is None: break
        # If no row at all, stop; absence means unknown, not zero.
        exists=db.execute("SELECT 1 FROM generacion_diaria WHERE ejecutivo=? AND fecha=? LIMIT 1",(name,cursor.isoformat())).fetchone()
        if not exists: break
        val=float(rows["v"])
        if val>0:
            if zero_streak==0: gen_streak+=1
            else: break
        else:
            if gen_streak==0: zero_streak+=1
            else: break
        cursor-=timedelta(days=1)
    # If today's value is zero, gen_streak should be zero and vice versa.
    if today>0:
        gen_streak=0; zero_streak=0
        cursor=day
        while True:
            exists=db.execute("SELECT 1 FROM generacion_diaria WHERE ejecutivo=? AND fecha=? LIMIT 1",(name,cursor.isoformat())).fetchone()
            if not exists: break
            val=_amount(db,name,cursor)
            if val>0: gen_streak+=1; cursor-=timedelta(days=1)
            else: break
    else:
        zero_streak=0; gen_streak=0; cursor=day
        while True:
            exists=db.execute("SELECT 1 FROM generacion_diaria WHERE ejecutivo=? AND fecha=? LIMIT 1",(name,cursor.isoformat())).fetchone()
            if not exists: break
            val=_amount(db,name,cursor)
            if val==0: zero_streak+=1; cursor-=timedelta(days=1)
            else: break
    vals=[]
    for i in range(5):
        d=day-timedelta(days=i)
        if d.month!=day.month: continue
        vals.append(_amount(db,name,d))
    if len(vals)>=3:
        recent=vals[:3]
        prior=vals[3:5] or vals[2:3]
        ra=sum(recent)/len(recent); pa=sum(prior)/len(prior)
        trend="subiendo" if ra>pa*1.05 else ("bajando" if ra<pa*0.95 else "estable")
    else: trend="estable"
    er=db.execute("SELECT telefono,meta_mensual FROM ejecutivos WHERE nombre=?",(name,)).fetchone()
    return {"ejecutivo":name,"today":int(today) if today.is_integer() else today,"mtd":int(mtd) if mtd.is_integer() else mtd,
            "avg":avg,"rank":rank,"generate_streak":gen_streak,"zero_streak":zero_streak,
            "trend":trend,"phone":er["telefono"] if er else "","target":er["meta_mensual"] if er else None,
            "streak_threshold":threshold,"generated_today":today>0}

def calculate_day_awards(day):
    names=get_executives_for_date(day)
    metrics=[calculate_executive_metrics(n,day) for n in names]
    if not metrics: return {"best_today":None,"best_growth":None,"best_streak":None,"recovery":{}}
    best=max(metrics,key=lambda x:x["today"])
    growths=[]
    for m in metrics:
        # Compara hoy contra el promedio propio anterior a hoy, evitando circularidad.
        elapsed_before=business_days_elapsed(day.year,day.month,max(day.day-1,0))
        prior_mtd=m["mtd"]-m["today"]
        prior_avg=prior_mtd/elapsed_before if elapsed_before else 0
        growth=(m["today"]/prior_avg-1) if prior_avg>0 else (float("inf") if m["today"]>0 else 0)
        growths.append((growth,m["ejecutivo"]))
    best_growth=max(growths,key=lambda x:x[0])[1] if growths else None
    best_streak=max(metrics,key=lambda x:x["generate_streak"])
    recovery={}
    db=get_db()
    for m in metrics:
        prev=[]
        for i in (1,2):
            d=day-timedelta(days=i)
            if d.month==day.month: prev.append(_amount(db,m["ejecutivo"],d))
        recovery[m["ejecutivo"]]=len(prev)>=2 and all(v==0 for v in prev) and m["today"]>0
    return {"best_today":best["ejecutivo"],"best_growth":best_growth,
            "best_streak":best_streak["ejecutivo"],"recovery":recovery}

def get_available_months():
    db=get_db()
    return [r["m"] for r in db.execute("SELECT DISTINCT substr(fecha,1,7) m FROM generacion_diaria ORDER BY m DESC").fetchall()]

def get_month_history(month,name=None):
    db=get_db()
    params=[month]
    q="SELECT ejecutivo,fecha,SUM(monto_generado) monto FROM generacion_diaria WHERE fecha LIKE ?"
    if name:
        q+=" AND ejecutivo=?"; params.append(name)
    q+=" GROUP BY ejecutivo,fecha ORDER BY ejecutivo,fecha"
    rows=db.execute(q,params).fetchall()
    grouped={}
    for r in rows: grouped.setdefault(r["ejecutivo"],[]).append({"fecha":r["fecha"],"monto":float(r["monto"])})
    out=[]
    import calendar
    y,m=map(int,month.split("-"))
    if date.today().strftime("%Y-%m")==month:
        elapsed=business_days_elapsed(y,m,date.today().day)
    else:
        elapsed=sum(1 for d in range(1,calendar.monthrange(y,m)[1]+1) if date(y,m,d).weekday()<5)
    for n,daily in grouped.items():
        vals=[x["monto"] for x in daily]
        out.append({"ejecutivo":n,"mtd":sum(vals),"avg":sum(vals)/(elapsed or 1),
                    "best_day":max(vals) if vals else 0,
                    "days_generating":sum(v>0 for v in vals),"days_zero":sum(v==0 for v in vals),
                    "daily":daily})
    return out
