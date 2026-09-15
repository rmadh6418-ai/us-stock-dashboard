from flask import Flask, render_template_string
import yfinance as yf
import pandas as pd
import requests
import feedparser
import pandas_datareader.data as web
from datetime import datetime, timedelta
import ssl
import io
import time
import cloudscraper
import xml.etree.ElementTree as ET

# --- SSL 우회 및 클라우드스크래퍼(우회 봇) 초기화 ---
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
        except Exception:
            data[name] = {'value': "N/A", 'diff': 0, 'pct': 0}
    return data

def get_fear_and_greed():
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json",
        "Referer": "https://edition.cnn.com/"
    }
    try:
        res = scraper.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            score = data['fear_and_greed']['score']
            rating = data['fear_and_greed']['rating']
            diff = score - data['fear_and_greed']['previous_close']
            return {'score': score, 'rating': rating, 'diff': diff}
        return None
    except:
        return None

def get_naver_finance(url, row_idx=0, col_idx=1):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        res.encoding = 'euc-kr'
        df = pd.read_html(io.StringIO(res.text))[0]
        current = float(str(df.iloc[row_idx, col_idx]).replace(',', ''))
        prev = float(str(df.iloc[row_idx+1, col_idx]).replace(',', ''))
        diff = current - prev
        pct = (diff / prev) * 100 if prev != 0 else 0
        return {'value': current, 'diff': diff, 'pct': pct}
    except:
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

def get_fed_liquidity():
    end = datetime.today()
    start = end - timedelta(days=60)
    try:
        df = web.DataReader(['WALCL', 'WTREGEN', 'RRPONTSYD', 'WRESBAL'], 'fred', start, end)
        df = df.ffill().dropna()
        df.columns = ['Total Assets', 'TGA', 'Reverse Repo', 'Bank Reserves']
        df['Reverse Repo'] = df['Reverse Repo'] * 1000
        df['Net Liquidity'] = df['Total Assets'] - df['TGA'] - df['Reverse Repo']
        
        current = df.iloc[-1]
        prev = df.iloc[-2]
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
    try:
        res = scraper.get(url, timeout=10)
        root = ET.fromstring(res.content)
        events = []
        
        for event in root.findall('event'):
            country = event.find('country')
            impact = event.find('impact')
            
            # 미국(USD) 지표 중 중요도가 'High'(높음)인 것만 선별
            if country is not None and country.text == 'USD':
                if impact is not None and impact.text == 'High':
                    title = event.find('title').text
                    date = event.find('date').text
                    time_str = event.find('time').text
                    events.append({"title": f"[{date} {time_str}] {title}"})
                    
        return events
    except:
        return []

# --- 메모리 캐시 (로딩 속도 개선) ---
CACHE = {}

def get_dashboard_data():
    if 'data' in CACHE and time.time() - CACHE['time'] < 600:
        return CACHE['data']
    
    indices_dict = {'S&P 500': '^GSPC', '다우존스': '^DJI', '나스닥 100': '^NDX', '필라델피아 반도체': '^SOX', '나스닥 생명공학': '^NBI'}
    macros_dict = {'달러 인덱스': 'DX-Y.NYB', '원/달러 환율': 'KRW=X', '엔/달러 환율': 'JPY=X', '미국채 10년물': '^TNX', '미국채 30년물': '^TYX', '빅스(VIX)': '^VIX'}
    m7_dict = {'Apple': 'AAPL', 'Microsoft': 'MSFT', 'Alphabet': 'GOOGL', 'Amazon': 'AMZN', 'NVIDIA': 'NVDA', 'Meta': 'META', 'Tesla': 'TSLA'}
    
    dubai_url = "https://finance.naver.com/marketindex/worldDailyQuote.naver?marketindexCd=OIL_DU&fdtc=2"
    
    data = {
        'indices': fetch_yfinance_data(indices_dict),
        'macros': fetch_yfinance_data(macros_dict),
        'cnn': get_fear_and_greed(),
        'commodities': fetch_yfinance_data({'WTI유': 'CL=F', '브렌트유': 'BZ=F'}),
        'dubai': get_naver_finance(dubai_url),
        'silver': get_silver_don_price(),
        'fed': get_fed_liquidity(),
        'm7': fetch_yfinance_data(m7_dict),
        'news': get_google_news(),
        'calendar': get_economic_calendar()
    }
    
    CACHE['data'] = data
    CACHE['time'] = time.time()
    return data

