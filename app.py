import flask
from flask import Flask, render_template_string
import yfinance as yf
import pandas as pd
import requests
import feedparser
import pandas_datareader.data as web
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import ssl
import io
import time
import cloudscraper
import google.generativeai as genai
import os
import xml.etree.ElementTree as ET
import re

try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

scraper = cloudscraper.create_scraper()
app = Flask(__name__)

def fetch_yfinance_data(tickers):
    data = {}
    tv_map = {'^GSPC':'SPX','^DJI':'DJI','^NDX':'NDX','^SOX':'SOX','^NBI':'NBI','DX-Y.NYB':'DXY','^TNX':'US10Y','^TYX':'US30Y','^VIX':'VIX','CL=F':'USOIL','BZ=F':'UKOIL','KRW=X':'USDKRW','JPY=X':'USDJPY','^N225':'NI225','^TWII':'TAIEX'}
    for name, ticker in tickers.items():
        tv_ticker = tv_map.get(ticker, ticker)
        try:
            hist = yf.Ticker(ticker).history(period="1y")
            if 'Close' in hist.columns and len(hist) >= 2:
                cls, hgh = hist['Close'].dropna(), hist['High'].dropna()
                if len(cls) >= 2:
                    curr, prev = float(cls.iloc[-1]), float(cls.iloc[-2])
                    diff = curr - prev
                    pct = (diff / prev) * 100 if prev != 0 else 0
                    near_52w = curr >= (float(hgh.max()) * 0.97)
                    data[name] = {'value':curr, 'diff':diff, 'pct':pct, 'near_52w_high':near_52w, 'ticker':tv_ticker}
                    continue
            data[name] = {'value':"N/A", 'diff':0, 'pct':0, 'near_52w_high':False, 'ticker':tv_ticker}
        except:
            data[name] = {'value':"N/A", 'diff':0, 'pct':0, 'near_52w_high':False, 'ticker':tv_ticker}
    return data

def get_fear_and_greed():
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    # 깃허브 액션 IP 차단을 막기 위한 프록시 우회 방식 도입
    proxy_url = f"https://api.allorigins.win/raw?url={url}"
    for target in [url, proxy_url]:
        try:
            res = requests.get(target, headers=headers, timeout=10)
            if res.status_code == 200:
                d = res.json()['fear_and_greed']
                scr, prv = d['score'], d['previous_close']
                return {'value':scr, 'diff':scr-prv, 'pct':((scr-prv)/prv)*100 if prv else 0, 'rating':d['rating']}
        except:
            continue
    return {'value': "N/A", 'diff': 0, 'pct': 0, 'rating': "조회불가"}

def get_silver_don_price():
    try:
        si, krw = yf.Ticker("SI=F").history(period="5d")['Close'].dropna(), yf.Ticker("KRW=X").history(period="5d")['Close'].dropna()
        curr, prev = (float(si.iloc[-1])/31.1034)*3.75*float(krw.iloc[-1]), (float(si.iloc[-2])/31.1034)*3.75*float(krw.iloc[-2])
        return {'value': int(curr), 'diff': int(curr-prev), 'pct': ((curr-prev)/prev)*100 if prev else 0, 'ticker': 'XAGUSD'}
    except: return {'value': "N/A", 'diff': 0, 'pct': 0, 'ticker': 'XAGUSD'}

def get_gold_don_price():
    try:
        gc, krw = yf.Ticker("GC=F").history(period="5d")['Close'].dropna(), yf.Ticker("KRW=X").history(period="5d")['Close'].dropna()
        curr, prev = (float(gc.iloc[-1])/31.1034)*3.75*float(krw.iloc[-1]), (float(gc.iloc[-2])/31.1034)*3.75*float(krw.iloc[-2])
        return {'value': int(curr), 'diff': int(curr-prev), 'pct': ((curr-prev)/prev)*100 if prev else 0, 'ticker': 'XAUUSD'}
    except: return {'value': "N/A", 'diff': 0, 'pct': 0, 'ticker': 'XAUUSD'}

