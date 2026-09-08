from __future__ import annotations
import json, re, traceback
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import requests
import yfinance as yf

ROOT=Path(__file__).resolve().parent
DATA=ROOT/"data.json"; CONFIG=ROOT/"config.json"; SEOUL=ZoneInfo("Asia/Seoul")

def load(p): return json.loads(p.read_text(encoding="utf-8"))
def save(p,o): p.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding="utf-8")
def clamp(v): return max(0,min(100,v))
def pct(a,b): return None if not b else round((a/b-1)*100,2)

def latest(symbol):
    df=yf.download(symbol,period="3mo",auto_adjust=False,progress=False)
    if df.empty: raise RuntimeError(symbol)
    c=df["Close"]
    if isinstance(c,pd.DataFrame): c=c.iloc[:,0]
    c=c.dropna()
    cur=float(c.iloc[-1]); w=float(c.iloc[-6] if len(c)>=6 else c.iloc[0]); m=float(c.iloc[-22] if len(c)>=22 else c.iloc[0])
    return cur,pct(cur,w),pct(cur,m)

def oil_score(p):
    if p<45:return 30
    if p<55:return 45
    if p<65:return 58
    if p<=90:return 72
    if p<=110:return 65
    return 52

def fx_score(v):
    if 1300<=v<=1400:return 70
    if 1250<=v<1300 or 1400<v<=1450:return 60
    return 48

def update():
    d=load(DATA); c=load(CONFIG); errs=[]
    for key,ticker in {"WTI":"CL=F","BRENT":"BZ=F","USDKRW":"KRW=X"}.items():
        try:
            cur,w,m=latest(ticker)
            d["market"][key].update(value=round(cur,2),change_1w=w,change_1m=m)
            d["market"][key]["score"]=oil_score(cur) if key!="USDKRW" else fx_score(cur)
        except Exception as e: errs.append(f"{key}: {e}")
    for name,ticker in c["tickers"].items():
        try:
            cur,w,m=latest(ticker)
            d["stocks"][name]={"ticker":ticker,"price":round(cur,0),"change_1w":w,"change_1m":m}
        except Exception as e: errs.append(f"{name}: {e}")

    # Baker Hughes 공개 페이지 best-effort
    try:
        txt=requests.get("https://rigcount.bakerhughes.com/",timeout=20,headers={"User-Agent":"Mozilla/5.0"}).text
        m=re.search(r'U\.?S\.?\s+Rig\s+Count[^0-9]{0,60}([0-9]{3,4})',txt,re.I)
        if m:
            cur=int(m.group(1)); old=d["market"]["US_RIGS"]["value"]
            d["market"]["US_RIGS"].update(value=cur,change_1w=cur-int(old),score=int(clamp(55+(cur-500)/3)))
    except Exception as e: errs.append(f"Rig Count: {e}")

    mi=c["manual_inputs"]
    hrc=float(mi["US_HRC"]); octg=float(mi["US_OCTG"]); spread=octg-hrc
    d["market"]["US_HRC"]["value"]=hrc; d["market"]["US_OCTG"]["value"]=octg
    d["market"]["OCTG_HRC_SPREAD"].update(value=round(spread,2),score=int(clamp(45+spread/25)))

    octg_spread=round((d["market"]["US_OCTG"]["score"]+d["market"]["OCTG_HRC_SPREAD"]["score"])/2)
    rig=round((d["market"]["US_RIGS"]["score"]+d["market"]["OIL_RIGS"]["score"])/2)
    oil=round((d["market"]["WTI"]["score"]+d["market"]["BRENT"]["score"])/2)
    comp={
      "OCTG/Spread":{"weight":35,"score":octg_spread},"Rig Count":{"weight":20,"score":rig},
      "Oil":{"weight":10,"score":oil},"HRC Cost":{"weight":10,"score":d["market"]["US_HRC"]["score"]},
      "Export":{"weight":10,"score":int(mi["EXPORT_SCORE"])},"US Policy":{"weight":10,"score":int(mi["US_POLICY_SCORE"])},
      "FX":{"weight":5,"score":d["market"]["USDKRW"]["score"]}
    }
    total=round(sum(v["weight"]*v["score"] for v in comp.values())/100)
    hist=d["history"]["pipe_score"]; prev=hist[-1] if hist else total
    if total!=prev: hist.append(total)
    d["history"]["pipe_score"]=hist[-13:]
    n=len(d["history"]["pipe_score"]); d["history"]["labels"]=[f"{n-1-i}W" for i in range(n)]; d["history"]["labels"][-1]="NOW"
    trend="BULLISH" if total>=70 else ("NEUTRAL" if total>=55 else "BEARISH")
    trend+=" · IMPROVING" if total>prev else (" · WEAKENING" if total<prev else " · FLAT")
    d["score"]={"pipe_cycle":total,"trend":trend,"components":comp}
    d["meta"].update(last_updated=datetime.now(SEOUL).isoformat(timespec="seconds"),mode="auto + manual core pricing",errors=errs)
    save(DATA,d)
    print("UPDATED",d["meta"]["last_updated"],"score",total)

if __name__=="__main__": update()
