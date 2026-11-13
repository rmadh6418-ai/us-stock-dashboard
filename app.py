import flask
from flask import Flask, render_template_string
import yfinance as yf
import pandas as pd
import requests
import feedparser
import pandas_datareader.data as web
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import ssl, time, cloudscraper, os, re, concurrent.futures
import xml.etree.ElementTree as ET
import google.generativeai as genai

try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
app = Flask(__name__)

def fetch_yfinance_data(tickers):
    data = {}
    for name, ticker in tickers.items():
        try:
            hist = yf.Ticker(ticker).history(period="5d")
            if 'Close' in hist.columns and len(hist) >= 2:
                current, prev = float(hist['Close'].iloc[-1]), float(hist['Close'].iloc[-2])
                data[name] = {'value': current, 'diff': current - prev, 'pct': ((current - prev) / prev) * 100, 'ticker': ticker}
            else:
                data[name] = {'value': "N/A", 'diff': 0, 'pct': 0, 'ticker': ticker}
        except:
            data[name] = {'value': "N/A", 'diff': 0, 'pct': 0, 'ticker': ticker}
    return data

def get_fear_and_greed():
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    try:
        res = scraper.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            d = res.json()['fear_and_greed']
            return {'value': d['score'], 'diff': d['score'] - d['previous_close'], 'pct': ((d['score'] - d['previous_close'])/d['previous_close'])*100, 'rating': d['rating']}
    except: pass
    return None

def get_fed_liquidity():
    try:
        end = datetime.today()
        start = end - timedelta(days=60)
        df = web.DataReader(['WALCL', 'WTREGEN', 'RRPONTSYD'], 'fred', start, end).ffill().dropna()
        df['RRPONTSYD'] *= 1000
        df['Net'] = df['WALCL'] - df['WTREGEN'] - df['RRPONTSYD']
        cur, prev = df.iloc[-1], df.iloc[-2]
        return {col: {'value': cur[col], 'diff': cur[col]-prev[col], 'pct': ((cur[col]-prev[col])/prev[col])*100} for col in df.columns}
    except: return None

def process_single_news(item):
    date_str = datetime.strptime(item.published, '%a, %d %b %Y %H:%M:%S %Z').strftime('%Y-%m-%d %H:%M') if hasattr(item, 'published') else ""
    content = re.sub('<[^<]+>', '', item.summary) if hasattr(item, 'summary') else ""
    try:
        res = requests.get(item.link, headers={"User-Agent": "Mozilla/5.0"}, timeout=1.5)
        if res.status_code == 200:
            clean = re.sub(r'<[^>]+>', ' ', res.text)
            content = re.sub(r'\s+', ' ', clean)[:800]
    except: pass
    return {'title': item.title, 'link': item.link, 'date': date_str, 'content': content.replace('"', "'").replace('\n', ' ')}

def get_google_news():
    try:
        items = feedparser.parse("https://news.google.com/rss/search?q=미국+증시+OR+연준+OR+빅테크+OR+환율&hl=ko&gl=KR&ceid=KR:ko").entries[:15]
        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as ex:
            return list(ex.map(process_single_news, items))
    except: return []

def get_economic_calendar():
    try:
        res = scraper.get("https://nfs.faireconomy.media/ff_calendar_thisweek.xml", timeout=5)
        events = []
        for ev in ET.fromstring(res.content).findall('event'):
            if ev.find('country').text == 'USD' and ev.find('impact').text in ['High', 'Medium']:
                title = ev.find('title').text.replace('Fed Chair Powell Speaks', '파월 의장 연설').replace('CPI', '소비자물가지수')
                events.append({"title": f"{'🔴' if ev.find('impact').text=='High' else '🟡'} [{ev.find('date').text} {ev.find('time').text}] {title}"})
        return events
    except: return []

def get_ai_summary(data):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key: return "🤖 AI 요약을 위한 API 키가 설정되지 않았습니다."
    try:
        genai.configure(api_key=api_key)
        prompt = f"오늘의 증시, 환율, 매크로 데이터를 심층 분석해 한국 증시 투자자를 위한 전망을 3줄로 요약해줘."
        return genai.GenerativeModel('gemini-3.5-flash-lite').generate_content(prompt).text.replace('*', '')
    except: return "⚠️ AI 분석 실패"