def get_copper_krw_price():
    try:
        hg, krw = yf.Ticker("HG=F").history(period="5d")['Close'].dropna(), yf.Ticker("KRW=X").history(period="5d")['Close'].dropna()
        curr, prev = float(hg.iloc[-1])*float(krw.iloc[-1]), float(hg.iloc[-2])*float(krw.iloc[-2])
        return {'value': int(curr), 'diff': int(curr-prev), 'pct': ((curr-prev)/prev)*100 if prev else 0, 'ticker': 'HG1!'}
    except: return {'value': "N/A", 'diff': 0, 'pct': 0, 'ticker': 'HG1!'}

def get_fed_liquidity():
    try:
        end = datetime.today()
        df = web.DataReader(['WALCL', 'WTREGEN', 'RRPONTSYD', 'WRESBAL'], 'fred', end-timedelta(days=60), end).ffill().dropna()
        df.columns = ['Total Assets', 'TGA', 'Reverse Repo', 'Bank Reserves']
        df['Reverse Repo'] *= 1000
        df['Net Liquidity'] = df['Total Assets'] - df['TGA'] - df['Reverse Repo']
        curr, prev = df.iloc[-1], df.iloc[-2]
        return {col: {'value': curr[col], 'diff': curr[col]-prev[col], 'pct': ((curr[col]-prev[col])/prev[col])*100 if prev[col] else 0} for col in df.columns}
    except: return None

def get_google_news():
    try:
        feed = feedparser.parse("https://news.google.com/rss/search?q=미국+증시+OR+연준+OR+빅테크+OR+환율&hl=ko&gl=KR&ceid=KR:ko")
        return [{'title': i.title, 'link': i.link, 'date': datetime.strptime(i.published, '%a, %d %b %Y %H:%M:%S %Z').strftime('%Y-%m-%d %H:%M')} for i in feed.entries[:7]]
    except: return []

def get_economic_calendar():
    dic = {"Core":"근원", "Prelim":"잠정", "Advance":"예비", "Final":"확정", "m/m":"(전월대비)", "y/y":"(전년동기대비)", "q/q":"(전분기대비)", "Fed Chair Powell Speaks":"파월 연준 의장 연설", "FOMC Statement":"FOMC 성명서", "Federal Funds Rate":"미국 기준금리 결정", "Unemployment Claims":"신규 실업수당 청구건수", "Non-Farm Employment Change":"비농업 고용지수", "Unemployment Rate":"실업률", "CPI":"소비자물가지수(CPI)", "PPI":"생산자물가지수(PPI)", "Retail Sales":"소매판매", "Manufacturing PMI":"제조업 PMI", "GDP":"국내총생산(GDP)", "PCE Price Index":"PCE 물가지수", "Average Hourly Earnings":"평균 시간당 임금"}
    try:
        root = ET.fromstring(scraper.get("https://nfs.faireconomy.media/ff_calendar_thisweek.xml", timeout=10).content)
        events = []
        for e in root.findall('event'):
            c, i = e.find('country'), e.find('impact')
            if c is not None and c.text and 'USD' in c.text and i is not None and i.text.strip() in ['High', 'Medium']:
                title, d_str, t_str = e.find('title').text, e.find('date').text, e.find('time').text
                for eng, kor in dic.items(): title = title.replace(eng, kor)
                try:
                    if 'am' in t_str.lower() or 'pm' in t_str.lower():
                        dt = datetime.strptime(f"{d_str} {t_str}", "%m-%d-%Y %I:%M%p").replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Asia/Seoul"))
                        d_out, t_out = dt.strftime("%m월 %d일"), f"{'오전' if dt.hour < 12 else '오후'} {dt.hour % 12 or 12}:{dt.minute:02d}"
                    else: d_out, t_out = d_str, ("종일" if "all day" in t_str.lower() else "시간 미정")
                except: d_out, t_out = d_str, t_str
                events.append({"title": f"{'🔴' if i.text.strip() == 'High' else '🟡'} [{d_out} {t_out}] {title.replace('  ', ' ').strip()}"})
        return events if events else [{"title": "이번 주 남은 주요 지표 없음"}]
    except Exception as e: return [{"title": f"⚠️ 데이터 오류: {str(e)}"}]