# --- [ 프론트엔드 HTML / CSS (모바일 반응형 적용) ] ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>실시간 미국 정규장 및 매크로 대시보드</title>
    <link rel="stylesheet" as="style" crossorigin href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css" />
    <style>
        body { font-family: 'Pretendard', sans-serif; background-color: #f3f4f6; color: #1f2937; margin: 0; padding: 10px; }
        .container { max-width: 1600px; margin: 0 auto; padding: 10px; }
        .header-title { text-align: center; font-size: 2.2rem; font-weight: 900; margin: 20px 0 30px 0; color: #111827; word-break: keep-all; }
        .section-title { font-size: 1.5rem; font-weight: 800; border-left: 6px solid #3b82f6; padding-left: 12px; margin: 30px 0 15px 0; }
        
        /* 반응형 그리드 설정 (모바일에선 1~2열, PC에선 자동 확장) */
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 15px; }
        .card { background: #ffffff; border-radius: 12px; padding: 20px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); text-align: center; transition: transform 0.2s; }
        .card:hover { transform: translateY(-3px); box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1); }
        .card-label { font-size: 1.1rem; font-weight: 700; color: #4b5563; margin-bottom: 8px; }
        .card-value { font-size: 2.1rem; font-weight: 900; color: #111827; margin-bottom: 5px; word-break: break-all; }
        .card-delta { font-size: 1.1rem; font-weight: 700; display: flex; justify-content: center; align-items: center; gap: 5px; }
        
        /* 한국식 상승/하락 지정 */
        .up { color: #dc2626; }    
        .down { color: #2563eb; }   
        .flat { color: #6b7280; }   
        
        .list-box { background: #ffffff; border-radius: 12px; padding: 20px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }
        .news-item { margin-bottom: 15px; font-size: 1.1rem; font-weight: 600; line-height: 1.4; }
        .news-link { color: #1d4ed8; text-decoration: none; }
        .news-link:hover { text-decoration: underline; color: #1e3a8a; }
        .news-date { font-size: 0.9rem; color: #6b7280; display: inline-block; margin-top: 3px; }
        .cal-item { font-size: 1.1rem; padding: 10px 0; border-bottom: 1px solid #e5e7eb; line-height: 1.4; }
        .cal-item:last-child { border-bottom: none; }

        /* 하단 뉴스/캘린더 2분할 영역 (모바일에선 1열로 자동 변경) */
        .dual-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 30px; }

        /* 스마트폰 화면 최적화 (768px 이하) */
        @media (max-width: 768px) {
            body { padding: 5px; }
            .header-title { font-size: 1.6rem; margin: 15px 0 20px 0; }
            .section-title { font-size: 1.25rem; margin: 25px 0 10px 0; }
            .grid { grid-template-columns: repeat(2, 1fr); gap: 10px; } /* 모바일에선 2열 배치 */
            .card { padding: 12px; }
            .card-label { font-size: 0.95rem; }
            .card-value { font-size: 1.5rem; }
            .card-delta { font-size: 0.9rem; }
            .dual-grid { grid-template-columns: 1fr; gap: 15px; } /* 뉴스/캘린더 세로로 1열 정렬 */
            .list-box { padding: 15px; }
            .news-item { font-size: 1rem; }
            .cal-item { font-size: 1rem; }
        }
    </style>
</head>
<body>

{% macro render_metric(label, data_obj, is_int=False, suffix='') %}
    <div class="card">
        <div class="card-label">{{ label }}</div>
        {% if data_obj.value != "N/A" %}
            <div class="card-value">
                {% if is_int %}
                    {{ "{:,}".format(data_obj.value|int) }}{{ suffix }}
                {% else %}
                    {{ "{:,.2f}".format(data_obj.value) }}{{ suffix }}
                {% endif %}
            </div>
            
            {% set diff_val = data_obj.diff|abs %}
            {% if is_int %}{% set diff_fmt = "{:,}".format(diff_val|int) %}{% else %}{% set diff_fmt = "{:,.2f}".format(diff_val) %}{% endif %}
            
            {% if data_obj.diff > 0 %}
                <div class="card-delta up">▲ {{ diff_fmt }} ({{ "{:,.2f}".format(data_obj.pct|abs) }}%)</div>
            {% elif data_obj.diff < 0 %}
                <div class="card-delta down">▼ {{ diff_fmt }} ({{ "{:,.2f}".format(data_obj.pct|abs) }}%)</div>
            {% else %}
                <div class="card-delta flat">- {{ diff_fmt }} (0.00%)</div>
            {% endif %}
        {% else %}
            <div class="card-value" style="font-size: 1.5rem; color:#9ca3af;">조회 불가</div>
        {% endif %}
    </div>
{% endmacro %}

<div class="container">
    <div class="header-title">📊 실시간 미국 정규장 및 매크로 대시보드</div>

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
                {% if data.cnn.diff > 0 %}
                    <div class="card-delta up">▲ {{ data.cnn.diff | abs | int }} (전일대비)</div>
                {% elif data.cnn.diff < 0 %}
                    <div class="card-delta down">▼ {{ data.cnn.diff | abs | int }} (전일대비)</div>
                {% else %}
                    <div class="card-delta flat">- 0 (전일대비)</div>
                {% endif %}
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
    {% else %}
    <div class="card" style="color: #b91c1c;">연준 데이터 서버에 일시적으로 접속할 수 없습니다.</div>
    {% endif %}

    <div class="section-title">💻 5. 빅테크(M7) 동향</div>
    <div class="grid">
        {{ render_metric('Apple', data.m7['Apple'], False, '$') }}
        {{ render_metric('Microsoft', data.m7['Microsoft'], False, '$') }}
        {{ render_metric('Alphabet', data.m7['Alphabet'], False, '$') }}
        {{ render_metric('Amazon', data.m7['Amazon'], False, '$') }}
        {{ render_metric('NVIDIA', data.m7['NVIDIA'], False, '$') }}
        {{ render_metric('Meta', data.m7['Meta'], False, '$') }}
        {{ render_metric('Tesla', data.m7['Tesla'], False, '$') }}
    </div>

    <div class="dual-grid">
        <div>
            <div class="section-title" style="margin-top:0;">📰 6. 주요 경제 및 빅테크 뉴스</div>
            <div class="list-box">
                {% if data.news %}
                    {% for item in data.news %}
                        <div class="news-item">
                            <a href="{{ item.link }}" target="_blank" class="news-link">{{ item.title }}</a><br>
                            <span class="news-date">({{ item.date }})</span>
                        </div>
                    {% endfor %}
                {% else %}
                    <div style="font-size: 1.1rem; color: #6b7280;">뉴스를 불러오지 못했습니다.</div>
                {% endif %}
            </div>
        </div>
        <div>
            <div class="section-title" style="margin-top:0;">📅 7. 주간 주요 USD 경제 지표</div>
            <div class="list-box">
                {% if data.calendar %}
                    {% for event in data.calendar %}
                        <div class="cal-item">🔹 {{ event.title }}</div>
                    {% endfor %}
                {% else %}
                    <div style="font-size: 1.1rem; color: #6b7280;">이번 주 남은 주요 달러(USD) 경제지표 일정이 없습니다.</div>
                {% endif %}
            </div>
        </div>
    </div>
</div>
</body>
</html>
"""

@app.route("/")
def index():
    dashboard_data = get_dashboard_data()
    return render_template_string(HTML_TEMPLATE, data=dashboard_data)

def generate_html():
    with app.app_context():
        print("미국 증시 데이터를 수집 중입니다. 잠시만 기다려주세요...")
        dashboard_data = get_dashboard_data()
        rendered = render_template_string(HTML_TEMPLATE, data=dashboard_data)
        
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(rendered)
        print("✅ index.html 파일이 성공적으로 생성되었습니다!")

if __name__ == "__main__":
    generate_html()
