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

# --- SSL 우회 및 클라우드스크래퍼 ---
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

scraper = cloudscraper.create_scraper()
app = Flask(__name__)

# --- [ 데이터 수집 함수 ] ---
def fetch_yfinance_data(tickers):
    data = {}
    for name, ticker in tickers.items():
        try:
            hist = yf.Ticker(ticker).history(period="5d")
            if 'Close' in hist.columns:
                close_prices = hist['Close'].dropna()
                if len(close_prices) >= 2:
                    current = float(close_prices.iloc[-1])
                    prev = float(close_prices.iloc[-2])
                    diff = current - prev
                    pct = (diff / prev) * 100 if prev != 0 else 0
                    data[name] = {'value': current, 'diff': diff, 'pct': pct}
                    continue
            data[name] = {'value': "N/A", 'diff': 0, 'pct': 0}
        except:
            data[name] = {'value': "N/A", 'diff': 0, 'pct': 0}
    return data

def get_fear_and_greed():
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://edition.cnn.com",
        "Referer": "https://edition.cnn.com/"
    }
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            return {
                'score': data['fear_and_greed']['score'],
                'rating': data['fear_and_greed']['rating'],
                'diff': data['fear_and_greed']['score'] - data['fear_and_greed']['previous_close']
            }
        return None
    except:
        return None

def get_naver_finance(url, row_idx=0, col_idx=1):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://finance.naver.com/"
    }
    try:
        import re
        
        # 1. 클라우드스크래퍼 통신 지연 시 일반 requests로 즉시 재시도하여 안정성 확보
        try:
            res = scraper.get(url, headers=headers, timeout=10)
        except:
            res = requests.get(url, headers=headers, timeout=10)
            
        res.encoding = 'euc-kr'
        
        # 2. 정규표현식을 사용해 <td class="num"> 안의 '숫자와 소수점'만 완벽하게 추출
        # (등락률 기호나 화살표 아이콘(img)이 있는 셀은 자동으로 필터링 됨)
        prices = re.findall(r'<td class="num">\s*([0-9\,\.]+)\s*</td>', res.text)
        
        if len(prices) >= 2:
            current = float(prices[0].replace(',', ''))
            prev = float(prices[1].replace(',', ''))
            diff = current - prev
            pct = (diff / prev) * 100 if prev != 0 else 0
            return {'value': current, 'diff': diff, 'pct': pct}
            
    except Exception as e:
        print(f"네이버 금융 데이터 수집 오류: {e}") 
        
    return {'value': "N/A", 'diff': 0, 'pct': 0}

def get_silver_don_price():
    try:
        si = yf.Ticker("SI=F").history(period="5d")['Close'].dropna()
        krw = yf.Ticker("KRW=X").history(period="5d")['Close'].dropna()
        if len(si) >= 2 and len(krw) >= 2:
            current = (float(si.iloc[-1]) / 31.1034768) * 3.75 * float(krw.iloc[-1])
            prev = (float(si.iloc[-2]) / 31.1034768) * 3.75 * float(krw.iloc[-2])
            diff = current - prev
            pct = (diff / prev) * 100 if prev != 0 else 0
            return {'value': int(current), 'diff': int(diff), 'pct': pct}
        return {'value': "N/A", 'diff': 0, 'pct': 0}
    except:
        return {'value': "N/A", 'diff': 0, 'pct': 0}

def get_gold_don_price():
    try:
        gc = yf.Ticker("GC=F").history(period="5d")['Close'].dropna()
        krw = yf.Ticker("KRW=X").history(period="5d")['Close'].dropna()
        if len(gc) >= 2 and len(krw) >= 2:
            current = (float(gc.iloc[-1]) / 31.1034768) * 3.75 * float(krw.iloc[-1])
            prev = (float(gc.iloc[-2]) / 31.1034768) * 3.75 * float(krw.iloc[-2])
            diff = current - prev
            pct = (diff / prev) * 100 if prev != 0 else 0
            return {'value': int(current), 'diff': int(diff), 'pct': pct}
        return {'value': "N/A", 'diff': 0, 'pct': 0}
    except:
        return {'value': "N/A", 'diff': 0, 'pct': 0}

