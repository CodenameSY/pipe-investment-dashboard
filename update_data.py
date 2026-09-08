from __future__ import annotations
import json, re
from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import requests
import yfinance as yf
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data.json'; CONFIG=ROOT/'config.json'; HISTORY=ROOT/'history.json'; SEOUL=ZoneInfo('Asia/Seoul')

def load(p, default=None):
    if not p.exists(): return default
    return json.loads(p.read_text(encoding='utf-8'))
def save(p,o): p.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8')
def clamp(v): return max(0,min(100,v))
def pct(a,b): return None if b in (None,0) else round((a/b-1)*100,2)

def latest(symbol):
    df=yf.download(symbol,period='3mo',auto_adjust=False,progress=False)
    if df.empty: raise RuntimeError(symbol)
    c=df['Close']
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

def hrc_cost_score(v):
    # Cost-side score only: lower HRC generally helps welded-pipe conversion margin.
    if v <= 700: return 85
    if v <= 850: return 78
    if v <= 1000: return 70
    if v <= 1150: return 62
    if v <= 1300: return 52
    return 42

def fetch_steelbenchmarker_hrc():
    """Fetch latest USA Hot-Rolled Band from SteelBenchmarker history.pdf.

    SteelBenchmarker publishes the headline price in USD/metric tonne and,
    in parentheses, the equivalent USD/net ton (short ton). The dashboard
    uses $/st, so the parenthetical figure is preferred.
    """
    url='https://steelbenchmarker.com/history.pdf'
    r=requests.get(url, timeout=30, headers={'User-Agent':'Mozilla/5.0 pipe-investment-dashboard/5.1'})
    r.raise_for_status()
    if not r.content.startswith(b'%PDF'):
        raise RuntimeError('SteelBenchmarker history.pdf did not return a PDF')
    reader=PdfReader(BytesIO(r.content))
    text='\n'.join((page.extract_text() or '') for page in reader.pages[:6])
    text=re.sub(r'\s+', ' ', text)
    usa=re.search(r'Region:\s*USA[^:]{0,120}Hot[- ]rolled band:\s*([0-9,]+)(?:\s*\(([0-9,]+)\))?', text, re.I)
    if not usa:
        # More permissive fallback for PDF text-layout changes.
        usa_pos=re.search(r'Region:\s*USA', text, re.I)
        if not usa_pos: raise RuntimeError('USA section not found in SteelBenchmarker PDF')
        chunk=text[usa_pos.start():usa_pos.start()+1800]
        usa=re.search(r'Hot[- ]rolled band:\s*([0-9,]+)(?:\s*\(([0-9,]+)\))?', chunk, re.I)
        if not usa: raise RuntimeError('USA hot-rolled band price not found')
    metric=float(usa.group(1).replace(',',''))
    short_ton=float(usa.group(2).replace(',','')) if usa.group(2) else round(metric/1.10231131)
    # Latest release date is the nearest date preceding the first USA section.
    usa_start=usa.start()
    prefix=text[:usa_start]
    dates=list(re.finditer(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}', prefix, re.I))
    release_date=dates[-1].group(0) if dates else None
    return round(short_ton,2), release_date, url

def hist_change(rows,key,days):
    if not rows: return None
    now=datetime.now(SEOUL).date(); target=now-timedelta(days=days)
    candidates=[]
    for r in rows:
        try: dt=datetime.fromisoformat(r['date']).date()
        except Exception: continue
        v=r.get(key)
        if v is not None and dt<=target: candidates.append((dt,float(v)))
    if not candidates:return None
    _,old=max(candidates,key=lambda x:x[0])
    cur=rows[-1].get(key)
    return pct(float(cur),old) if cur is not None else None

def update():
    d=load(DATA); c=load(CONFIG); hist=load(HISTORY,{'snapshots':[]}); errs=[]
    d['meta']['version']='v5.1'
    for key,ticker in {'WTI':'CL=F','BRENT':'BZ=F','USDKRW':'KRW=X'}.items():
        try:
            cur,w,m=latest(ticker)
            d['market'][key].update(value=round(cur,2),change_1w=w,change_1m=m)
            d['market'][key]['score']=oil_score(cur) if key!='USDKRW' else fx_score(cur)
        except Exception as e: errs.append(f'{key}: {e}')
    for name,ticker in c['tickers'].items():
        try:
            cur,w,m=latest(ticker)
            d['stocks'][name]={'ticker':ticker,'price':round(cur,0),'change_1w':w,'change_1m':m}
        except Exception as e: errs.append(f'{name}: {e}')

    # US total rig count: Baker Hughes public page, best effort.
    try:
        txt=requests.get('https://rigcount.bakerhughes.com/',timeout=20,headers={'User-Agent':'Mozilla/5.0'}).text
        m=re.search(r'U\.?S\.?\s+Rig\s+Count[^0-9]{0,60}([0-9]{3,4})',txt,re.I)
        if m:
            cur=int(m.group(1)); old=d['market']['US_RIGS']['value']
            d['market']['US_RIGS'].update(value=cur,change_1w=cur-int(old),score=int(clamp(55+(cur-500)/3)))
    except Exception as e: errs.append(f'Rig Count: {e}')

    mi=c['manual_inputs']
    # HRC: automatic SteelBenchmarker pull, with config.json fallback.
    try:
        hrc, hrc_date, hrc_url = fetch_steelbenchmarker_hrc()
        d['market']['US_HRC'].update(value=hrc, score=hrc_cost_score(hrc), manual=False, source='SteelBenchmarker', source_date=hrc_date, source_url=hrc_url)
    except Exception as e:
        hrc=float(mi['US_HRC'])
        d['market']['US_HRC'].update(value=hrc, score=hrc_cost_score(hrc), manual=True, source='config.json fallback', source_date=None)
        errs.append(f'HRC auto: {e}')

    # OCTG remains manual until a licensed/structured series is connected.
    octg=float(mi['US_OCTG'])
    d['market']['US_OCTG'].update(value=octg, manual=True, source='config.json')
    spread=octg-hrc
    d['market']['OCTG_HRC_SPREAD']['value']=round(spread,2)
    d['market']['OCTG_HRC_SPREAD']['score']=int(clamp(45+spread/25))

    octg_spread=round((d['market']['US_OCTG']['score']+d['market']['OCTG_HRC_SPREAD']['score'])/2)
    rig=round((d['market']['US_RIGS']['score']+d['market']['OIL_RIGS']['score'])/2)
    oil=round((d['market']['WTI']['score']+d['market']['BRENT']['score'])/2)
    comp={
      'OCTG/Spread':{'weight':35,'score':octg_spread},'Rig Count':{'weight':20,'score':rig},
      'Oil':{'weight':10,'score':oil},'HRC Cost':{'weight':10,'score':d['market']['US_HRC']['score']},
      'Export':{'weight':10,'score':int(mi['EXPORT_SCORE'])},'US Policy':{'weight':10,'score':int(mi['US_POLICY_SCORE'])},
      'FX':{'weight':5,'score':d['market']['USDKRW']['score']}}
    total=round(sum(v['weight']*v['score'] for v in comp.values())/100)

    rows=hist.setdefault('snapshots',[])
    prev_score=rows[-1].get('PIPE_SCORE',total) if rows else total
    trend='BULLISH' if total>=70 else ('NEUTRAL' if total>=55 else 'BEARISH')
    trend+=' · IMPROVING' if total>prev_score else (' · WEAKENING' if total<prev_score else ' · FLAT')
    d['score']={'pipe_cycle':total,'trend':trend,'components':comp}

    today=datetime.now(SEOUL).date().isoformat()
    snap={'date':today,'PIPE_SCORE':total}
    for key in ['WTI','BRENT','USDKRW','US_RIGS','OIL_RIGS','US_HRC','US_OCTG','OCTG_HRC_SPREAD']:
        snap[key]=d['market'][key]['value']
    if rows and rows[-1].get('date')==today: rows[-1]=snap
    else: rows.append(snap)
    hist['snapshots']=rows[-730:]
    save(HISTORY,hist)

    # Once enough real snapshots exist, replace manual 1M display changes with history-derived values.
    for key in ['US_HRC','US_OCTG','OCTG_HRC_SPREAD']:
        ch=hist_change(hist['snapshots'],key,28)
        if ch is not None: d['market'][key]['change_1m']=ch

    # Score history now uses dated, real snapshots rather than illustrative bars.
    recent=hist['snapshots'][-13:]
    d['history']={'pipe_score':[r['PIPE_SCORE'] for r in recent], 'labels':[r['date'][5:] for r in recent]}
    d['meta'].update(last_updated=datetime.now(SEOUL).isoformat(timespec='seconds'),mode='auto HRC (SteelBenchmarker) + manual OCTG + persistent history',errors=errs)
    save(DATA,d)
    print('UPDATED',d['meta']['last_updated'],'score',total,'history rows',len(hist['snapshots']))

if __name__=='__main__': update()
