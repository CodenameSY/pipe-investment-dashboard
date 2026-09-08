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

def yf_close(symbol, period='3mo'):
    df=yf.download(symbol,period=period,auto_adjust=False,progress=False)
    if df.empty: raise RuntimeError(symbol)
    c=df['Close']; c=c.iloc[:,0] if isinstance(c,pd.DataFrame) else c
    return c.dropna()
def latest(symbol):
    c=yf_close(symbol,'3mo'); cur=float(c.iloc[-1]); w=float(c.iloc[-6] if len(c)>=6 else c.iloc[0]); m=float(c.iloc[-22] if len(c)>=22 else c.iloc[0])
    return cur,pct(cur,w),pct(cur,m)
def merge_market_history(rows,mapping):
    by={r['date']:dict(r) for r in rows if r.get('date')}
    for key,ticker in mapping.items():
        for ts,val in yf_close(ticker,'3mo').items():
            d=pd.Timestamp(ts).date().isoformat(); by.setdefault(d,{'date':d})[key]=round(float(val),4)
    return [by[d] for d in sorted(by)]
def oil_score(p):
    if p<45:return 30
    if p<55:return 45
    if p<65:return 58
    if p<=90:return 72
    if p<=110:return 65
    return 52
def fx_score(v): return 70 if 1300<=v<=1400 else (60 if 1250<=v<1300 or 1400<v<=1450 else 48)
def hrc_cost_score(v):
    if v<=700:return 85
    if v<=850:return 78
    if v<=1000:return 70
    if v<=1150:return 62
    if v<=1300:return 52
    return 42