def get_ai_summary(data):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key: return "🤖 API 키 미설정"
    try:
        genai.configure(api_key=api_key)
        td = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y년 %m월 %d일")
        f_net = f"{int(data['fed']['Net Liquidity']['value']):,} M$" if data.get('fed') else "N/A"
        f_rrp = f"{int(data['fed']['Reverse Repo']['value']):,} M$" if data.get('fed') else "N/A"
        f_tga = f"{int(data['fed']['TGA']['value']):,} M$" if data.get('fed') else "N/A"
        cnn_v = f"{int(data['cnn']['value'])} ({data['cnn'].get('rating', '')})" if data.get('cnn') and data['cnn'].get('value') != "N/A" else "N/A"
        
        prompt = f"""[{td}] 거시경제 애널리스트로서 아래 데이터를 심층 분석하여 시장 전망을 도출하세요.
[★할루시네이션(거짓 정보) 절대 금지 규칙★]
1. 제공된 데이터 기반으로만 작성. 추측성 예측 금지.
2. 마크다운 기호(*, #, - 등) 절대 사용 금지.
3. 각 문단 앞에 "1. ", "2. ", "3. " 처럼 번호를 매겨서 깔끔하게 요약할 것.
[분석 포인트] 지수(반도체, 니케이, 대만 포함), 외국인 수급(환율/금리), 유동성/투심(VIX, CNN, 연준 순유동성/RRP)
[데이터] S&P500:{data['indices'].get('S&P 500',{}).get('value')} / 나스닥:{data['indices'].get('나스닥 100',{}).get('value')} / 반도체:{data['indices'].get('필라델피아 반도체',{}).get('value')} / 니케이:{data['indices'].get('니케이 225',{}).get('value')} / 대만:{data['indices'].get('대만 가권',{}).get('value')} / 미국채10년:{data['macros'].get('미국채 10년물',{}).get('value')}% / 환율:{data['macros'].get('원/달러 환율',{}).get('value')}원 / VIX:{data['macros'].get('빅스(VIX)',{}).get('value')} / CNN:{cnn_v} / WTI:{data['commodities'].get('WTI유',{}).get('value')} / 순유동성:{f_net} / RRP:{f_rrp} / TGA:{f_tga}"""
        
        for model in ['gemini-3.6-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-flash-lite', 'gemini-1.5-flash']:
            try:
                res = genai.GenerativeModel(model).generate_content(prompt).text
                return re.sub(r'\n\s*\n', '\n\n', res.replace('*', '').replace('#', '').replace('_', '').replace('-', '')).strip()
            except: time.sleep(1)
        return "⚠️ AI 분석 실패 (서버 혼잡)"
    except: return "⚠️ AI 설정 오류"

CACHE = {}

def get_dashboard_data():
    if 'data' in CACHE and time.time() - CACHE['time'] < 600: return CACHE['data']
    d = {
        'indices': fetch_yfinance_data({'S&P 500':'^GSPC','다우존스':'^DJI','나스닥 100':'^NDX','필라델피아 반도체':'^SOX','나스닥 생명공학':'^NBI','니케이 225':'^N225','대만 가권':'^TWII'}),
        'macros': fetch_yfinance_data({'달러 인덱스':'DX-Y.NYB','원/달러 환율':'KRW=X','엔/달러 환율':'JPY=X','미국채 10년물':'^TNX','미국채 30년물':'^TYX','빅스(VIX)':'^VIX'}),
        'cnn': get_fear_and_greed(), 'commodities': fetch_yfinance_data({'WTI유':'CL=F','브렌트유':'BZ=F'}),
        'copper': get_copper_krw_price(), 'silver': get_silver_don_price(), 'gold': get_gold_don_price(), 'fed': get_fed_liquidity(),
        'tech_soft': fetch_yfinance_data({'Apple':'AAPL','Microsoft':'MSFT','Alphabet':'GOOGL','Amazon':'AMZN','Meta':'META','Oracle':'ORCL','크라우드스트라이크':'CRWD','세일스포스':'CRM','넷플릭스':'NFLX'}),
        'semi_ai': fetch_yfinance_data({'NVIDIA':'NVDA','AMD':'AMD','TSMC':'TSM','Micron':'MU','인텔':'INTC','퀄컴':'QCOM','브로드컴':'AVGO','ASML':'ASML','델':'DELL'}),
        'energy_infra': fetch_yfinance_data({'엑슨모빌':'XOM','셰브론':'CVX','GE버노바':'GEV','뉴스케일파워':'SMR','블룸에너지':'BE'}),
        'health': fetch_yfinance_data({'Eli Lilly':'LLY','화이자':'PFE','존슨앤드존슨':'JNJ','유나이티드헬스':'UNH','모더나':'MRNA','암젠':'AMGN'}),
        'space_mobility': fetch_yfinance_data({'Tesla':'TSLA','로켓랩':'RKLB','GE에어로스페이스':'GE'}),
        'finance': fetch_yfinance_data({'JP모건':'JPM','뱅크오브아메리카':'BAC','웰스파고':'WFC','비자':'V','버크셔':'BRK-B'}),
        'consumer': fetch_yfinance_data({'월마트':'WMT','코스트코':'COST','코카콜라':'KO','맥도날드':'MCD'}),
        'news': get_google_news(), 'calendar': get_economic_calendar()
    }
    d['ai_summary'] = get_ai_summary(d)
    CACHE['data'], CACHE['time'] = d, time.time()
    return d

