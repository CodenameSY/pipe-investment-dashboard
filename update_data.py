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
UA={'User-Agent':'Mozilla/5.0 pipe-investment-dashboard/5.7'}

def load(p, default=None): return default if not p.exists() else json.loads(p.read_text(encoding='utf-8'))
def save(p,o): p.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8')
def clamp(v): return max(0,min(100,v))
def pct(a,b): return None if b in (None,0,'') or a in (None,'') else round((float(a)/float(b)-1)*100,2)
def clean_text(html): return re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',html)).replace('&nbsp;',' ')
def latest_from_history(rows,key):
    for r in reversed(rows or []):
        if r.get(key) not in (None,''): return r.get(key)
    return None
def status_source(src,key,status,date=None,url=None,error=None): src[key]={'status':status,'date':date,'url':url,'error':str(error)[:220] if error else None}

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
    url='https://steelbenchmarker.com/history.pdf'; r=requests.get(url,timeout=(8,35),headers=UA); r.raise_for_status()
    if not r.content.startswith(b'%PDF'): raise RuntimeError('SteelBenchmarker did not return PDF')
    text='\n'.join((p.extract_text() or '') for p in PdfReader(BytesIO(r.content)).pages[:6]); text=re.sub(r'\s+',' ',text)
    pos=re.search(r'Region:\s*USA',text,re.I)
    if not pos: raise RuntimeError('USA section not found')
    m=re.search(r'Hot[- ]rolled band:\s*([0-9,]+)(?:\s*\(([0-9,]+)\))?',text[pos.start():pos.start()+1800],re.I)
    if not m: raise RuntimeError('USA HRC not found')
    metric=float(m.group(1).replace(',','')); st=float(m.group(2).replace(',','')) if m.group(2) else round(metric/1.10231131)
    dates=list(re.finditer(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}',text[:pos.start()],re.I))
    return round(st,2),(dates[-1].group(0) if dates else None),url

def fetch_aogr_us_rigs():
    url='https://www.aogr.com/web-exclusives/us-rig-count/2026'
    text=clean_text(requests.get(url,timeout=(8,30),headers=UA).text)
    pat=r'(\d{2}/\d{2}/2026).*?Total Rigs 2026\s*\(Wk\./Wk\.\)\s*([+\-]?\d+)\s*(\d{3,4}).*?Oil\s*\(Wk\./Wk\.\)\s*([+\-]?\d+)\s*\((\d{3,4})\)'
    ms=re.findall(pat,text,re.I|re.S)
    if not ms: raise RuntimeError('AOGR rig table parse failed')
    date,total_ch,total,oil_ch,oil=ms[0]
    dt=datetime.strptime(date,'%m/%d/%Y').date().isoformat()
    return {'US_RIGS':int(total),'OIL_RIGS':int(oil),'date':dt,'source':url}

def fetch_oilpriceapi_permian():
    url='https://www.oilpriceapi.com/data/rig-count/permian'
    text=clean_text(requests.get(url,timeout=(8,25),headers=UA).text)
    m=re.search(r'Permian Basin Rig Count\s+[^0-9]{0,40}\s+to\s+(\d{2,4}).*?As of\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})',text,re.I|re.S)
    if not m:
        m=re.search(r'(\d{2,4})\s+Active Rigs.*?As of\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})',text,re.I|re.S)
    if not m: raise RuntimeError('OilPriceAPI Permian page parse failed')
    dt=datetime.strptime(m.group(2),'%B %d, %Y').date().isoformat()
    return {'PERMIAN_RIGS':int(m.group(1)),'date':dt,'source':url}

def fetch_eia_steo():
    url='https://api.eia.gov/v2/steo/data/'
    params=[('api_key','DEMO_KEY'),('frequency','quarterly'),('data[0]','value'),('facets[seriesId][]','DUCSPM'),('facets[seriesId][]','NWCPM'),('facets[seriesId][]','RIGSPM'),('sort[0][column]','period'),('sort[0][direction]','desc'),('offset','0'),('length','24')]
    r=requests.get(url,params=params,timeout=(8,35),headers=UA); r.raise_for_status(); rows=r.json().get('response',{}).get('data',[])
    if not rows: raise RuntimeError('EIA STEO returned no data')
    out={}; ids={'DUCSPM':'PERMIAN_DUC','NWCPM':'PERMIAN_COMPLETIONS_Q','RIGSPM':'PERMIAN_RIGS_Q'}
    for sid,key in ids.items():
        series=[x for x in rows if x.get('seriesId')==sid and x.get('value') not in (None,'')]
        if series:
            series.sort(key=lambda x:x.get('period',''),reverse=True); out[key]=float(series[0]['value']); out[key+'_PERIOD']=series[0].get('period')
    if 'PERMIAN_DUC' not in out or 'PERMIAN_COMPLETIONS_Q' not in out: raise RuntimeError('EIA key series missing')
    out['PERMIAN_MONTHLY_COMPLETIONS']=round(out['PERMIAN_COMPLETIONS_Q']/3,2); out['source']=r.url
    return out

def discover_release(list_url, domain, needle):
    html=requests.get(list_url,timeout=(5,20),headers=UA).text
    cand=[]
    for h in re.findall(r'href=["\']([^"\']+)["\']',html,re.I):
        u=urljoin(domain,h)
        if '/news-details/20' in u and needle.lower() in u.lower(): cand.append(u)
    if not cand: raise RuntimeError('release link not found')
    return cand[0]
def fetch_hp_metrics():
    try: url=discover_release('https://ir.hpinc.com/news/press-releases/default.aspx','https://ir.hpinc.com/','results')
    except Exception: url='https://ir.hpinc.com/news/press-releases/news-details/2026/Helmerich--Payne-Inc--Announces-Fiscal-Third-Quarter-Results/default.aspx'
    text=clean_text(requests.get(url,timeout=(5,25),headers=UA).text)
    m=re.search(r'direct margins? averaged\s*\$?([0-9,]+)\s*with\s*([0-9,]+)\s*rigs?\s+active',text,re.I) or re.search(r'per[- ]day basis direct margins? averaged\s*\$?([0-9,]+).*?with\s*([0-9,]+)\s*rigs?\s+active',text,re.I)
    if not m: raise RuntimeError('HP margin/day + active rigs not found')
    return {'HP_MARGIN_DAY':int(m.group(1).replace(',','')),'HP_ACTIVE_RIGS':int(m.group(2).replace(',','')),'source':url}
def fetch_pten_metrics():
    try: url=discover_release('https://investor.patenergy.com/Investors/News-and-Events/news/default.aspx','https://investor.patenergy.com/','financial-results')
    except Exception: url='https://investor.patenergy.com/Investors/News-and-Events/news/news-details/2026/Patterson-UTI-Energy-Reports-Financial-Results-for-the-Quarter-Ended-June-30-2026-/default.aspx'
    text=clean_text(requests.get(url,timeout=(5,25),headers=UA).text)
    m=re.search(r'Completion Services revenue totaled\s*\$?([0-9,.]+)\s*million,?\s*with adjusted gross profit of\s*\$?([0-9,.]+)\s*million',text,re.I) or re.search(r'Completion Services.*?Adjusted gross profit[^$]{0,60}\$\s*([0-9,]+)',text,re.I)
    if not m: raise RuntimeError('PTEN completion GP not found')
    gp=float(m.group(2).replace(',','')) if len(m.groups())>1 and m.group(2) else round(float(m.group(1).replace(',',''))/1000,1)
    return {'PTEN_COMPLETION_GP':gp,'source':url}

def hist_change(rows,key,days):
    cur=latest_from_history(rows,key)
    if cur is None:return None
    target=datetime.now(SEOUL).date()-timedelta(days=days); cand=[]
    for r in rows:
        try:dt=datetime.fromisoformat(r['date']).date()
        except Exception:continue
        if r.get(key) is not None and dt<=target:cand.append((dt,float(r[key])))
    return None if not cand else pct(float(cur),max(cand,key=lambda x:x[0])[1])
def merge_today(rows,snap):
    by={r['date']:dict(r) for r in rows if r.get('date')}; by.setdefault(snap['date'],{'date':snap['date']}).update(snap)
    return [by[d] for d in sorted(by)]

def shale_cycle(cfg,hist_rows,live,sources):
    s=cfg.get('shale_cycle',{}); get=lambda k: live.get(k, latest_from_history(hist_rows,k) if latest_from_history(hist_rows,k) is not None else s.get(k))
    duc=get('PERMIAN_DUC'); comps=get('PERMIAN_MONTHLY_COMPLETIONS'); cover=round(float(duc)/float(comps),2) if duc and comps else None
    old_duc=None
    for r in reversed(hist_rows):
        if r.get('PERMIAN_DUC') is not None and r.get('PERMIAN_DUC')!=duc: old_duc=float(r['PERMIAN_DUC']); break
    pricing=str(s.get('PTEN_COMPLETION_PRICING','UNKNOWN')).upper()
    signals={'DUC Pressure':80 if cover is not None and cover<2 else (65 if cover is not None and cover<2.5 else 50),'HP Rig Tightness':85 if (get('HP_SUPERSPEC_UTIL') or 0)>=95 else 65,'HP Pricing':80 if (get('HP_MARGIN_DAY') or 0)>=18500 else 60,'PTEN Completion':80 if pricing in ('IMPROVING','UP','STRONG') else (50 if pricing in ('FLAT','STABLE') else 35)}
    score=round(sum(signals.values())/len(signals)); label='SHALE CYCLE CONFIRMED' if score>=78 else ('DRILLING TIGHTENING' if score>=65 else 'WATCH')
    return {'signal':label,'score':score,'PERMIAN_DUC':duc,'PERMIAN_COMPLETIONS':comps,'PERMIAN_COMPLETIONS_Q':get('PERMIAN_COMPLETIONS_Q'),'DUC_COVER':cover,'DUC_CHANGE':pct(float(duc),old_duc) if duc and old_duc else None,'PERMIAN_RIGS':get('PERMIAN_RIGS'),'FRAC_SPREAD':s.get('FRAC_SPREAD'),'HP_ACTIVE_RIGS':get('HP_ACTIVE_RIGS'),'HP_SUPERSPEC_UTIL':s.get('HP_SUPERSPEC_UTIL'),'HP_MARGIN_DAY':get('HP_MARGIN_DAY'),'PTEN_DRILLING_RIGS':s.get('PTEN_DRILLING_RIGS'),'PTEN_COMPLETION_GP':get('PTEN_COMPLETION_GP'),'PTEN_COMPLETION_PRICING':pricing,'components':signals,'sources':sources,'as_of':s.get('AS_OF',{})}

def update():
    d=load(DATA); c=load(CONFIG); hist=load(HISTORY,{'snapshots':[]}); rows=hist.setdefault('snapshots',[]); errs=[]; live={}; sources={}
    d.setdefault('meta',{})['version']='v5.7'
    for key,ticker in {'WTI':'CL=F','BRENT':'BZ=F','USDKRW':'KRW=X'}.items():
        try:
            cur,w,m=latest(ticker); d['market'][key].update(value=round(cur,2),change_1w=w,change_1m=m,score=oil_score(cur) if key!='USDKRW' else fx_score(cur),manual=False,source='Yahoo Finance')
            status_source(sources,key,'AUTO',datetime.now(SEOUL).date().isoformat(),'Yahoo Finance')
        except Exception as e: errs.append(f'{key}: {e}'); status_source(sources,key,'STALE/FALLBACK',error=e)
    try: hist['snapshots']=merge_market_history(rows,{'WTI':'CL=F','BRENT':'BZ=F','USDKRW':'KRW=X'}); rows=hist['snapshots']
    except Exception as e: errs.append(f'Market history: {e}')
    for name,ticker in c['tickers'].items():
        try: cur,w,m=latest(ticker); d['stocks'][name]={'ticker':ticker,'price':round(cur,0),'change_1w':w,'change_1m':m}
        except Exception as e: errs.append(f'{name}: {e}')
    try:
        rig=fetch_aogr_us_rigs()
        for key in ['US_RIGS','OIL_RIGS']:
            old=d['market'][key].get('value') or rig[key]; cur=rig[key]
            d['market'][key].update(value=cur,change_1w=cur-int(old),manual=False,source='AOGR / Baker Hughes data',source_date=rig['date'])
        status_source(sources,'Rig Count','AUTO',rig['date'],rig['source'])
    except Exception as e:
        errs.append(f'Rig count mirror auto: {e}'); status_source(sources,'Rig Count','STALE/FALLBACK',error=e)
    try:
        perm=fetch_oilpriceapi_permian(); live['PERMIAN_RIGS']=perm['PERMIAN_RIGS']; status_source(sources,'Permian Rig Count','AUTO',perm['date'],perm['source'])
    except Exception as e:
        errs.append(f'Permian rig mirror auto: {e}'); status_source(sources,'Permian Rig Count','STALE/FALLBACK',error=e)
    try:
        eia=fetch_eia_steo(); live.update({k:v for k,v in eia.items() if k.startswith('PERMIAN_')}); status_source(sources,'EIA STEO','AUTO',eia.get('PERMIAN_DUC_PERIOD'),eia['source'])
        if live.get('PERMIAN_RIGS') in (None,'') and eia.get('PERMIAN_RIGS_Q') is not None:
            live['PERMIAN_RIGS']=round(eia['PERMIAN_RIGS_Q']); status_source(sources,'Permian Rigs Fallback','AUTO',eia.get('PERMIAN_RIGS_Q_PERIOD'),eia['source'])
    except Exception as e: errs.append(f'EIA STEO auto: {e}'); status_source(sources,'EIA STEO','STALE/FALLBACK',error=e)
    try: hp=fetch_hp_metrics(); live.update(hp); status_source(sources,'HP IR','AUTO',url=hp['source'])
    except Exception as e: errs.append(f'HP IR auto: {e}'); status_source(sources,'HP IR','STALE/FALLBACK',error=e)
    try: pt=fetch_pten_metrics(); live.update(pt); status_source(sources,'PTEN IR','AUTO',url=pt['source'])
    except Exception as e: errs.append(f'PTEN IR auto: {e}'); status_source(sources,'PTEN IR','STALE/FALLBACK',error=e)
    mi=c['manual_inputs']
    try:
        hrc,hd,hu=fetch_steelbenchmarker_hrc(); d['market']['US_HRC'].update(value=hrc,score=hrc_cost_score(hrc),manual=False,source='SteelBenchmarker',source_date=hd,source_url=hu); status_source(sources,'SteelBenchmarker HRC','AUTO',hd,hu)
    except Exception as e:
        hrc=float(mi['US_HRC']); d['market']['US_HRC'].update(value=hrc,score=hrc_cost_score(hrc),manual=True,source='config.json fallback',source_date=None); errs.append(f'HRC auto: {e}'); status_source(sources,'SteelBenchmarker HRC','STALE/FALLBACK',error=e)
    octg=float(mi['US_OCTG']); d['market']['US_OCTG'].update(value=octg,manual=True,source='config.json/manual'); status_source(sources,'US OCTG','MANUAL',url='config.json')
    spread=octg-hrc; d['market']['OCTG_HRC_SPREAD']['value']=round(spread,2); d['market']['OCTG_HRC_SPREAD']['score']=int(clamp(45+spread/25))
    octg_spread=round((d['market']['US_OCTG']['score']+d['market']['OCTG_HRC_SPREAD']['score'])/2); rigscore=round((d['market']['US_RIGS']['score']+d['market']['OIL_RIGS']['score'])/2); oil=round((d['market']['WTI']['score']+d['market']['BRENT']['score'])/2)
    comp={'OCTG/Spread':{'weight':35,'score':octg_spread},'Rig Count':{'weight':20,'score':rigscore},'Oil':{'weight':10,'score':oil},'HRC Cost':{'weight':10,'score':d['market']['US_HRC']['score']},'Export':{'weight':10,'score':int(mi['EXPORT_SCORE'])},'US Policy':{'weight':10,'score':int(mi['US_POLICY_SCORE'])},'FX':{'weight':5,'score':d['market']['USDKRW']['score']}}
    total=round(sum(v['weight']*v['score'] for v in comp.values())/100); prev=(latest_from_history(rows,'PIPE_SCORE') or total)
    trend='BULLISH' if total>=70 else ('NEUTRAL' if total>=55 else 'BEARISH'); trend+=' · IMPROVING' if total>prev else (' · WEAKENING' if total<prev else ' · FLAT')
    d['score']={'pipe_cycle':total,'trend':trend,'components':comp}
    shale=shale_cycle(c,rows,live,sources); d['shale_cycle']=shale
    today=datetime.now(SEOUL).date().isoformat(); snap={'date':today,'PIPE_SCORE':total,'PERMIAN_DUC':shale['PERMIAN_DUC'],'PERMIAN_COMPLETIONS_Q':shale.get('PERMIAN_COMPLETIONS_Q'),'PERMIAN_MONTHLY_COMPLETIONS':shale['PERMIAN_COMPLETIONS'],'PERMIAN_RIGS':shale['PERMIAN_RIGS'],'DUC_COVER':shale['DUC_COVER'],'HP_MARGIN_DAY':shale['HP_MARGIN_DAY'],'HP_ACTIVE_RIGS':shale['HP_ACTIVE_RIGS'],'PTEN_COMPLETION_GP':shale['PTEN_COMPLETION_GP']}
    for key in ['WTI','BRENT','USDKRW','US_RIGS','OIL_RIGS','US_HRC','US_OCTG','OCTG_HRC_SPREAD']: snap[key]=d['market'][key]['value']
    hist['snapshots']=merge_today(rows,snap)[-730:]
    for key in ['US_HRC','US_OCTG','OCTG_HRC_SPREAD','OIL_RIGS','US_RIGS']:
        ch=hist_change(hist['snapshots'],key,28)
        if ch is not None and key in d['market']: d['market'][key]['change_1m']=ch
    recent=[r for r in hist['snapshots'] if r.get('PIPE_SCORE') is not None][-13:]; d['history']={'pipe_score':[r['PIPE_SCORE'] for r in recent],'labels':[r['date'][5:] for r in recent]}
    d['meta'].update(last_updated=datetime.now(SEOUL).isoformat(timespec='seconds'),mode='v5.7 rig-count mirror automation + EIA/IR/HRC auto + manual OCTG/FSC/qualitative inputs',errors=errs,source_status=sources)
    save(HISTORY,hist); save(DATA,d)
    print('UPDATED',d['meta']['last_updated'],'pipe',total,'shale',shale['score'],'permian_rigs',shale['PERMIAN_RIGS'],'errors',len(errs))
    if errs: print('ERRORS:', ' | '.join(errs[:5]))
if __name__=='__main__': update()