CACHE = {}
def get_dashboard_data():
    if 'data' in CACHE and time.time() - CACHE['time'] < 300: return CACHE['data']
    data = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        f_cnn = ex.submit(get_fear_and_greed)
        f_fed = ex.submit(get_fed_liquidity)
        f_news = ex.submit(get_google_news)
        f_cal = ex.submit(get_economic_calendar)
        f_tech = ex.submit(fetch_yfinance_data, {'Apple':'AAPL','MSFT':'MSFT','Alphabet':'GOOGL','NVIDIA':'NVDA','TSLA':'TSLA'})
        
        data['cnn'], data['fed'], data['news'], data['calendar'], data['tech'] = f_cnn.result(), f_fed.result(), f_news.result(), f_cal.result(), f_tech.result()
    
    data['ai_summary'] = get_ai_summary(data)
    CACHE['data'], CACHE['time'] = data, time.time()
    return data

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>실시간 미국 증시 대시보드</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css" />
    <style>
        body { font-family: 'Pretendard', sans-serif; background: #f3f4f6; color: #1f2937; margin: 0; padding: 10px; }
        .container { max-width: 1600px; margin: 0 auto; }
        .header-wrapper { display: flex; justify-content: space-between; align-items: center; margin: 20px 0 30px; position: relative; }
        .header-title { font-size: 2.2rem; font-weight: 900; margin: 0; text-align: center; flex: 1; }
        .refresh-btn { padding: 10px 16px; background: #3b82f6; color: white; border: none; border-radius: 8px; font-weight: bold; cursor: pointer; position: absolute; right: 0; }
        .section-title { font-size: 1.5rem; font-weight: 800; border-left: 6px solid #3b82f6; padding-left: 12px; margin: 30px 0 15px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 15px; }
        .list-box { background: white; border-radius: 12px; padding: 20px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); margin-bottom: 30px; }
        
        .news-container { max-height: 450px; overflow-y: auto; padding-right: 10px; }
        .news-item { margin-bottom: 15px; padding-bottom: 10px; border-bottom: 1px dashed #e2e8f0; }
        .news-link { color: #1d4ed8; text-decoration: none; font-weight: bold; font-size: 1.1rem; }
        
        .chatbot-fab { position: fixed; bottom: 30px; right: 30px; width: 65px; height: 65px; background: #111827; color: white; border-radius: 50%; display: flex; justify-content: center; align-items: center; font-size: 2rem; cursor: pointer; z-index: 1000; }
        .chatbot-window { position: fixed; bottom: 110px; right: 30px; width: 400px; background: white; border-radius: 16px; box-shadow: 0 15px 35px rgba(0,0,0,0.2); display: none; flex-direction: column; z-index: 999; border: 1px solid #e5e7eb; overflow: hidden; }
        .chatbot-header { background: #111827; color: white; padding: 18px; font-weight: bold; display: flex; justify-content: space-between; }
        .chat-history { height: 450px; overflow-y: auto; padding: 15px; display: flex; flex-direction: column; gap: 12px; background: #f9fafb; scroll-behavior: smooth; }
        .chat-msg { padding: 12px 16px; border-radius: 14px; max-width: 85%; font-size: 1.05rem; line-height: 1.6; }
        .chat-msg.user { background: #3b82f6; color: white; align-self: flex-end; }
        .chat-msg.ai { background: white; color: #1f2937; align-self: flex-start; border: 1px solid #e5e7eb; }
        .chat-input-area { display: flex; padding: 15px; background: white; border-top: 1px solid #e5e7eb; gap: 10px; }
        .chat-input-area input { flex: 1; padding: 12px; border: 1px solid #d1d5db; border-radius: 8px; }
        .chat-input-area button { padding: 12px 18px; background: #3b82f6; color: white; border: none; border-radius: 8px; cursor: pointer; }
    </style>
</head>
<body>

<div class="chatbot-fab" onclick="toggleChatbot()">💬</div>
<div class="chatbot-window" id="chatbot-window">
    <div class="chatbot-header"><span>🤖 AI 증시 분석</span><span style="cursor:pointer;" onclick="toggleChatbot()">✖</span></div>
    <div id="chat-history" class="chat-history"><div class="chat-msg ai">질문을 입력해주세요.</div></div>
    <div class="chat-input-area">
        <input type="text" id="chat-input" placeholder="질문 입력..."><button onclick="sendChatMessage()">전송</button>
    </div>
</div>

{% macro render_tv_quote(symbol) %}
<div class="tradingview-widget-container" style="border-radius:12px; overflow:hidden; box-shadow:0 4px 6px -1px rgba(0,0,0,0.1); background:white;">
  <div class="tradingview-widget-container__widget"></div>
  <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/tv-widget-single-quote.js" async>
  { "symbol": "{{ symbol }}", "width": "100%", "colorTheme": "light", "isTransparent": true, "locale": "kr" }
  </script>
</div>
{% endmacro %}

<div class="container">
    <div class="header-wrapper">
        <div class="header-title">📊 미국 증시 대시보드</div>
        <button class="refresh-btn" onclick="location.reload();">🔄 새로고침</button>
    </div>

    <!-- 1. 최상단 실시간 티커 -->
    <div class="tradingview-widget-container" style="margin-bottom:30px; border-radius:12px; overflow:hidden; box-shadow:0 4px 6px -1px rgba(0,0,0,0.1);">
      <div class="tradingview-widget-container__widget"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/tv-widget-ticker-tape.js" async>
      {
      "symbols": [{"proName":"FOREXCOM:SPXUSD","title":"S&P 500"},{"proName":"FOREXCOM:NSXUSD","title":"나스닥"},{"proName":"NASDAQ:NVDA","title":"NVIDIA"},{"proName":"KRX:005930","title":"삼성전자"}],
      "showSymbolLogo": true, "displayMode": "adaptive", "colorTheme": "light", "locale": "kr"
      }
      </script>
    </div>
    
    <div class="section-title">✨ 🤖 AI 브리핑</div>
    <div class="list-box"><p id="ai-summary-text" style="font-size:1.2rem; line-height:1.8; margin:0;">{{ data.ai_summary }}</p></div>

    <div class="section-title">📈 1. 글로벌 주요 지수 (1초 단위 실시간 연동)</div>
    <div class="grid">
        {{ render_tv_quote('FOREXCOM:SPXUSD') }}
        {{ render_tv_quote('FOREXCOM:DJIUSD') }}
        {{ render_tv_quote('FOREXCOM:NSXUSD') }}
        {{ render_tv_quote('INDEX:SOX') }}
        {{ render_tv_quote('TVC:NI225') }}   <!-- 니케이 225 실시간 -->
        {{ render_tv_quote('TWSE:TAIEX') }}  <!-- 대만 가권 실시간 -->
    </div>

    <div class="section-title">🌐 2. 환율 및 국채 (1초 단위 실시간 연동)</div>
    <div class="grid">
        {{ render_tv_quote('TVC:DXY') }}
        {{ render_tv_quote('FX_IDC:USDKRW') }}
        {{ render_tv_quote('FX_IDC:USDJPY') }}
        {{ render_tv_quote('TVC:US10Y') }}
    </div>

    <div class="section-title">🛢️ 3. 원자재 및 귀금속 (1초 단위 실시간 연동)</div>
    <div class="grid">
        {{ render_tv_quote('TVC:USOIL') }}
        {{ render_tv_quote('OANDA:XAUUSD') }}
        {{ render_tv_quote('COMEX:HG1!') }}
    </div>

    <div class="section-title">📰 경제 뉴스 (15개)</div>
    <div class="list-box news-container">
        {% for item in data.news %}
        <div class="news-item" data-content="{{ item.content }}">
            <a href="{{ item.link }}" target="_blank" class="news-link">{{ item.title }}</a><br>
            <span style="font-size:0.9rem; color:#6b7280;">{{ item.date }}</span>
        </div>
        {% endfor %}
    </div>
</div>

<script>
    let chatHistory = [];
    function toggleChatbot() {
        const win = document.getElementById('chatbot-window');
        win.style.display = win.style.display === 'none' || win.style.display === '' ? 'flex' : 'none';
    }
    
    async function sendChatMessage() {
        const inputEl = document.getElementById('chat-input');
        const message = inputEl.value.trim();
        if (!message) return;

        let apiKey = localStorage.getItem('gemini_api_key') || prompt("Gemini API 키 입력:");
        if (!apiKey) return;
        localStorage.setItem('gemini_api_key', apiKey.trim());

        if (chatHistory.length === 0) {
            const newsText = Array.from(document.querySelectorAll('.news-item')).map(n => n.getAttribute('data-content')).join('\\n');
            chatHistory.push({ "role": "user", "parts": [{ "text": `다음 뉴스 기반으로 답변해:\\n${newsText}` }] });
            chatHistory.push({ "role": "model", "parts": [{ "text": "네, 준비되었습니다." }] });
        }

        appendMessage('user', message);
        inputEl.value = '';
        chatHistory.push({ "role": "user", "parts": [{ "text": message }] });
        
        const loadingId = 'msg-' + Date.now();
        appendMessage('ai', '분석 중...', loadingId);

        try {
            let res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent?key=${apiKey}`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ contents: chatHistory })
            });
            let data = await res.json();
            const reply = data.candidates[0].content.parts[0].text;
            chatHistory.push({ "role": "model", "parts": [{ "text": reply }] });
            updateMessage(loadingId, reply);
        } catch (e) { updateMessage(loadingId, "오류 발생"); }
    }
    
    function appendMessage(role, text, id = null) {
        const he = document.getElementById('chat-history');
        const d = document.createElement('div');
        d.className = 'chat-msg ' + role; if (id) d.id = id;
        d.innerHTML = text.replace(/\\n/g, '<br>');
        he.appendChild(d); he.scrollTop = he.scrollHeight;
    }
    
    function updateMessage(id, text) {
        const d = document.getElementById(id);
        if (d) {
            d.innerHTML = text.replace(/\\n/g, '<br>');
            document.getElementById('chat-history').scrollTo({ top: d.offsetTop - 15, behavior: 'smooth' });
        }
    }
    document.getElementById('chat-input').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); sendChatMessage(); }});
</script>
</body>
</html>
"""

def generate_html():
    with app.app_context():
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(render_template_string(HTML_TEMPLATE, data=get_dashboard_data()))

if __name__ == "__main__":
    generate_html()