def get_fed_liquidity():
    end = datetime.today()
    start = end - timedelta(days=60)
    try:
        df = web.DataReader(['WALCL', 'WTREGEN', 'RRPONTSYD', 'WRESBAL'], 'fred', start, end).ffill().dropna()
        df.columns = ['Total Assets', 'TGA', 'Reverse Repo', 'Bank Reserves']
        df['Reverse Repo'] = df['Reverse Repo'] * 1000
        df['Net Liquidity'] = df['Total Assets'] - df['TGA'] - df['Reverse Repo']
        current, prev = df.iloc[-1], df.iloc[-2]
        result = {}
        for col in df.columns:
            diff = current[col] - prev[col]
            pct = (diff / prev[col]) * 100 if prev[col] != 0 else 0
            result[col] = {'value': current[col], 'diff': diff, 'pct': pct}
        return result
    except:
        return None

def get_google_news():
    url = "https://news.google.com/rss/search?q=미국+증시+OR+연준+OR+빅테크+OR+환율&hl=ko&gl=KR&ceid=KR:ko"
    try:
        feed = feedparser.parse(url)
        news = []
        for item in feed.entries[:7]:
            dt = datetime.strptime(item.published, '%a, %d %b %Y %H:%M:%S %Z')
            news.append({'title': item.title, 'link': item.link, 'date': dt.strftime('%Y-%m-%d %H:%M')})
        return news
    except:
        return []

def get_economic_calendar():
    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
    def translate_title(text):
        dic = {
            "Core": "근원", "Prelim": "잠정", "Advance": "예비", "Final": "확정",
            "m/m": "(전월대비)", "y/y": "(전년동기대비)", "q/q": "(전분기대비)",
            "Fed Chair Powell Speaks": "파월 연준 의장 연설",
            "FOMC Statement": "FOMC 성명서", "Federal Funds Rate": "미국 기준금리 결정", "FOMC Press Conference": "FOMC 기자회견",
            "Unemployment Claims": "신규 실업수당 청구건수", "Non-Farm Employment Change": "비농업 고용지수", "Unemployment Rate": "실업률",
            "CPI": "소비자물가지수(CPI)", "PPI": "생산자물가지수(PPI)", "Retail Sales": "소매판매", "Building Permits": "건축허가 건수",
            "Manufacturing PMI": "제조업 PMI", "Services PMI": "서비스업 PMI", "Consumer Sentiment": "미시간대 소비자심리지수",
            "JOLTS Job Openings": "JOLTS 구인건수", "CB Consumer Confidence": "CB 소비자신뢰지수", "Crude Oil Inventories": "주간 원유 재고",
            "Existing Home Sales": "기존 주택판매", "New Home Sales": "신규 주택판매", "Pending Home Sales": "잠정 주택판매",
            "GDP": "국내총생산(GDP)", "PCE Price Index": "PCE 물가지수", "Average Hourly Earnings": "평균 시간당 임금"
        }
        for eng, kor in dic.items(): text = text.replace(eng, kor)
        return text.replace("  ", " ").strip()

    try:
        res = scraper.get(url, timeout=10)
        root = ET.fromstring(res.content)
        events = []
        for event in root.findall('event'):
            country, impact = event.find('country'), event.find('impact')
            if country is not None and country.text is not None and 'USD' in country.text:
                imp = impact.text.strip() if impact is not None and impact.text else ""
                if imp in ['High', 'Medium']:
                    title_eng, date_str, time_str = event.find('title').text, event.find('date').text, event.find('time').text
                    try:
                        if 'am' in time_str.lower() or 'pm' in time_str.lower():
                            # 💡 America/New_York 을 UTC 로 변경했습니다!
                            utc_dt = datetime.strptime(f"{date_str} {time_str}", "%m-%d-%Y %I:%M%p").replace(tzinfo=ZoneInfo("UTC"))
                            kst_dt = utc_dt.astimezone(ZoneInfo("Asia/Seoul"))
                            kst_date = kst_dt.strftime("%m월 %d일")
                            kst_time = f"{'오전' if kst_dt.hour < 12 else '오후'} {kst_dt.hour % 12 or 12}:{kst_dt.minute:02d}"
                        else:
                            kst_date, kst_time = date_str, ("종일" if "all day" in time_str.lower() else "시간 미정")
                    except:
                        kst_date, kst_time = date_str, time_str
                    
                    title_kor = translate_title(title_eng)
                    icon = "🔴" if imp == 'High' else "🟡"
                    events.append({"title": f"{icon} [{kst_date} {kst_time}] {title_kor}"})
        return events if events else [{"title": "이번 주 남은 주요 달러(USD) 지표가 없습니다."}]
    except Exception as e:
        return [{"title": f"⚠️ 데이터를 불러오지 못했습니다. (원인: {str(e)})"}]
        