HTML_TEMPLATE = """<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>미국 증시 대시보드</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css" /><style>body{font-family:'Pretendard',sans-serif;background:#f3f4f6;color:#1f2937;margin:0;padding:10px}.container{max-width:1600px;margin:0 auto}.section-title{font-size:1.5rem;font-weight:800;border-left:6px solid #3b82f6;padding-left:12px;margin:30px 0 15px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:15px}.card{background:#fff;border-radius:12px;padding:20px;box-shadow:0 4px 6px -1px rgba(0,0,0,0.1);text-align:center}.card-link{text-decoration:none;color:inherit;display:block}.card-label{font-size:1.1rem;font-weight:700;color:#4b5563;margin-bottom:8px}.card-value{font-size:2.1rem;font-weight:900}.card-delta{font-size:1.1rem;font-weight:700}.up{color:#dc2626}.down{color:#2563eb}.flat{color:#6b7280}.list-box{background:#fff;border-radius:12px;padding:20px}.dual-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:30px}.chatbot-fab{position:fixed;bottom:30px;right:30px;width:65px;height:65px;background:#111827;color:#fff;border-radius:50%;display:flex;justify-content:center;align-items:center;font-size:2rem;cursor:pointer;z-index:1000}.chatbot-window{position:fixed;bottom:110px;right:30px;width:400px;max-width:90vw;background:#fff;border-radius:16px;box-shadow:0 15px 35px rgba(0,0,0,0.2);display:none;flex-direction:column;z-index:999}.chatbot-header{background:#111827;color:#fff;padding:18px;font-weight:bold;display:flex;justify-content:space-between}.chat-history{height:400px;overflow-y:auto;padding:15px;display:flex;flex-direction:column;gap:12px;background:#f9fafb}.chat-msg{padding:12px 16px;border-radius:14px;max-width:85%}.chat-msg.user{background:#3b82f6;color:#fff;align-self:flex-end}.chat-msg.ai{background:#fff;color:#1f2937;align-self:flex-start;border:1px solid #e5e7eb}.chat-input-area{display:flex;padding:15px;gap:10px;background:#fff}.chat-input-area input{flex:1;padding:12px;border:1px solid #d1d5db;border-radius:8px}.chat-input-area button{padding:12px;background:#3b82f6;color:#fff;border:none;border-radius:8px;cursor:pointer}@media(max-width:768px){.grid{grid-template-columns:repeat(2,1fr)}.dual-grid{grid-template-columns:1fr}.chatbot-window{right:5vw;width:90vw;bottom:90px}}</style></head><body>
<div id="lock-screen" style="position:fixed;top:0;left:0;width:100%;height:100%;background:#f3f4f6;z-index:9999;display:flex;justify-content:center;align-items:center;"><div style="background:#fff;padding:40px;border-radius:15px;text-align:center;"><h2>🔒 대시보드 잠금</h2><input type="password" id="pw-input" style="padding:12px;margin-bottom:15px;width:100%;"><br><button onclick="checkPassword()" style="padding:12px;width:100%;background:#3b82f6;color:#fff;border:none;border-radius:8px;">입장</button><p id="pw-error" style="color:red;display:none;">비밀번호 오류</p></div></div>
<div class="chatbot-fab" onclick="document.getElementById('chatbot-window').style.display=document.getElementById('chatbot-window').style.display==='none'||!document.getElementById('chatbot-window').style.display?'flex':'none'">💬</div>
<div class="chatbot-window" id="chatbot-window"><div class="chatbot-header"><span>🤖 AI 챗봇</span><span onclick="document.getElementById('chatbot-window').style.display='none'" style="cursor:pointer">✖</span></div><div id="chat-history" class="chat-history"><div class="chat-msg ai">질문을 입력해주세요! (최초 API 키 필요)</div></div><div class="chat-input-area"><input type="text" id="chat-input" placeholder="질문 입력..."><button onclick="sendChatMessage()">전송</button></div></div>
{% macro render_metric(label, obj, is_int=False, sfx='') %}
{% if obj is mapping and obj.get('ticker') %}<a href="https://kr.tradingview.com/chart/?symbol={{ obj.ticker }}" target="_blank" class="card-link">{% endif %}
<div class="card"><div class="card-label">{{ label }}</div>
{% if obj is mapping and obj.get('value') != "N/A" %}
<div class="card-value">{% if is_int %}{{ "{:,}".format(obj.value|int) }}{% else %}{{ "{:,.2f}".format(obj.value) }}{% endif %}{{ sfx }}{% if obj.get('rating') %} <span style="font-size:1rem;color:#6b7280;">({{ obj.rating }})</span>{% endif %}</div>
{% set diff_fmt = "{:,}".format(obj.diff|abs|int) if is_int else "{:,.2f}".format(obj.diff|abs) %}
{% if obj.diff > 0 %}<div class="card-delta up">▲ {{ diff_fmt }} ({{ "{:,.2f}".format(obj.pct|abs) }}%)</div>{% elif obj.diff < 0 %}<div class="card-delta down">▼ {{ diff_fmt }} ({{ "{:,.2f}".format(obj.pct|abs) }}%)</div>{% else %}<div class="card-delta flat">- {{ diff_fmt }} (0.00%)</div>{% endif %}
{% else %}<div class="card-value" style="color:#9ca3af;">N/A</div>{% endif %}</div>
{% if obj is mapping and obj.get('ticker') %}</a>{% endif %}
{% endmacro %}
<div class="container"><h1 style="text-align:center">📊 실시간 미국 증시 대시보드</h1>
<div class="section-title" onclick="const c=document.getElementById('ai-content');c.style.display=c.style.display==='none'?'block':'none'" style="cursor:pointer">✨ 🤖 AI 증시 브리핑 ▼</div>
<div class="list-box" id="ai-content"><p id="ai-summary-text" style="white-space:pre-wrap;font-size:1.2rem;line-height:1.8;font-weight:500;">{{ data.ai_summary }}</p></div>
<div class="dual-grid"><div><div class="section-title">📰 뉴스</div><div class="list-box">{% for i in data.news %}<div style="margin-bottom:15px"><a href="{{ i.link }}" target="_blank">{{ i.title }}</a><br><span style="color:#6b7280;font-size:0.9rem">({{ i.date }})</span></div>{% endfor %}</div></div><div><div class="section-title">📅 지표</div><div class="list-box">{% for e in data.calendar %}<div style="padding:5px 0">{{ e.title }}</div>{% endfor %}</div></div></div>
<div class="section-title">📈 1. 주요 지수</div><div class="grid">{{ render_metric('S&P 500', data.indices['S&P 500'])}}{{ render_metric('다우존스', data.indices['다우존스'])}}{{ render_metric('나스닥 100', data.indices['나스닥 100'])}}{{ render_metric('반도체', data.indices['필라델피아 반도체'])}}{{ render_metric('니케이 225', data.indices['니케이 225'])}}{{ render_metric('대만 가권', data.indices['대만 가권'])}}</div>
<div class="section-title">🌐 2. 매크로 및 시장 심리</div><div class="grid">{{ render_metric('달러 인덱스', data.macros['달러 인덱스'])}}{{ render_metric('원/달러', data.macros['원/달러 환율'], False, '원')}}{{ render_metric('미국채 10년', data.macros['미국채 10년물'], False, '%')}}{{ render_metric('빅스(VIX)', data.macros['빅스(VIX)'])}}{{ render_metric('CNN 공포지수', data.cnn, True)}}</div>
<div class="section-title">💧 3. 연준 유동성</div><div class="grid">{% if data.fed %}{{ render_metric('순유동성', data.fed['Net Liquidity'], True, 'M$')}}{{ render_metric('역레포(RRP)', data.fed['Reverse Repo'], True, 'M$')}}{{ render_metric('TGA 잔액', data.fed['TGA'], True, 'M$')}}{% else %}<div class="card"><div class="card-value">N/A</div></div>{% endif %}</div>
<div class="section-title">🛢️ 4. 원자재</div><div class="grid">{{ render_metric('WTI유', data.commodities['WTI유'], False, '$')}}{{ render_metric('브렌트유', data.commodities['브렌트유'], False, '$')}}{{ render_metric('금(1돈)', data.gold, True, '원')}}{{ render_metric('은(1돈)', data.silver, True, '원')}}{{ render_metric('구리', data.copper, True, '원')}}</div>
<div class="section-title">💻 5. 빅테크</div><div class="grid">{% for n, o in data.tech_soft.items() %}{{ render_metric(n, o, False, '$')}}{% endfor %}</div><div class="section-title">🧠 6. 반도체</div><div class="grid">{% for n, o in data.semi_ai.items() %}{{ render_metric(n, o, False, '$')}}{% endfor %}</div><div class="section-title">⚡ 7. 에너지</div><div class="grid">{% for n, o in data.energy_infra.items() %}{{ render_metric(n, o, False, '$')}}{% endfor %}</div><div class="section-title">🏥 8. 헬스케어</div><div class="grid">{% for n, o in data.health.items() %}{{ render_metric(n, o, False, '$')}}{% endfor %}</div>
</div>
<script>
function checkPassword(){const i=document.getElementById('pw-input').value;const h=[0x1e,0x18,0x1a,0x19],k=0x2a;let a=(i.length===h.length);if(a){for(let j=0;j<h.length;j++){if((i.charCodeAt(j)^k)!==h[j]){a=false;break;}}}if(a){document.getElementById('lock-screen').style.display='none';sessionStorage.setItem('isUnlocked','true')}else{document.getElementById('pw-error').style.display='block'}}
window.onload=()=>{if(sessionStorage.getItem('isUnlocked')==='true')document.getElementById('lock-screen').style.display='none';document.getElementById('pw-input').addEventListener('keypress',e=>{if(e.key==='Enter')checkPassword()});document.getElementById('chat-input').addEventListener('keypress',e=>{if(e.key==='Enter')sendChatMessage()})}
let chatHistory=[];
async function sendChatMessage(){const input=document.getElementById('chat-input');const msg=input.value.trim();if(!msg){alert("입력해주세요!");return}let key=localStorage.getItem('gemini_api_key');if(!key){key=prompt("API 키 입력:");if(!key)return;localStorage.setItem('gemini_api_key',key.trim())}if(chatHistory.length===0){chatHistory.push({"role":"user","parts":[{"text":`할루시네이션 금지. 제공된 요약 기반 답변.\n[데이터]\n${document.getElementById('ai-summary-text').innerText}`}]});chatHistory.push({"role":"model","parts":[{"text":"네, 질문해주세요."}]})}appendMsg('user',msg);input.value='';chatHistory.push({"role":"user","parts":[{"text":msg}]});const lId='msg-'+Date.now();appendMsg('ai','분석 중...',lId);try{let res=await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent?key=${key}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({contents:chatHistory})});if(!res.ok){res=await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent?key=${key}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({contents:chatHistory})})}const d=await res.json();if(!res.ok)throw new Error('API 오류');const txt=d.candidates[0].content.parts[0].text;chatHistory.push({"role":"model","parts":[{"text":txt}]});document.getElementById(lId).innerHTML=txt.replace(/\\n/g,'<br>')}catch(e){chatHistory.pop();document.getElementById(lId).innerHTML=`🚨 오류: ${e.message}`}}
function appendMsg(r,t,id=null){const h=document.getElementById('chat-history');const d=document.createElement('div');d.className='chat-msg '+r;if(id)d.id=id;d.innerHTML=t.replace(/\\n/g,'<br>');h.appendChild(d);h.scrollTop=h.scrollHeight}
</script></body></html>"""

def generate_html():
    with app.app_context():
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(render_template_string(HTML_TEMPLATE, data=get_dashboard_data()))

if __name__ == "__main__":
    generate_html()
