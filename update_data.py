from __future__ import annotations
import json, re
from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urljoin
import pandas as pd
import requests
import yfinance as yf
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data.json'; CONFIG=ROOT/'config.json'; HISTORY=ROOT/'history.json'; SEOUL=ZoneInfo('Asia/Seoul')
UA={'User-Agent':'Mozilla/5.0 pipe-investment-dashboard/5.4'}

def load(p, default=None):
    if not p.exists(): return default
    return json.loads(p.read_text(encoding='utf-8'))
def save(p,o): p.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8')
def clamp(v): return max(0,min(100,v))
def pct(a,b): return None if b in (None,0) else round((a/b-1)*100,2)
def clean_text(html): return re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',html)).replace('&nbsp;',' ').replace('&#36;','$')

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
    url='https://steelbenchmarker.com/history.pdf'; r=requests.get(url,timeout=30,headers=UA); r.raise_for_status()
    if not r.content.startswith(b'%PDF'): raise RuntimeError('SteelBenchmarker did not return PDF')
    text='\n'.join((p.extract_text() or '') for p in PdfReader(BytesIO(r.content)).pages[:6]); text=re.sub(r'\s+',' ',text)
    pos=re.search(r'Region:\s*USA',text,re.I)
    if not pos: raise RuntimeError('USA section not found')
    m=re.search(r'Hot[- ]rolled band:\s*([0-9,]+)(?:\s*\(([0-9,]+)\))?',text[pos.start():pos.start()+1800],re.I)
    if not m: raise RuntimeError('USA HRC not found')
    metric=float(m.group(1).replace(',','')); st=float(m.group(2).replace(',','')) if m.group(2) else round(metric/1.10231131)
    dates=list(re.finditer(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}',text[:pos.start()],re.I))
    return round(st,2),(dates[-1].group(0) if dates else None),url

def fetch_baker_hughes():
    page='https://rigcount.bakerhughes.com/na-rig-count/'
    html=requests.get(page,timeout=30,headers=UA).text
    links=re.findall(r'href=["\']([^"\']*static-files/[^"\']+)["\']',html,re.I)
    if not links: raise RuntimeError('latest Baker Hughes xlsx link not found')
    url=urljoin(page,links[0]); r=requests.get(url,timeout=40,headers=UA); r.raise_for_status()
    xls=pd.ExcelFile(BytesIO(r.content))
    best=None
    for sheet in xls.sheet_names:
        raw=pd.read_excel(xls,sheet_name=sheet,header=None)
        for hr in range(min(30,len(raw))):
            vals=[str(x).strip() for x in raw.iloc[hr].tolist()]
            joined=' | '.join(vals).lower()
            if 'country' in joined and ('rig count value' in joined or 'drill for' in joined) and 'basin' in joined:
                df=pd.read_excel(xls,sheet_name=sheet,header=hr)
                df.columns=[re.sub(r'\s+',' ',str(c)).strip() for c in df.columns]
                low={c.lower():c for c in df.columns}
                def col(*names):
                    for n in names:
                        for k,v in low.items():
                            if n in k:return v
                country=col('country'); basin=col('basin'); drill=col('drill for'); val=col('rig count value','rig count'); dtc=col('us_publishdate','publishdate','publish date')
                if all([country,basin,drill,val,dtc]): best=(df,country,basin,drill,val,dtc,url); break
        if best: break
    if not best: raise RuntimeError('Baker Hughes detail table not found')
    df,country,basin,drill,val,dtc,url=best
    df[dtc]=pd.to_datetime(df[dtc],errors='coerce'); df[val]=pd.to_numeric(df[val],errors='coerce')
    us=df[df[country].astype(str).str.upper().isin(['USA','US','U.S.','UNITED STATES'])].copy()
    if us.empty: us=df[df[country].astype(str).str.contains('UNITED STATES|USA',case=False,na=False)].copy()
    latest_dt=us[dtc].max(); cur=us[us[dtc]==latest_dt]
    total=int(round(cur[val].sum()))
    oil=int(round(cur[cur[drill].astype(str).str.contains('oil',case=False,na=False)][val].sum()))
    perm=int(round(cur[cur[basin].astype(str).str.contains('permian',case=False,na=False)][val].sum()))
    return {'US_RIGS':total,'OIL_RIGS':oil,'PERMIAN_RIGS':perm,'date':latest_dt.date().isoformat(),'source':url}

def fetch_eia_steo():
    url='https://api.eia.gov/v2/steo/data/'
    params=[('api_key','DEMO_KEY'),('frequency','quarterly'),('data[0]','value'),('facets[seriesId][]','DUCSPM'),('facets[seriesId][]','NWCPM'),('facets[seriesId][]','RIGSPM'),('sort[0][column]','period'),('sort[0][direction]','desc'),('offset','0'),('length','24')]
    r=requests.get(url,params=params,timeout=30,headers=UA); r.raise_for_status(); js=r.json()
    rows=js.get('response',{}).get('data',[])
    if not rows: raise RuntimeError('EIA STEO returned no data')
    out={}
    ids={'DUCSPM':'PERMIAN_DUC','NWCPM':'PERMIAN_COMPLETIONS_Q','RIGSPM':'PERMIAN_RIGS_Q'}
    for sid,key in ids.items():
        series=[x for x in rows if x.get('seriesId')==sid and x.get('value') not in (None,'')]
        if not series: continue
        series.sort(key=lambda x:x.get('period',''),reverse=True)
        out[key]=float(series[0]['value']); out[key+'_PERIOD']=series[0].get('period')
    if 'PERMIAN_DUC' not in out or 'PERMIAN_COMPLETIONS_Q' not in out: raise RuntimeError('EIA key series missing')
    out['PERMIAN_MONTHLY_COMPLETIONS']=round(out['PERMIAN_COMPLETIONS_Q']/3,2)
    out['source']=r.url
    return out

def discover_release(list_url, domain, needle):
    html=requests.get(list_url,timeout=30,headers=UA).text
    hrefs=re.findall(r'href=["\']([^"\']+)["\']',html,re.I)
    cand=[]
    for h in hrefs:
        u=urljoin(domain,h)
        if '/news-details/20' in u and needle.lower() in u.lower(): cand.append(u)
    if not cand: raise RuntimeError('earnings release link not found')
    return cand[0]

def fetch_hp_metrics():
    try: url=discover_release('https://ir.hpinc.com/news/press-releases/default.aspx','https://ir.hpinc.com/','results')
    except: url='https://ir.hpinc.com/news/press-releases/news-details/2026/Helmerich--Payne-Inc--Announces-Fiscal-Third-Quarter-Results/default.aspx'
    html=requests.get(url,timeout=30,headers=UA).text; text=clean_text(html)
    m1=re.search(r'direct margins? averaged\s*\$?([0-9,]+)\s*with\s*([0-9,]+)\s*rigs?\s+active',text,re.I)
    if not m1:
        m1=re.search(r'per[- ]day basis direct margins? averaged\s*\$?([0-9,]+).*?with\s*([0-9,]+)\s*rigs?\s+active',text,re.I)
    if not m1: raise RuntimeError('HP margin/day + active rigs not found')
    return {'HP_MARGIN_DAY':int(m1.group(1).replace(',','')),'HP_ACTIVE_RIGS':int(m1.group(2).replace(',','')),'source':url}

def fetch_pten_metrics():
    try: url=discover_release('https://investor.patenergy.com/Investors/News-and-Events/news/default.aspx','https://investor.patenergy.com/','financial-results')
    except: url='https://investor.patenergy.com/Investors/News-and-Events/news/news-details/2026/Patterson-UTI-Energy-Reports-Financial-Results-for-the-Quarter-Ended-June-30-2026-/default.aspx'
    html=requests.get(url,timeout=30,headers=UA).text; text=clean_text(html)
    m=re.search(r'Completion Services revenue totaled\s*\$?([0-9,.]+)\s*million,?\s*with adjusted gross profit of\s*\$?([0-9,.]+)\s*million',text,re.I)
    if not m:
        m=re.search(r'Completion Services.*?Adjusted gross profit[^$]{0,60}\$\s*([0-9,]+)',text,re.I)
        if not m: raise RuntimeError('PTEN completion GP not found')
        gp=round(float(m.group(1).replace(',',''))/1000,1)
    else: gp=float(m.group(2).replace(',',''))
    return {'PTEN_COMPLETION_GP':gp,'source':url}

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

def shale_cycle(cfg, hist_rows, live, sources):
    s=cfg.get('shale_cycle',{}); get=lambda k: live.get(k,s.get(k))
    duc=get('PERMIAN_DUC'); comps=get('PERMIAN_MONTHLY_COMPLETIONS'); cover=round(float(duc)/float(comps),2) if duc and comps else None
    old_duc=None
    for r in reversed(hist_rows):
        if r.get('PERMIAN_DUC') is not None and r.get('PERMIAN_DUC')!=duc: old_duc=float(r['PERMIAN_DUC']);break
    duc_ch=pct(float(duc),old_duc) if duc and old_duc else None
    pricing=str(s.get('PTEN_COMPLETION_PRICING','UNKNOWN')).upper()
    signals={'DUC Pressure':80 if cover is not None and cover<2 else (65 if cover is not None and cover<2.5 else 50),'HP Rig Tightness':85 if (get('HP_SUPERSPEC_UTIL') or 0)>=95 else 65,'HP Pricing':80 if (get('HP_MARGIN_DAY') or 0)>=18500 else 60,'PTEN Completion':80 if pricing in ('IMPROVING','UP','STRONG') else (50 if pricing in ('FLAT','STABLE') else 35)}
    score=round(sum(signals.values())/len(signals)); label='SHALE CYCLE CONFIRMED' if score>=78 else ('DRILLING TIGHTENING' if score>=65 else 'WATCH')
    return {'signal':label,'score':score,'PERMIAN_DUC':duc,'PERMIAN_COMPLETIONS':comps,'DUC_COVER':cover,'DUC_CHANGE':duc_ch,'PERMIAN_RIGS':get('PERMIAN_RIGS'),'FRAC_SPREAD':s.get('FRAC_SPREAD'),'HP_ACTIVE_RIGS':get('HP_ACTIVE_RIGS'),'HP_SUPERSPEC_UTIL':s.get('HP_SUPERSPEC_UTIL'),'HP_MARGIN_DAY':get('HP_MARGIN_DAY'),'PTEN_DRILLING_RIGS':s.get('PTEN_DRILLING_RIGS'),'PTEN_COMPLETION_GP':get('PTEN_COMPLETION_GP'),'PTEN_COMPLETION_PRICING':pricing,'components':signals,'sources':sources,'as_of':s.get('AS_OF',{})}

def update():
    d=load(DATA);c=load(CONFIG);hist=load(HISTORY,{'snapshots':[]});errs=[];d['meta']['version']='v5.4'; live={}; sources={}
    market_map={'WTI':'CL=F','BRENT':'BZ=F','USDKRW':'KRW=X'}
    for key,ticker in market_map.items():
        try:cur,w,m=latest(ticker);d['market'][key].update(value=round(cur,2),change_1w=w,change_1m=m,score=oil_score(cur) if key!='USDKRW' else fx_score(cur),manual=False)
        except Exception as e:errs.append(f'{key}: {e}')
    try:hist['snapshots']=merge_market_history(hist.setdefault('snapshots',[]),market_map)
    except Exception as e:errs.append(f'Market history: {e}')
    for name,ticker in c['tickers'].items():
        try:cur,w,m=latest(ticker);d['stocks'][name]={'ticker':ticker,'price':round(cur,0),'change_1w':w,'change_1m':m}
        except Exception as e:errs.append(f'{name}: {e}')
    try:
        bh=fetch_baker_hughes(); sources['Baker Hughes']={'status':'AUTO','date':bh['date'],'url':bh['source']}
        for key in ['US_RIGS','OIL_RIGS']:
            old=d['market'][key]['value']; cur=bh[key]; d['market'][key].update(value=cur,change_1w=cur-int(old),manual=False,source='Baker Hughes',source_date=bh['date'])
        live['PERMIAN_RIGS']=bh['PERMIAN_RIGS']
    except Exception as e: errs.append(f'Baker Hughes auto: {e}'); sources['Baker Hughes']={'status':'STALE/FALLBACK'}
    try:
        eia=fetch_eia_steo(); live.update({k:v for k,v in eia.items() if k.startswith('PERMIAN_')}); sources['EIA STEO']={'status':'AUTO','period':eia.get('PERMIAN_DUC_PERIOD'),'url':eia['source']}
    except Exception as e: errs.append(f'EIA STEO auto: {e}'); sources['EIA STEO']={'status':'STALE/FALLBACK'}
    try:
        hp=fetch_hp_metrics();live.update(hp);sources['HP IR']={'status':'AUTO','url':hp['source']}
    except Exception as e: errs.append(f'HP IR auto: {e}');sources['HP IR']={'status':'STALE/FALLBACK'}
    try:
        pt=fetch_pten_metrics();live.update(pt);sources['PTEN IR']={'status':'AUTO','url':pt['source']}
    except Exception as e: errs.append(f'PTEN IR auto: {e}');sources['PTEN IR']={'status':'STALE/FALLBACK'}
    mi=c['manual_inputs']
    try:hrc,hd,hu=fetch_steelbenchmarker_hrc();d['market']['US_HRC'].update(value=hrc,score=hrc_cost_score(hrc),manual=False,source='SteelBenchmarker',source_date=hd,source_url=hu)
    except Exception as e:hrc=float(mi['US_HRC']);d['market']['US_HRC'].update(value=hrc,score=hrc_cost_score(hrc),manual=True,source='config.json fallback',source_date=None);errs.append(f'HRC auto: {e}')
    octg=float(mi['US_OCTG']);d['market']['US_OCTG'].update(value=octg,manual=True,source='config.json');spread=octg-hrc;d['market']['OCTG_HRC_SPREAD']['value']=round(spread,2);d['market']['OCTG_HRC_SPREAD']['score']=int(clamp(45+spread/25))
    octg_spread=round((d['market']['US_OCTG']['score']+d['market']['OCTG_HRC_SPREAD']['score'])/2);rig=round((d['market']['US_RIGS']['score']+d['market']['OIL_RIGS']['score'])/2);oil=round((d['market']['WTI']['score']+d['market']['BRENT']['score'])/2)
    comp={'OCTG/Spread':{'weight':35,'score':octg_spread},'Rig Count':{'weight':20,'score':rig},'Oil':{'weight':10,'score':oil},'HRC Cost':{'weight':10,'score':d['market']['US_HRC']['score']},'Export':{'weight':10,'score':int(mi['EXPORT_SCORE'])},'US Policy':{'weight':10,'score':int(mi['US_POLICY_SCORE'])},'FX':{'weight':5,'score':d['market']['USDKRW']['score']}}
    total=round(sum(v['weight']*v['score'] for v in comp.values())/100);rows=hist.setdefault('snapshots',[]);score_rows=[r for r in rows if r.get('PIPE_SCORE') is not None];prev=score_rows[-1]['PIPE_SCORE'] if score_rows else total;trend='BULLISH' if total>=70 else ('NEUTRAL' if total>=55 else 'BEARISH');trend+=' · IMPROVING' if total>prev else (' · WEAKENING' if total<prev else ' · FLAT');d['score']={'pipe_cycle':total,'trend':trend,'components':comp}
    shale=shale_cycle(c,rows,live,sources);d['shale_cycle']=shale
    today=datetime.now(SEOUL).date().isoformat();snap={'date':today,'PIPE_SCORE':total,'PERMIAN_DUC':shale['PERMIAN_DUC'],'PERMIAN_RIGS':shale['PERMIAN_RIGS'],'DUC_COVER':shale['DUC_COVER'],'HP_MARGIN_DAY':shale['HP_MARGIN_DAY'],'HP_ACTIVE_RIGS':shale['HP_ACTIVE_RIGS'],'PTEN_COMPLETION_GP':shale['PTEN_COMPLETION_GP']}
    for key in ['WTI','BRENT','USDKRW','US_RIGS','OIL_RIGS','US_HRC','US_OCTG','OCTG_HRC_SPREAD']:snap[key]=d['market'][key]['value']
    hist['snapshots']=merge_today(rows,snap)[-730:];save(HISTORY,hist)
    for key in ['US_HRC','US_OCTG','OCTG_HRC_SPREAD']:
        ch=hist_change(hist['snapshots'],key,28)
        if ch is not None:d['market'][key]['change_1m']=ch
    recent=[r for r in hist['snapshots'] if r.get('PIPE_SCORE') is not None][-13:];d['history']={'pipe_score':[r['PIPE_SCORE'] for r in recent],'labels':[r['date'][5:] for r in recent]}
    d['meta'].update(last_updated=datetime.now(SEOUL).isoformat(timespec='seconds'),mode='v5.4 automated public shale metrics + market history + auto HRC + manual OCTG/FSC/qualitative call items',errors=errs);save(DATA,d);print('UPDATED',d['meta']['last_updated'],'pipe',total,'shale',shale['score'],'errors',len(errs))
if __name__=='__main__':update()