# --- [ AI 요약 분석 함수 ] ---
def get_ai_summary(data):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "🤖 AI 요약을 위한 API 키가 깃허브 Secrets에 설정되지 않았습니다."
    
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-3.6-flash')
        
        fed_net = f"{int(data['fed']['Net Liquidity']['value']):,} 백만 달러" if data.get('fed') else "조회 불가"
        fed_rrp = f"{int(data['fed']['Reverse Repo']['value']):,} 백만 달러" if data.get('fed') else "조회 불가"
        
        prompt = f"""
        너는 월스트리트 최고의 금융 애널리스트야. 아래 수집된 오늘 미국 증시 데이터를 분석해서, 투자자들이 오늘 아침 반드시 알아야 할 '핵심 흐름과 포인트'를 딱 3줄로 명확하게 요약해줘. (한국어로 작성하고 1., 2., 3. 번호 붙여서 작성)
        
        [오늘의 데이터]
        - S&P 500: {data['indices'].get('S&P 500', {}).get('value')}
        - 나스닥 100: {data['indices'].get('나스닥 100', {}).get('value')}
        - 미국채 10년물 금리: {data['macros'].get('미국채 10년물', {}).get('value')}%
        - 원/달러 환율: {data['macros'].get('원/달러 환율', {}).get('value')}원
        - VIX 지수: {data['macros'].get('빅스(VIX)', {}).get('value')}
        - CNN 공포탐욕지수: {data['cnn'].get('score') if data.get('cnn') else '조회 불가'}
        - 연준 순유동성(Net Liquidity): {fed_net}
        - 연준 역레포 잔액(ON RRP): {fed_rrp}
        """
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"⚠️ AI 분석 중 오류가 발생했습니다: {e}"

# --- 메모리 캐시 ---
CACHE = {}

def get_dashboard_data():
    if 'data' in CACHE and time.time() - CACHE['time'] < 600: return CACHE['data']
    
    data = {
        'indices': fetch_yfinance_data({'S&P 500': '^GSPC', '다우존스': '^DJI', '나스닥 100': '^NDX', '필라델피아 반도체': '^SOX', '나스닥 생명공학': '^NBI'}),
        'macros': fetch_yfinance_data({'달러 인덱스': 'DX-Y.NYB', '원/달러 환율': 'KRW=X', '엔/달러 환율': 'JPY=X', '미국채 10년물': '^TNX', '미국채 30년물': '^TYX', '빅스(VIX)': '^VIX'}),
        'cnn': get_fear_and_greed(),
        'commodities': fetch_yfinance_data({'WTI유': 'CL=F', '브렌트유': 'BZ=F'}),
        'dubai': get_naver_finance("https://finance.naver.com/marketindex/worldDailyQuote.naver?marketindexCd=OIL_DU&fdtc=2"),
        'silver': get_silver_don_price(),
        'gold': get_gold_don_price(),
        'fed': get_fed_liquidity(),
        
        # 💡 M7에서 주요 빅테크 및 관심 종목 12개로 확장!
        'bigtech': fetch_yfinance_data({
            'Apple': 'AAPL', 'Microsoft': 'MSFT', 'Alphabet': 'GOOGL', 'Amazon': 'AMZN', 'NVIDIA': 'NVDA', 'Meta': 'META', 'Tesla': 'TSLA',
            'Micron': 'MU', 'TSMC': 'TSM', 'Oracle': 'ORCL', 'Palantir': 'PLTR', 'Eli Lilly': 'LLY'
        }),
        'news': get_google_news(),
        'calendar': get_economic_calendar()
    }
    
    print("🤖 AI에게 시황 3줄 요약을 요청하는 중입니다...")
    data['ai_summary'] = get_ai_summary(data)
    
    CACHE['data'] = data
    CACHE['time'] = time.time()
    return data