def fetch_steelbenchmarker_hrc():
    url='https://steelbenchmarker.com/history.pdf'; r=requests.get(url,timeout=30,headers={'User-Agent':'Mozilla/5.0 pipe-investment-dashboard/5.3'}); r.raise_for_status()
    if not r.content.startswith(b'%PDF'): raise RuntimeError('SteelBenchmarker history.pdf did not return a PDF')
    text='\n'.join((p.extract_text() or '') for p in PdfReader(BytesIO(r.content)).pages[:6]); text=re.sub(r'\s+',' ',text)
    usa=re.search(r'Region:\s*USA[^:]{0,120}Hot[- ]rolled band:\s*([0-9,]+)(?:\s*\(([0-9,]+)\))?',text,re.I)
    if not usa:
        pos=re.search(r'Region:\s*USA',text,re.I)
        if not pos: raise RuntimeError('USA section not found')
        usa=re.search(r'Hot[- ]rolled band:\s*([0-9,]+)(?:\s*\(([0-9,]+)\))?',text[pos.start():pos.start()+1800],re.I)
        if not usa: raise RuntimeError('USA HRC not found')
    metric=float(usa.group(1).replace(',','')); st=float(usa.group(2).replace(',','')) if usa.group(2) else round(metric/1.10231131)
    dates=list(re.finditer(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}',text[:usa.start()],re.I))
    return round(st,2),(dates[-1].group(0) if dates else None),url

def latest_value(rows,key):
    for r in reversed(rows):
        if r.get(key) is not None:return float(r[key])
    return None
def hist_change(rows,key,days):
    cur=latest_value(rows,key)
    if cur is None:return None
    target=datetime.now(SEOUL).date()-timedelta(days=days); candidates=[]
    for r in rows:
        try:dt=datetime.fromisoformat(r['date']).date()
        except:continue
        if r.get(key) is not None and dt<=target:candidates.append((dt,float(r[key])))
    return None if not candidates else pct(cur,max(candidates,key=lambda x:x[0])[1])
def merge_today(rows,snap):
    by={r['date']:dict(r) for r in rows if r.get('date')}; cur=by.get(snap['date'],{'date':snap['date']});cur.update(snap);by[snap['date']]=cur
    return [by[d] for d in sorted(by)]

def shale_cycle(cfg, hist_rows):
    s=cfg.get('shale_cycle',{}); duc=s.get('PERMIAN_DUC'); comps=s.get('PERMIAN_MONTHLY_COMPLETIONS'); cover=round(duc/comps,2) if duc and comps else None
    old_duc=None
    for r in reversed(hist_rows):
        if r.get('PERMIAN_DUC') is not None and r.get('PERMIAN_DUC')!=duc: old_duc=float(r['PERMIAN_DUC']);break
    duc_ch=pct(duc,old_duc) if duc and old_duc else None
    pricing=str(s.get('PTEN_COMPLETION_PRICING','UNKNOWN')).upper()
    signals={
      'DUC Pressure': 80 if cover is not None and cover<2 else (65 if cover is not None and cover<2.5 else 50),
      'HP Rig Tightness': 85 if (s.get('HP_SUPERSPEC_UTIL') or 0)>=95 else 65,
      'HP Pricing': 80 if (s.get('HP_MARGIN_DAY') or 0)>=18500 else 60,
      'PTEN Completion': 80 if pricing in ('IMPROVING','UP','STRONG') else (50 if pricing in ('FLAT','STABLE') else 35)
    }
    score=round(sum(signals.values())/len(signals)); label='SHALE CYCLE CONFIRMED' if score>=78 else ('DRILLING TIGHTENING' if score>=65 else 'WATCH')
    return {'signal':label,'score':score,'PERMIAN_DUC':duc,'PERMIAN_COMPLETIONS':comps,'DUC_COVER':cover,'DUC_CHANGE':duc_ch,'PERMIAN_RIGS':s.get('PERMIAN_RIGS'),'FRAC_SPREAD':s.get('FRAC_SPREAD'),'HP_ACTIVE_RIGS':s.get('HP_ACTIVE_RIGS'),'HP_SUPERSPEC_UTIL':s.get('HP_SUPERSPEC_UTIL'),'HP_MARGIN_DAY':s.get('HP_MARGIN_DAY'),'PTEN_DRILLING_RIGS':s.get('PTEN_DRILLING_RIGS'),'PTEN_COMPLETION_GP':s.get('PTEN_COMPLETION_GP'),'PTEN_COMPLETION_PRICING':pricing,'components':signals,'as_of':s.get('AS_OF',{})}

def update():
    d=load(DATA);c=load(CONFIG);hist=load(HISTORY,{'snapshots':[]});errs=[];d['meta']['version']='v5.3'
    market_map={'WTI':'CL=F','BRENT':'BZ=F','USDKRW':'KRW=X'}
    for key,ticker in market_map.items():
        try:
            cur,w,m=latest(ticker);d['market'][key].update(value=round(cur,2),change_1w=w,change_1m=m,score=oil_score(cur) if key!='USDKRW' else fx_score(cur))
        except Exception as e:errs.append(f'{key}: {e}')
    try:hist['snapshots']=merge_market_history(hist.setdefault('snapshots',[]),market_map)
    except Exception as e:errs.append(f'Market history: {e}')
    for name,ticker in c['tickers'].items():
        try:cur,w,m=latest(ticker);d['stocks'][name]={'ticker':ticker,'price':round(cur,0),'change_1w':w,'change_1m':m}
        except Exception as e:errs.append(f'{name}: {e}')
    try:
        txt=requests.get('https://rigcount.bakerhughes.com/',timeout=20,headers={'User-Agent':'Mozilla/5.0'}).text;m=re.search(r'U\.?S\.?\s+Rig\s+Count[^0-9]{0,60}([0-9]{3,4})',txt,re.I)
        if m:
            cur=int(m.group(1));old=d['market']['US_RIGS']['value'];d['market']['US_RIGS'].update(value=cur,change_1w=cur-int(old),score=int(clamp(55+(cur-500)/3)))
    except Exception as e:errs.append(f'Rig Count: {e}')
    mi=c['manual_inputs']
    try:hrc,hd,hu=fetch_steelbenchmarker_hrc();d['market']['US_HRC'].update(value=hrc,score=hrc_cost_score(hrc),manual=False,source='SteelBenchmarker',source_date=hd,source_url=hu)
    except Exception as e:hrc=float(mi['US_HRC']);d['market']['US_HRC'].update(value=hrc,score=hrc_cost_score(hrc),manual=True,source='config.json fallback',source_date=None);errs.append(f'HRC auto: {e}')
    octg=float(mi['US_OCTG']);d['market']['US_OCTG'].update(value=octg,manual=True,source='config.json');spread=octg-hrc;d['market']['OCTG_HRC_SPREAD']['value']=round(spread,2);d['market']['OCTG_HRC_SPREAD']['score']=int(clamp(45+spread/25))
    octg_spread=round((d['market']['US_OCTG']['score']+d['market']['OCTG_HRC_SPREAD']['score'])/2);rig=round((d['market']['US_RIGS']['score']+d['market']['OIL_RIGS']['score'])/2);oil=round((d['market']['WTI']['score']+d['market']['BRENT']['score'])/2)
    comp={'OCTG/Spread':{'weight':35,'score':octg_spread},'Rig Count':{'weight':20,'score':rig},'Oil':{'weight':10,'score':oil},'HRC Cost':{'weight':10,'score':d['market']['US_HRC']['score']},'Export':{'weight':10,'score':int(mi['EXPORT_SCORE'])},'US Policy':{'weight':10,'score':int(mi['US_POLICY_SCORE'])},'FX':{'weight':5,'score':d['market']['USDKRW']['score']}}
    total=round(sum(v['weight']*v['score'] for v in comp.values())/100);rows=hist.setdefault('snapshots',[]);score_rows=[r for r in rows if r.get('PIPE_SCORE') is not None];prev=score_rows[-1]['PIPE_SCORE'] if score_rows else total;trend='BULLISH' if total>=70 else ('NEUTRAL' if total>=55 else 'BEARISH');trend+=' · IMPROVING' if total>prev else (' · WEAKENING' if total<prev else ' · FLAT');d['score']={'pipe_cycle':total,'trend':trend,'components':comp}
    shale=shale_cycle(c,rows);d['shale_cycle']=shale
    today=datetime.now(SEOUL).date().isoformat();snap={'date':today,'PIPE_SCORE':total,'PERMIAN_DUC':shale['PERMIAN_DUC'],'DUC_COVER':shale['DUC_COVER'],'HP_MARGIN_DAY':shale['HP_MARGIN_DAY'],'HP_ACTIVE_RIGS':shale['HP_ACTIVE_RIGS'],'PTEN_COMPLETION_GP':shale['PTEN_COMPLETION_GP']}
    for key in ['WTI','BRENT','USDKRW','US_RIGS','OIL_RIGS','US_HRC','US_OCTG','OCTG_HRC_SPREAD']:snap[key]=d['market'][key]['value']
    hist['snapshots']=merge_today(rows,snap)[-730:];save(HISTORY,hist)
    for key in ['US_HRC','US_OCTG','OCTG_HRC_SPREAD']:
        ch=hist_change(hist['snapshots'],key,28)
        if ch is not None:d['market'][key]['change_1m']=ch
    recent=[r for r in hist['snapshots'] if r.get('PIPE_SCORE') is not None][-13:];d['history']={'pipe_score':[r['PIPE_SCORE'] for r in recent],'labels':[r['date'][5:] for r in recent]}
    d['meta'].update(last_updated=datetime.now(SEOUL).isoformat(timespec='seconds'),mode='v5.3 market history + US Shale Cycle + auto HRC + manual OCTG',errors=errs);save(DATA,d);print('UPDATED',d['meta']['last_updated'],'pipe',total,'shale',shale['score'])
if __name__=='__main__':update()