# --- [ HTML 템플릿 ] ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>실시간 미국 증시 대시보드</title>
    <link rel="stylesheet" as="style" crossorigin href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css" />
    <style>
        body { font-family: 'Pretendard', sans-serif; background-color: #f3f4f6; color: #1f2937; margin: 0; padding: 10px; }
        .container { max-width: 1600px; margin: 0 auto; padding: 10px; }
        .header-title { text-align: center; font-size: 2.2rem; font-weight: 900; margin: 20px 0 30px 0; color: #111827; word-break: keep-all; }
        .section-title { font-size: 1.5rem; font-weight: 800; border-left: 6px solid #3b82f6; padding-left: 12px; margin: 30px 0 15px 0; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 15px; }
        .card { background: #ffffff; border-radius: 12px; padding: 20px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); text-align: center; }
        .card-label { font-size: 1.1rem; font-weight: 700; color: #4b5563; margin-bottom: 8px; }
        .card-value { font-size: 2.1rem; font-weight: 900; color: #111827; margin-bottom: 5px; word-break: break-all; }
        .card-delta { font-size: 1.1rem; font-weight: 700; display: flex; justify-content: center; align-items: center; gap: 5px; }
        .up { color: #dc2626; } .down { color: #2563eb; } .flat { color: #6b7280; }
        .list-box { background: #ffffff; border-radius: 12px; padding: 20px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }
        .news-item { margin-bottom: 15px; font-size: 1.1rem; font-weight: 600; line-height: 1.4; }
        .news-link { color: #1d4ed8; text-decoration: none; }
        .news-date { font-size: 0.9rem; color: #6b7280; display: inline-block; margin-top: 3px; }
        .cal-item { font-size: 1.1rem; padding: 10px 0; border-bottom: 1px solid #e5e7eb; line-height: 1.4; }
        .cal-item:last-child { border-bottom: none; }
        .dual-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 30px; }
        
        @media (max-width: 768px) {
            body { padding: 5px; }
            .header-title { font-size: 1.6rem; margin: 15px 0 20px 0; }
            .section-title { font-size: 1.25rem; margin: 25px 0 10px 0; }
            .grid { grid-template-columns: repeat(2, 1fr); gap: 10px; }
            .card { padding: 12px; }
            .card-label { font-size: 0.95rem; }
            .card-value { font-size: 1.5rem; }
            .card-delta { font-size: 0.9rem; }
            .dual-grid { grid-template-columns: 1fr; gap: 15px; }
        }
    </style>
</head>
<body>
<!-- 🔐 비밀번호 잠금 화면 시작 -->
<div id="lock-screen" style="position: fixed; top: 0; left: 0; width: 100%; height: 100%; background-color: #f3f4f6; z-index: 9999; display: flex; flex-direction: column; justify-content: center; align-items: center;">
    <div style="background: white; padding: 40px; border-radius: 15px; box-shadow: 0 10px 25px rgba(0,0,0,0.1); text-align: center;">
        <h2 style="margin-top: 0; margin-bottom: 20px; color: #111827; font-weight: 800;">🔒 대시보드 잠금</h2>
        <input type="password" id="pw-input" placeholder="비밀번호를 입력하세요" style="width: 100%; box-sizing: border-box; padding: 12px; font-size: 1.1rem; border: 1.5px solid #d1d5db; border-radius: 8px; margin-bottom: 15px; outline: none; text-align: center;">
        <button onclick="checkPassword()" style="width: 100%; padding: 12px; font-size: 1.1rem; background-color: #3b82f6; color: white; border: none; border-radius: 8px; cursor: pointer; font-weight: bold;">입장하기</button>
        <p id="pw-error" style="color: #ef4444; margin-top: 15px; font-weight: 600; display: none;">비밀번호가 틀렸습니다.</p>
    </div>
</div>

<script>
    // 💡 여기에 원하는 비밀번호를 설정하세요! (현재는 1234)
    const SECRET_PASSWORD = "4203";

    function checkPassword() {
        const input = document.getElementById('pw-input').value;
        if (input === SECRET_PASSWORD) {
            // 비밀번호가 맞으면 잠금 화면을 숨김
            document.getElementById('lock-screen').style.display = 'none';
            // 창을 닫기 전까지 로그인 상태 유지
            sessionStorage.setItem('isUnlocked', 'true');
        } else {
            // 비밀번호가 틀리면 에러 메시지 표시
            document.getElementById('pw-error').style.display = 'block';
        }
    }

    // 페이지 접속 시 로그인 상태인지 확인
    window.onload = function() {
        if (sessionStorage.getItem('isUnlocked') === 'true') {
            document.getElementById('lock-screen').style.display = 'none';
        }
        // 엔터키만 눌러도 확인 버튼이 눌리도록 설정
        document.getElementById('pw-input').addEventListener('keypress', function (e) {
            if (e.key === 'Enter') {
                checkPassword();
            }
        });
    }
</script>
<!-- 🔐 비밀번호 잠금 화면 끝 -->
{% macro render_metric(label, data_obj, is_int=False, suffix='') %}
    <div class="card">
        <div class="card-label">{{ label }}</div>
        {% if data_obj.value != "N/A" %}
            <div class="card-value">
                {% if is_int %}{{ "{:,}".format(data_obj.value|int) }}{{ suffix }}
                {% else %}{{ "{:,.2f}".format(data_obj.value) }}{{ suffix }}{% endif %}
            </div>
            {% set diff_val = data_obj.diff|abs %}
            {% if is_int %}{% set diff_fmt = "{:,}".format(diff_val|int) %}{% else %}{% set diff_fmt = "{:,.2f}".format(diff_val) %}{% endif %}
            
            {% if data_obj.diff > 0 %} <div class="card-delta up">▲ {{ diff_fmt }} ({{ "{:,.2f}".format(data_obj.pct|abs) }}%)</div>
            {% elif data_obj.diff < 0 %} <div class="card-delta down">▼ {{ diff_fmt }} ({{ "{:,.2f}".format(data_obj.pct|abs) }}%)</div>
            {% else %} <div class="card-delta flat">- {{ diff_fmt }} (0.00%)</div> {% endif %}
        {% else %}
            <div class="card-value" style="font-size: 1.5rem; color:#9ca3af;">조회 불가</div>
        {% endif %}
    </div>
{% endmacro %}

<div class="container">
    <div class="header-title">📊 실시간 미국 증시 대시보드</div>

    <div class="section-title" style="margin-top: 0; border-left-color: #8b5cf6; color: #6d28d9;">✨ 🤖 AI 오늘의 증시 3줄 요약</div>
    <div class="list-box" style="margin-bottom: 30px; background: linear-gradient(145deg, #f3f4f6, #ffffff); border: 2px solid #e5e7eb;">
        <p style="white-space: pre-wrap; font-size: 1.2rem; font-weight: 600; line-height: 1.8; color: #374151; margin: 0;">{{ data.ai_summary }}</p>
    </div>

    <div class="section-title">📈 1. 미국 주요 지수</div>
    <div class="grid">
        {{ render_metric('S&P 500', data.indices['S&P 500']) }}
        {{ render_metric('다우존스', data.indices['다우존스']) }}
        {{ render_metric('나스닥 100', data.indices['나스닥 100']) }}
        {{ render_metric('필라델피아 반도체', data.indices['필라델피아 반도체']) }}
        {{ render_metric('나스닥 생명공학', data.indices['나스닥 생명공학']) }}
    </div>

    <div class="section-title">🌐 2. 매크로 및 시장 심리 지표</div>
    <div class="grid">
        {{ render_metric('달러 인덱스', data.macros['달러 인덱스']) }}
        {{ render_metric('원/달러 환율', data.macros['원/달러 환율'], False, '원') }}
        {{ render_metric('엔/달러 환율', data.macros['엔/달러 환율'], False, '엔') }}
        {{ render_metric('미국채 10년물 (%)', data.macros['미국채 10년물'], False, '%') }}
        {{ render_metric('미국채 30년물 (%)', data.macros['미국채 30년물'], False, '%') }}
        {{ render_metric('빅스(VIX) 지수', data.macros['빅스(VIX)']) }}
        
        <div class="card">
            <div class="card-label">CNN 공포탐욕지수</div>
            {% if data.cnn %}
                <div class="card-value">{{ data.cnn.score | int }} ({{ data.cnn.rating }})</div>
                {% if data.cnn.diff > 0 %} <div class="card-delta up">▲ {{ data.cnn.diff | abs | int }} (전일대비)</div>
                {% elif data.cnn.diff < 0 %} <div class="card-delta down">▼ {{ data.cnn.diff | abs | int }} (전일대비)</div>
                {% else %} <div class="card-delta flat">- 0 (전일대비)</div> {% endif %}
            {% else %}
                <div class="card-value" style="font-size: 1.5rem; color:#9ca3af;">조회 불가</div>
            {% endif %}
        </div>
    </div>

    <div class="section-title">🛢️ 3. 원자재 및 귀금속 시세</div>
    <div class="grid">
        {{ render_metric('WTI유 ($/bbl)', data.commodities['WTI유']) }}
        {{ render_metric('브렌트유 ($/bbl)', data.commodities['브렌트유']) }}
        {{ render_metric('두바이유 ($/bbl)', data.dubai) }}
        {{ render_metric('국내 금시세 (1돈)', data.gold, True, '원') }}
        {{ render_metric('국내 은시세 (1돈)', data.silver, True, '원') }}
    </div>

    <div class="section-title">🏦 4. 연준(Fed) 유동성 현황 (단위: 백만 $)</div>
    {% if data.fed %}
    <div class="grid">
        {{ render_metric('순유동성 (Net Liquidity)', data.fed['Net Liquidity'], True) }}
        {{ render_metric('역레포 잔액 (ON RRP)', data.fed['Reverse Repo'], True) }}
        {{ render_metric('은행 지급준비금', data.fed['Bank Reserves'], True) }}
        {{ render_metric('재무부 일반계정 (TGA)', data.fed['TGA'], True) }}
    </div>
    {% endif %}

    <!-- 💡 섹션 이름 변경 및 추가된 12개 종목 반영 -->
    <div class="section-title">💻 5. 주요 빅테크 및 관심 종목 동향</div>
    <div class="grid">
        {{ render_metric('Apple', data.bigtech['Apple'], False, '$') }}
        {{ render_metric('Microsoft', data.bigtech['Microsoft'], False, '$') }}
        {{ render_metric('Alphabet', data.bigtech['Alphabet'], False, '$') }}
        {{ render_metric('Amazon', data.bigtech['Amazon'], False, '$') }}
        {{ render_metric('NVIDIA', data.bigtech['NVIDIA'], False, '$') }}
        {{ render_metric('Meta', data.bigtech['Meta'], False, '$') }}
        {{ render_metric('Tesla', data.bigtech['Tesla'], False, '$') }}
        {{ render_metric('Micron', data.bigtech['Micron'], False, '$') }}
        {{ render_metric('TSMC', data.bigtech['TSMC'], False, '$') }}
        {{ render_metric('Oracle', data.bigtech['Oracle'], False, '$') }}
        {{ render_metric('Palantir', data.bigtech['Palantir'], False, '$') }}
        {{ render_metric('Eli Lilly', data.bigtech['Eli Lilly'], False, '$') }}
    </div>

    <div class="dual-grid">
        <div>
            <div class="section-title" style="margin-top:0;">📰 6. 주요 경제 및 빅테크 뉴스</div>
            <div class="list-box">
                {% if data.news %}
                    {% for item in data.news %}
                        <div class="news-item"><a href="{{ item.link }}" target="_blank" class="news-link">{{ item.title }}</a><br><span class="news-date">({{ item.date }})</span></div>
                    {% endfor %}
                {% endif %}
            </div>
        </div>
        <div>
            <div class="section-title" style="margin-top:0;">📅 7. 주간 주요 달러(USD) 경제 지표</div>
            <div class="list-box">
                {% if data.calendar %}
                    {% for event in data.calendar %}
                        <div class="cal-item">{{ event.title }}</div>
                    {% endfor %}
                {% endif %}
            </div>
        </div>
    </div>
</div>
</body>
</html>
"""

def generate_html():
    with app.app_context():
        dashboard_data = get_dashboard_data()
        rendered = render_template_string(HTML_TEMPLATE, data=dashboard_data)
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(rendered)

if __name__ == "__main__":
    generate_html()
