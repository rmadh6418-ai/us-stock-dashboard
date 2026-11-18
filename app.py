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
import concurrent.futures

# 뉴스 본문 스크래핑을 위한 라이브러리
try:
    from bs4 import BeautifulSoup
except ImportError:
    pass

# --- SSL 우회 및 클라우드스크래퍼 설정 ---
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

# CNN, 경제지표 전용 스크래퍼
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    }
)
app = Flask(__name__)

# --- [ 데이터 수집 함수 ] ---
def fetch_yfinance_data(tickers):
    data = {}
    tv_mapping = {
        '^GSPC': 'SPX', '^DJI': 'DJI', '^NDX': 'NDX', '^SOX': 'SOX', '^NBI': 'NBI',
        'DX-Y.NYB': 'DXY', '^TNX': 'US10Y', '^TYX': 'US30Y', '^VIX': 'VIX',
        'CL=F': 'USOIL', 'BZ=F': 'UKOIL', 'KRW=X': 'USDKRW', 'JPY=X': 'USDJPY',
        '^N225': 'NI225', '^TWII': 'TAIEX'
    }
    for name, ticker in tickers.items():
        tv_ticker = tv_mapping.get(ticker, ticker)
        safe_id = re.sub(r'[^a-zA-Z0-9]', '', tv_ticker) # SVG 그라데이션 ID용 안전한 문자열 생성
        
        try:
            hist = yf.Ticker(ticker).history(period="1y")
            
            if 'Close' in hist.columns and len(hist) >= 20:
                hist['MA5'] = hist['Close'].rolling(window=5).mean()
                hist['MA20'] = hist['Close'].rolling(window=20).mean()
                
                close_prices = hist['Close'].dropna()
                high_prices = hist['High'].dropna()
                
                if len(close_prices) >= 2:
                    current = float(close_prices.iloc[-1])
                    prev = float(close_prices.iloc[-2])
                    ma5 = float(hist['MA5'].iloc[-1])
                    ma20 = float(hist['MA20'].iloc[-1])
                    
                    diff = current - prev
                    pct = (diff / prev) * 100 if prev != 0 else 0
                    fifty_two_week_high = float(high_prices.max())
                    near_52w_high = current >= (fifty_two_week_high * 0.97)
                    
                    if current >= ma5 and ma5 >= ma20:
                        trend = "상승추세"
                    elif current < ma5 and ma5 < ma20:
                        trend = "하락추세"
                    else:
                        trend = "횡보/혼조"
                        
                    # 1년(전체 거래일) 미니 차트 좌표 변환
                    period_data = close_prices
                    min_val = period_data.min()
                    max_val = period_data.max()
                    val_range = max_val - min_val if max_val != min_val else 1
                    pts = []
                    n = len(period_data)
                    for i, val in enumerate(period_data):
                        x = (i / (n - 1)) * 100
                        y = 95 - ((val - min_val) / val_range) * 90 
                        pts.append(f"{x},{y:.2f}")
                    sparkline_points = " ".join(pts)
                    
                    # 최고점/최저점 위치(Index) 찾기
                    min_idx = period_data.argmin()
                    max_idx = period_data.argmax()
                    
                    # 마커 좌표 계산 (퍼센트 단위)
                    min_x = (min_idx / (n - 1)) * 100
                    min_y = 95 - ((period_data.iloc[min_idx] - min_val) / val_range) * 90
                    
                    max_x = (max_idx / (n - 1)) * 100
                    max_y = 95 - ((period_data.iloc[max_idx] - min_val) / val_range) * 90
                        
                    data[name] = {
                        'value': current, 'diff': diff, 'pct': pct, 
                        'near_52w_high': near_52w_high, 'ticker': tv_ticker, 
                        'trend': trend, 'sparkline': sparkline_points, 'safe_id': safe_id,
                        'min_x': min_x, 'min_y': min_y, 'max_x': max_x, 'max_y': max_y,
                        'min_val': float(min_val), 'max_val': float(max_val)
                    }
                    continue
            data[name] = {'value': "N/A", 'diff': 0, 'pct': 0, 'near_52w_high': False, 'ticker': tv_ticker, 'trend': "알 수 없음", 'safe_id': safe_id}
        except:
            data[name] = {'value': "N/A", 'diff': 0, 'pct': 0, 'near_52w_high': False, 'ticker': tv_ticker, 'trend': "알 수 없음", 'safe_id': safe_id}
    return data

def get_fear_and_greed():
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Origin": "https://edition.cnn.com",
        "Referer": "https://edition.cnn.com/",
        "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "cross-site"
    }
    try:
        res = scraper.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            score = data['fear_and_greed']['score']
            prev = data['fear_and_greed']['previous_close']
            diff = score - prev
            pct = (diff / prev) * 100 if prev != 0 else 0
            return {'value': score, 'diff': diff, 'pct': pct, 'rating': data['fear_and_greed']['rating']}
        return None
    except:
        return None

def get_silver_don_price():
    try:
        si = yf.Ticker("SI=F").history(period="5d")['Close'].dropna()
        krw = yf.Ticker("KRW=X").history(period="5d")['Close'].dropna()
        if len(si) >= 2 and len(krw) >= 2:
            current = (float(si.iloc[-1]) / 31.1034768) * 3.75 * float(krw.iloc[-1])
            prev = (float(si.iloc[-2]) / 31.1034768) * 3.75 * float(krw.iloc[-2])
            diff = current - prev
            pct = (diff / prev) * 100 if prev != 0 else 0
            return {'value': int(current), 'diff': int(diff), 'pct': pct, 'ticker': 'XAGUSD'}
        return {'value': "N/A", 'diff': 0, 'pct': 0, 'ticker': 'XAGUSD'}
    except:
        return {'value': "N/A", 'diff': 0, 'pct': 0, 'ticker': 'XAGUSD'}

def get_gold_don_price():
    try:
        gc = yf.Ticker("GC=F").history(period="5d")['Close'].dropna()
        krw = yf.Ticker("KRW=X").history(period="5d")['Close'].dropna()
        if len(gc) >= 2 and len(krw) >= 2:
            current = (float(gc.iloc[-1]) / 31.1034768) * 3.75 * float(krw.iloc[-1])
            prev = (float(gc.iloc[-2]) / 31.1034768) * 3.75 * float(krw.iloc[-2])
            diff = current - prev
            pct = (diff / prev) * 100 if prev != 0 else 0
            return {'value': int(current), 'diff': int(diff), 'pct': pct, 'ticker': 'XAUUSD'}
        return {'value': "N/A", 'diff': 0, 'pct': 0, 'ticker': 'XAUUSD'}
    except:
        return {'value': "N/A", 'diff': 0, 'pct': 0, 'ticker': 'XAUUSD'}

def get_copper_krw_price():
    try:
        hg = yf.Ticker("HG=F").history(period="5d")['Close'].dropna()
        krw = yf.Ticker("KRW=X").history(period="5d")['Close'].dropna()
        if len(hg) >= 2 and len(krw) >= 2:
            current = float(hg.iloc[-1]) * float(krw.iloc[-1])
            prev = float(hg.iloc[-2]) * float(krw.iloc[-2])
            diff = current - prev
            pct = (diff / prev) * 100 if prev != 0 else 0
            return {'value': int(current), 'diff': int(diff), 'pct': pct, 'ticker': 'HG1!'}
        return {'value': "N/A", 'diff': 0, 'pct': 0, 'ticker': 'HG1!'}
    except:
        return {'value': "N/A", 'diff': 0, 'pct': 0, 'ticker': 'HG1!'}

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

def process_single_news(item):
    try:
        dt = datetime.strptime(item.published, '%a, %d %b %Y %H:%M:%S %Z')
        date_str = dt.strftime('%Y-%m-%d %H:%M')
    except:
        date_str = ""
    
    content_preview = ""
    
    if hasattr(item, 'summary'):
        content_preview = re.sub('<[^<]+>', '', item.summary)
        
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get(item.link, headers=headers, timeout=1.5, allow_redirects=True)
        if res.status_code == 200:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(res.content, 'html.parser')
            paragraphs = soup.find_all('p')
            raw_text = " ".join([p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20])
            if raw_text:
                content_preview = raw_text[:800]
    except:
        pass
            
    content_preview = content_preview.replace('"', "'").replace('\n', ' ')
    return {'title': item.title, 'link': item.link, 'date': date_str, 'content': content_preview}

def get_google_news():
    url = "https://news.google.com/rss/search?q=미국+증시+OR+연준+OR+빅테크+OR+환율&hl=ko&gl=KR&ceid=KR:ko"
    try:
        feed = feedparser.parse(url)
        items = feed.entries[:15]
        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
            news = list(executor.map(process_single_news, items))
        return news
    except Exception as e:
        print("News Fetch Error:", e)
        return []

def get_economic_calendar():
    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
    def translate_title(text):
        dic = {
            "Core": "근원", "Prelim": "잠정", "Advance": "예비", "Final": "확정", "m/m": "(전월대비)", "y/y": "(전년동기대비)", "q/q": "(전분기대비)",
            "Fed Chair Powell Speaks": "파월 연준 의장 연설", "FOMC Statement": "FOMC 성명서", "Federal Funds Rate": "미국 기준금리 결정",
            "Unemployment Claims": "신규 실업수당 청구건수", "Non-Farm Employment Change": "비농업 고용지수", "Unemployment Rate": "실업률",
            "CPI": "소비자물가지수(CPI)", "PPI": "생산자물가지수(PPI)", "Retail Sales": "소매판매", "Manufacturing PMI": "제조업 PMI",
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
                            utc_dt = datetime.strptime(f"{date_str} {time_str}", "%m-%d-%Y %I:%M%p").replace(tzinfo=ZoneInfo("UTC"))
                            kst_dt = utc_dt.astimezone(ZoneInfo("Asia/Seoul"))
                            kst_date, kst_time = kst_dt.strftime("%m월 %d일"), f"{'오전' if kst_dt.hour < 12 else '오후'} {kst_dt.hour % 12 or 12}:{kst_dt.minute:02d}"
                        else:
                            kst_date, kst_time = date_str, ("종일" if "all day" in time_str.lower() else "시간 미정")
                    except:
                        kst_date, kst_time = date_str, time_str
                    icon = "🔴" if imp == 'High' else "🟡"
                    events.append({"title": f"{icon} [{kst_date} {kst_time}] {translate_title(title_eng)}"})
        return events if events else [{"title": "이번 주 남은 주요 달러(USD) 지표가 없습니다."}]
    except Exception as e:
        return [{"title": f"⚠️ 데이터를 불러오지 못했습니다. (원인: {str(e)})"}]

def get_ai_summary(data):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key: return "🤖 AI 요약을 위한 API 키가 설정되지 않았습니다."
    try:
        genai.configure(api_key=api_key)
        today_str = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y년 %m월 %d일")
        
        fed_net = f"{int(data['fed']['Net Liquidity']['value']):,} 백만 달러" if data.get('fed') else "조회 불가"
        fed_rrp = f"{int(data['fed']['Reverse Repo']['value']):,} 백만 달러" if data.get('fed') else "조회 불가"
        fed_tga = f"{int(data['fed']['TGA']['value']):,} 백만 달러" if data.get('fed') else "조회 불가"
        cnn_score = f"{int(data['cnn']['value'])} ({data['cnn'].get('rating', '')})" if data.get('cnn') else "조회 불가"
        
        indices_trend_info = "\n".join([f"  - {k}: {v.get('value')} (차트 추세: {v.get('trend', '알 수 없음')})" for k, v in data['indices'].items() if isinstance(v, dict) and v.get('value') != "N/A"])
        
        prompt = f"""
        [분석 기준 날짜: {today_str}]
        당신은 전세계 0.1% 거시경제 및 금융 애널리스트입니다. 아래 제공된 간밤의 미국 증시 데이터(지수값 및 차트 추세 포함), 전세계 매크로 데이터, 경제지표, 국제유가를 심층 분석하여, 한국 증시 개장을 준비하는 투자자를 위한 핵심 시장 전망 도출해주세요.

        [★엄격한 작성 규칙 - 할루시네이션(정보 왜곡) 절대 금지★]
1. 오직 제공된 [오늘의 데이터] 및 경제지표, 뉴스 그리고 당신(AI)이 가지고 있는 최신 정보 기반으로 사실 관계를 확인하여 작성할 것.
2. 지수의 '차트 추세(상승추세, 하락추세, 횡보)' 데이터를 반드시 참고하여 현재 시장이 기술적으로 어떤 위치에 있는지 진단에 포함시킬 것.
3. 마크다운 특수기호(*, #, -, _ 등) 단 하나도 사용하지 말고 오직 줄바꿈과 번호 매기기(1., 2. 등)만 활용할 것.
4. 데이터를 기반으로 한국 증시에 어떤 영향이 있을지 근거를 제시하고 앞으로의 주가 향방을 작성할 것.
        
        [오늘의 데이터]
        <주요 지수 및 차트 추세>
        {indices_trend_info}
        <매크로 지표>
        미국채 10년물 금리: {data['macros'].get('미국채 10년물', {}).get('value')}%
        원달러 환율: {data['macros'].get('원/달러 환율', {}).get('value')}원
        VIX 지수: {data['macros'].get('빅스(VIX)', {}).get('value')}
        CNN 공포탐욕지수: {cnn_score}
        WTI유: {data['commodities'].get('WTI유', {}).get('value')}달러
        연준 순유동성: {fed_net}
        역레포(RRP) 잔액: {fed_rrp}
        TGA 잔액: {fed_tga}
        """
        
        for model_name in ['gemini-3.6-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-flash-lite', 'gemini-3-flash']:
            try:
                response = genai.GenerativeModel(model_name).generate_content(prompt)
                clean_text = response.text.replace('*', '').replace('#', '').replace('_', '').replace('+', '').replace('-', '')
                clean_text = re.sub(r'\n\s*\n', '\n\n', clean_text)
                return clean_text.strip()
            except:
                time.sleep(2)
        return "⚠️ AI 분석 실패"
    except:
        return "⚠️ AI 설정 중 오류 발생"

CACHE = {}

def get_dashboard_data():
    if 'data' in CACHE and time.time() - CACHE['time'] < 600: return CACHE['data']
    data = {}
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        f_indices = executor.submit(fetch_yfinance_data, {'S&P 500': '^GSPC', '다우존스': '^DJI', '나스닥 100': '^NDX', '필라델피아 반도체': '^SOX', '나스닥 생명공학': '^NBI', '니케이 225': '^N225', '대만 가권': '^TWII', '코스피 야간선물': 'EWY'})
        f_macros = executor.submit(fetch_yfinance_data, {'달러 인덱스': 'DX-Y.NYB', '원/달러 환율': 'KRW=X', '엔/달러 환율': 'JPY=X', '미국채 10년물': '^TNX', '미국채 30년물': '^TYX', '빅스(VIX)': '^VIX'})
        f_cnn = executor.submit(get_fear_and_greed)
        f_comm = executor.submit(fetch_yfinance_data, {'WTI유': 'CL=F', '브렌트유': 'BZ=F'})
        f_cop = executor.submit(get_copper_krw_price)
        f_sil = executor.submit(get_silver_don_price)
        f_gol = executor.submit(get_gold_don_price)
        f_fed = executor.submit(get_fed_liquidity)
        f_tech = executor.submit(fetch_yfinance_data, {'Apple': 'AAPL', 'Microsoft': 'MSFT', 'Alphabet': 'GOOGL', 'Amazon': 'AMZN', 'Meta': 'META', 'Oracle': 'ORCL', '크라우드스트라이크': 'CRWD', '클라우드플레어': 'NET', '세일스포스': 'CRM', '팔로알토 네트웍스': 'PANW', '앱러빈': 'APP', '넷플릭스': 'NFLX'})
        f_semi = executor.submit(fetch_yfinance_data, {'NVIDIA': 'NVDA', 'AMD': 'AMD', 'TSMC': 'TSM', 'Micron': 'MU', '인텔': 'INTC', '퀄컴': 'QCOM', '브로드컴': 'AVGO', 'ASML': 'ASML', '램리서치': 'LRCX', 'Palantir': 'PLTR', '템퍼스 AI': 'TEM', '웨스턴디지털': 'WDC', '셀레스티카': 'CLS', '델테크놀로지': 'DELL'})
        f_ener = executor.submit(fetch_yfinance_data, {'엑슨모빌': 'XOM', '셰브론': 'CVX', 'GE버노바': 'GEV', '뉴스케일파워': 'SMR', '오클로': 'OKLO', 'T1에너지': 'TE', '비스트라 에너지': 'VST', '블룸에너지': 'BE', 'BWX 테크놀로지스': 'BWXT', '버티브홀딩스': 'VRT', '콴타서비시스': 'PWR', '카메코': 'CCJ', '파월 인더스트리스': 'POWL', '마스텍': 'MTZ'})
        f_heal = executor.submit(fetch_yfinance_data, {'Eli Lilly': 'LLY', '화이자': 'PFE', '존슨앤드존슨': 'JNJ', '유나이티드헬스': 'UNH', '모더나': 'MRNA', '암젠': 'AMGN'})
        f_spac = executor.submit(fetch_yfinance_data, {'Tesla': 'TSLA', '스페이스X': 'SPCX', '로켓랩': 'RKLB', 'GE에어로스페이스': 'GE'})
        f_fina = executor.submit(fetch_yfinance_data, {'JP모건': 'JPM', '뱅크오브아메리카': 'BAC', '웰스파고': 'WFC', '모건스탠리': 'MS', '찰스슈왑': 'SCHW', '비자': 'V', '마스터카드': 'MA', '버크셔해서웨이': 'BRK-B', '블랙록': 'BLK', 'KKR & CO': 'KKR'})
        f_cons = executor.submit(fetch_yfinance_data, {'월마트': 'WMT', '코스트코': 'COST', '코카콜라': 'KO', '펩시코': 'PEP', '맥도날드': 'MCD'})
        f_news = executor.submit(get_google_news)
        f_cale = executor.submit(get_economic_calendar)
        
        data['indices'] = f_indices.result()
        data['macros'] = f_macros.result()
        data['cnn'] = f_cnn.result()
        data['commodities'] = f_comm.result()
        data['copper'] = f_cop.result()
        data['silver'] = f_sil.result()
        data['gold'] = f_gol.result()
        data['fed'] = f_fed.result()
        data['tech_soft'] = f_tech.result()
        data['semi_ai'] = f_semi.result()
        data['energy_infra'] = f_ener.result()
        data['health'] = f_heal.result()
        data['space_mobility'] = f_spac.result()
        data['finance'] = f_fina.result()
        data['consumer'] = f_cons.result()
        data['news'] = f_news.result()
        data['calendar'] = f_cale.result()
        
    data['ai_summary'] = get_ai_summary(data)
    CACHE['data'], CACHE['time'] = data, time.time()
    return data

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <!-- 모바일 확대/축소 허용으로 변경됨 -->
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <title>실시간 미국 증시 대시보드</title>
    <meta name="theme-color" content="#f3f4f6">
    <link rel="stylesheet" as="style" crossorigin href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css" />
    <style>
        body { font-family: 'Pretendard', sans-serif; background-color: #f3f4f6; color: #1f2937; margin: 0; padding: 10px; padding-bottom: env(safe-area-inset-bottom); }
        .container { max-width: 1600px; margin: 0 auto; padding: 10px; }
        
        .header-wrapper { display: flex; justify-content: space-between; align-items: center; margin: 20px 0 30px 0; position: relative; }
        .header-title { font-size: 2.2rem; font-weight: 900; margin: 0; text-align: center; flex: 1; }
        .refresh-btn { padding: 10px 16px; background-color: #3b82f6; color: white; border: none; border-radius: 8px; font-weight: bold; cursor: pointer; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); transition: background 0.2s; position: absolute; right: 0; display: flex; align-items: center; gap: 6px; }
        .refresh-btn:hover { background-color: #2563eb; }
        
        .section-title { font-size: 1.5rem; font-weight: 800; border-left: 6px solid #3b82f6; padding-left: 12px; margin: 30px 0 15px 0; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 15px; align-items: stretch; }
        
        .card-link { text-decoration: none; color: inherit; display: block; height: 100%; }
        .card { background: #ffffff; border-radius: 12px; padding: 20px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); text-align: center; height: 100%; box-sizing: border-box; border: 2px solid transparent; transition: transform 0.2s ease; display: flex; flex-direction: column; justify-content: center;}
        .card-link:hover .card { transform: translateY(-4px); box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1); border-color: #3b82f6; }
        .card-label { font-size: 1.1rem; font-weight: 700; color: #4b5563; margin-bottom: 8px; }
        .card-value { font-size: 2.1rem; font-weight: 900; margin-bottom: 5px; }
        .card-delta { font-size: 1.1rem; font-weight: 700; display: flex; justify-content: center; gap: 5px; }
        .up { color: #dc2626; } .down { color: #2563eb; } .flat { color: #6b7280; }
        .trend-badge { font-size: 0.95rem; font-weight: 600; padding: 4px 8px; background: #f1f5f9; border-radius: 6px; display: inline-block; margin-top: 10px; color: #475569; }
        
        .list-box { background: #ffffff; border-radius: 12px; padding: 20px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }
        
        .news-container { max-height: 450px; overflow-y: auto; padding-right: 10px; }
        .news-container::-webkit-scrollbar { width: 8px; }
        .news-container::-webkit-scrollbar-track { background: #f1f5f9; border-radius: 4px; }
        .news-container::-webkit-scrollbar-thumb { background-color: #cbd5e1; border-radius: 4px; }
        
        .news-item { margin-bottom: 15px; font-size: 1.1rem; font-weight: 600; padding-bottom: 10px; border-bottom: 1px dashed #e2e8f0; }
        .news-item:last-child { border-bottom: none; margin-bottom: 0; padding-bottom: 0; }
        .news-link { color: #1d4ed8; text-decoration: none; }
        .news-link:hover { text-decoration: underline; }
        .news-date { font-size: 0.9rem; color: #6b7280; display: block; margin-top: 4px; }
        
        .cal-item { font-size: 1.1rem; padding: 12px 0; border-bottom: 1px solid #e5e7eb; }
        .cal-item:last-child { border-bottom: none; }
        
        .chatbot-fab { position: fixed; bottom: 30px; right: 30px; width: 65px; height: 65px; background-color: #111827; color: white; border-radius: 50%; display: flex; justify-content: center; align-items: center; font-size: 2rem; box-shadow: 0 10px 25px rgba(0,0,0,0.2); cursor: pointer; z-index: 1000; transition: transform 0.2s; user-select: none; }
        .chatbot-fab:hover { transform: scale(1.05); }
        .chatbot-fab:active { transform: scale(0.95); }
        
        .chatbot-window { position: fixed; bottom: 110px; right: 30px; width: 400px; max-width: 90vw; background: #ffffff; border-radius: 16px; box-shadow: 0 15px 35px rgba(0,0,0,0.2); display: none; flex-direction: column; z-index: 999; border: 1px solid #e5e7eb; overflow: hidden; }
        .chatbot-header { background: #111827; color: white; padding: 18px; font-size: 1.2rem; font-weight: bold; display: flex; justify-content: space-between; align-items: center; }
        
        .chat-history { position: relative; height: 450px; max-height: 50vh; overflow-y: auto; padding: 15px; display: flex; flex-direction: column; gap: 12px; background: #f9fafb; scroll-behavior: smooth; }
        .chat-msg { padding: 12px 16px; border-radius: 14px; max-width: 85%; font-size: 1.05rem; line-height: 1.6; word-break: keep-all; box-shadow: 0 1px 2px rgba(0,0,0,0.05); }
        .chat-msg.user { background: #3b82f6; color: white; align-self: flex-end; border-bottom-right-radius: 4px; }
        .chat-msg.ai { background: #ffffff; color: #1f2937; align-self: flex-start; border-bottom-left-radius: 4px; border: 1px solid #e5e7eb; }
        
        .chat-input-area { display: flex; padding: 15px; background: white; border-top: 1px solid #e5e7eb; gap: 10px; }
        .chat-input-area input { flex: 1; padding: 12px; border: 1px solid #d1d5db; border-radius: 8px; font-size: 1rem; outline: none; }
        .chat-input-area button { padding: 12px 18px; background: #3b82f6; color: white; border: none; border-radius: 8px; font-weight: bold; cursor: pointer; transition: background 0.1s; }
        .chat-input-area button:hover { background: #2563eb; }

        /* 챗봇 창 확대 상태 스타일 */
        .chatbot-window.expanded { width: 90vw !important; max-width: 1200px !important; height: 85vh !important; bottom: 7.5vh !important; right: 5vw !important; transition: all 0.3s ease; }
        .chatbot-window.expanded .chat-history { height: calc(85vh - 130px) !important; max-height: none !important; }

        @media (max-width: 768px) {
            .grid { grid-template-columns: repeat(2, 1fr); gap: 10px; }
            .card { padding: 12px; } .card-value { font-size: 1.5rem; }
            .chatbot-window { right: 5vw; width: 90vw; bottom: 90px; }
            .chatbot-fab { bottom: 20px; right: 20px; width: 55px; height: 55px; font-size: 1.5rem; }
            .refresh-btn { position: relative; width: 100%; justify-content: center; margin-top: 10px; }
            .header-wrapper { flex-direction: column; align-items: stretch; margin-bottom: 20px; }
        }
    </style>
</head>
<body>
<!-- 잠금화면 -->
<div id="lock-screen" style="position: fixed; top: 0; left: 0; width: 100%; height: 100%; background-color: #f3f4f6; z-index: 9999; display: flex; flex-direction: column; justify-content: center; align-items: center;">
    <div style="background: white; padding: 40px; border-radius: 15px; box-shadow: 0 10px 25px rgba(0,0,0,0.1); text-align: center;">
        <h2 style="margin-top: 0; margin-bottom: 20px; color: #111827; font-weight: 800;">🔒 대시보드 잠금</h2>
        <input type="password" id="pw-input" placeholder="비밀번호를 입력하세요" style="width: 100%; box-sizing: border-box; padding: 12px; font-size: 1.1rem; border: 1.5px solid #d1d5db; border-radius: 8px; margin-bottom: 15px; outline: none; text-align: center;">
        <button onclick="checkPassword()" style="width: 100%; padding: 12px; font-size: 1.1rem; background-color: #3b82f6; color: white; border: none; border-radius: 8px; cursor: pointer; font-weight: bold;">입장하기</button>
        <p id="pw-error" style="color: #ef4444; margin-top: 15px; font-weight: 600; display: none;">비밀번호가 틀렸습니다.</p>
    </div>
</div>

<div class="chatbot-fab" onclick="toggleChatbot()">💬</div>

<div class="chatbot-window" id="chatbot-window">
    <div class="chatbot-header">
        <span>🤖 AI 차트 추세 & 증시 분석</span>
        <div>
            <!-- 초기화 버튼 추가 -->
            <span onclick="clearChat()" style="cursor: pointer; margin-right: 15px; font-size: 1.2rem;" title="대화 초기화">🗑️</span>
            <!-- 확대/축소 버튼 추가 -->
            <span id="chat-resize-btn" onclick="toggleChatSize()" style="cursor: pointer; margin-right: 15px; font-size: 1.2rem;" title="크게/작게">🗖</span>
            <!-- 닫기 버튼 -->
            <span class="chatbot-close" onclick="toggleChatbot()" style="cursor: pointer;" title="닫기">✖</span>
        </div>
    </div>
    <div id="chat-history" class="chat-history">
        <div class="chat-msg ai">
            안녕하세요! 경제 시황과 차트 추세(기술적 흐름)를 객관적으로 분석하는 AI 챗봇입니다.<br><br>
            오늘의 증시 방향성, 각 지수의 상승/하락 차트 추세 판단, 스크랩된 15개 최신 기사 본문 요약에 대해 자유롭게 질문해주세요.<br>
            <span style="font-size: 0.9em; color: #6b7280;">(최초 1회 브라우저에 API 키 설정이 필요합니다.)</span>
        </div>
    </div>
    <div class="chat-input-area">
        <input type="text" id="chat-input" placeholder="질문을 입력하세요...">
        <button onclick="sendChatMessage()">전송</button>
    </div>
</div>

<script>
    function checkPassword() {
        const input = document.getElementById('pw-input').value;
        const _hash = [0x1e, 0x18, 0x1a, 0x19], _k = 0x2a; 
        let isAuth = (input.length === _hash.length);
        if (isAuth) {
            for (let i = 0; i < _hash.length; i++) {
                if ((input.charCodeAt(i) ^ _k) !== _hash[i]) { isAuth = false; break; }
            }
        }
        if (isAuth) {
            document.getElementById('lock-screen').style.display = 'none';
            sessionStorage.setItem('isUnlocked', 'true');
        } else document.getElementById('pw-error').style.display = 'block';
    }
    
    window.onload = function() {
        if (sessionStorage.getItem('isUnlocked') === 'true') document.getElementById('lock-screen').style.display = 'none';
        document.getElementById('pw-input').addEventListener('keydown', function (e) { 
            if (e.key === 'Enter' && !e.isComposing) checkPassword(); 
        });
    }
    
    function toggleChatbot() {
        const win = document.getElementById('chatbot-window');
        if (win.style.display === 'none' || win.style.display === '') {
            win.style.display = 'flex';
            document.getElementById('chat-input').focus();
        } else {
            win.style.display = 'none';
        }
    }

    function toggleChatSize() {
        const win = document.getElementById('chatbot-window');
        const btn = document.getElementById('chat-resize-btn');
        win.classList.toggle('expanded');
        
        if (win.classList.contains('expanded')) {
            btn.innerText = '🗗'; 
            btn.title = '원래 크기로';
        } else {
            btn.innerText = '🗖'; 
            btn.title = '크게 보기';
        }
    }

    function clearChat() {
        if (confirm("대화 내용을 모두 지우고 초기화하시겠습니까?")) {
            chatHistory = [];
            const historyEl = document.getElementById('chat-history');
            historyEl.innerHTML = `
                <div class="chat-msg ai">
                    안녕하세요! 경제 시황과 차트 추세(기술적 흐름)를 객관적으로 분석하는 AI 챗봇입니다.<br><br>
                    오늘의 증시 방향성, 각 지수의 상승/하락 차트 추세 판단, 스크랩된 15개 최신 기사 본문 요약에 대해 자유롭게 질문해주세요.<br>
                    <span style="font-size: 0.9em; color: #6b7280;">(최초 1회 브라우저에 API 키 설정이 필요합니다.)</span>
                </div>
            `;
        }
    }
    
    function toggleAiSection() {
        const content = document.getElementById('ai-section-content');
        const icon = document.getElementById('ai-toggle-icon');
        if (content.style.display === 'none') {
            content.style.display = 'block';
            icon.innerText = '▼';
        } else {
            content.style.display = 'none';
            icon.innerText = '▶';
        }
    }
</script>

{% macro render_metric(label, data_obj, is_int=False, suffix='') %}
    {% set has_ticker = data_obj is mapping and data_obj.get('ticker') %}
    {% if has_ticker %}<a href="https://kr.tradingview.com/chart/?symbol={{ data_obj.ticker }}" target="_blank" class="card-link">{% endif %}
    <div class="card">
        <div class="card-label">{{ label }} {% if data_obj is mapping and data_obj.get('near_52w_high') %}<span title="52주 신고가 근접">🔥</span>{% endif %}</div>
        {% if data_obj is mapping and data_obj.get('value') != "N/A" %}
            <div class="card-value">{% if is_int %}{{ "{:,}".format(data_obj.value|int) }}{% else %}{{ "{:,.2f}".format(data_obj.value) }}{% endif %}{{ suffix }}
            {% if data_obj.get('rating') %} <span style="font-size:1rem; color:#6b7280;">({{ data_obj.rating }})</span>{% endif %}
            </div>
            {% set diff_val = data_obj.diff|abs %}
            {% set diff_fmt = "{:,}".format(diff_val|int) if is_int else "{:,.2f}".format(diff_val) %}
            {% if data_obj.diff > 0 %} <div class="card-delta up">▲ {{ diff_fmt }} ({{ "{:,.2f}".format(data_obj.pct|abs) }}%)</div>
            {% elif data_obj.diff < 0 %} <div class="card-delta down">▼ {{ diff_fmt }} ({{ "{:,.2f}".format(data_obj.pct|abs) }}%)</div>
            {% else %} <div class="card-delta flat">- {{ diff_fmt }} (0.00%)</div> {% endif %}
            
            {% if data_obj.get('trend') and data_obj.get('trend') != "알 수 없음" %}
            {% set trend_color = '#dc2626' if data_obj.trend == '상승추세' else ('#2563eb' if data_obj.trend == '하락추세' else '#475569') %}
            <div><span class="trend-badge" style="color: {{ trend_color }};">{{ data_obj.trend }}</span></div>
            {% endif %}
            
            <!-- 1년 그라데이션 스파크라인 SVG 및 최고/최저 마커 렌더링 부분 -->
            {% if data_obj.get('sparkline') %}
            <div style="margin-top: 25px; margin-bottom: 10px; width: 100%; height: 45px; position: relative;">
                <svg viewBox="0 0 100 100" preserveAspectRatio="none" style="width: 100%; height: 100%; overflow: visible;">
                    <defs>
                        <linearGradient id="grad_{{ data_obj.safe_id }}" x1="0%" y1="0%" x2="100%" y2="0%">
                            {% if data_obj.diff > 0 %}
                                <stop offset="0%" stop-color="#fca5a5" />
                                <stop offset="100%" stop-color="#dc2626" />
                            {% elif data_obj.diff < 0 %}
                                <stop offset="0%" stop-color="#93c5fd" />
                                <stop offset="100%" stop-color="#2563eb" />
                            {% else %}
                                <stop offset="0%" stop-color="#d1d5db" />
                                <stop offset="100%" stop-color="#6b7280" />
                            {% endif %}
                        </linearGradient>
                    </defs>
                    <polyline fill="none" stroke="url(#grad_{{ data_obj.safe_id }})" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke" points="{{ data_obj.sparkline }}"></polyline>
                </svg>
                
                <!-- 최저점 마커 -->
                <div style="position: absolute; left: {{ data_obj.min_x }}%; top: {{ data_obj.min_y }}%; transform: translate(-50%, -50%); pointer-events: none; z-index: 5;">
                    <div style="width: 6px; height: 6px; background: #2563eb; border-radius: 50%; box-shadow: 0 0 0 2px #ffffff; margin: 0 auto;"></div>
                    <div style="position: absolute; top: 12px; left: 50%; transform: translateX(-50%); font-size: 0.75rem; color: #2563eb; font-weight: 800; white-space: nowrap; background: rgba(255, 255, 255, 0.85); padding: 2px 5px; border-radius: 4px; line-height: 1;">
                        최저 {% if is_int %}{{ "{:,}".format(data_obj.min_val|int) }}{% else %}{{ "{:,.2f}".format(data_obj.min_val) }}{% endif %}
                    </div>
                </div>

                <!-- 최고점 마커 -->
                <div style="position: absolute; left: {{ data_obj.max_x }}%; top: {{ data_obj.max_y }}%; transform: translate(-50%, -50%); pointer-events: none; z-index: 5;">
                    <div style="width: 6px; height: 6px; background: #dc2626; border-radius: 50%; box-shadow: 0 0 0 2px #ffffff; margin: 0 auto;"></div>
                    <div style="position: absolute; bottom: 12px; left: 50%; transform: translateX(-50%); font-size: 0.75rem; color: #dc2626; font-weight: 800; white-space: nowrap; background: rgba(255, 255, 255, 0.85); padding: 2px 5px; border-radius: 4px; line-height: 1;">
                        최고 {% if is_int %}{{ "{:,}".format(data_obj.max_val|int) }}{% else %}{{ "{:,.2f}".format(data_obj.max_val) }}{% endif %}
                    </div>
                </div>
            </div>
            {% endif %}
            
        {% else %}
            <div class="card-value" style="font-size: 1.5rem; color:#9ca3af;">조회 불가</div>
        {% endif %}
    </div>
    {% if has_ticker %}</a>{% endif %}
{% endmacro %}

<div class="container">
    <div class="header-wrapper">
        <div class="header-title">📊 실시간 미국 증시 대시보드</div>
        <button class="refresh-btn" onclick="location.reload();">🔄 새로고침</button>
    </div>

    <!-- 실시간 주가 티커 위젯 -->
    <div class="tradingview-widget-container" style="margin-bottom: 30px; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);">
      <div class="tradingview-widget-container__widget"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/tv-widget-ticker-tape.js" async>
      {
      "symbols": [
        { "proName": "FOREXCOM:SPXUSD", "title": "S&P 500" },
        { "proName": "FOREXCOM:NSXUSD", "title": "나스닥 100" },
        { "proName": "NASDAQ:NVDA", "title": "엔비디아" },
        { "proName": "NASDAQ:AAPL", "title": "애플" },
        { "proName": "NASDAQ:MSFT", "title": "마이크로소프트" },
        { "proName": "NASDAQ:TSLA", "title": "테슬라" },
        { "proName": "KRX:005930", "title": "삼성전자" }
      ],
      "showSymbolLogo": true,
      "isTransparent": false,
      "displayMode": "adaptive",
      "colorTheme": "light",
      "locale": "kr"
    }
      </script>
    </div>
    
    <div class="section-title ai-toggle-title" onclick="toggleAiSection()">
        <span>✨ 🤖 AI 오늘의 증시 브리핑</span>
        <span id="ai-toggle-icon" style="font-size: 1.2rem; padding-right: 10px;">▼</span>
    </div>
    
    <div class="list-box" id="ai-section-content" style="margin-bottom: 40px;">
        <p id="ai-summary-text" style="white-space: pre-wrap; font-size: 1.2rem; font-weight: 500; line-height: 1.8;">{{ data.ai_summary }}</p>
    </div>

    <div class="section-title" style="margin-top:0;">📅 이번 주 경제 지표</div>
    <div class="list-box" style="margin-bottom: 30px;">
        {% for event in data.calendar %}
        <div class="cal-item">{{ event.title }}</div>
        {% endfor %}
    </div>

    <div class="section-title" style="margin-top:0;">📰 최신 경제 뉴스 (15개)</div>
    <div class="list-box news-container" style="margin-bottom: 40px;">
        {% for item in data.news %}
        <div class="news-item" data-content="{{ item.content }}">
            <a href="{{ item.link }}" target="_blank" class="news-link">{{ item.title }}</a>
            <span class="news-date">({{ item.date }})</span>
        </div>
        {% endfor %}
    </div>

    <div class="section-title">📈 1. 주요 지수</div>
    <div class="grid">
        {{ render_metric('S&P 500', data.indices['S&P 500']) }}
        {{ render_metric('다우존스', data.indices['다우존스']) }}
        {{ render_metric('나스닥 100', data.indices['나스닥 100']) }}
        {{ render_metric('반도체', data.indices['필라델피아 반도체']) }}
        {{ render_metric('니케이 225', data.indices['니케이 225']) }}
        {{ render_metric('대만 가권', data.indices['대만 가권']) }}
        {{ render_metric('코스피 야간(EWY)', data.indices['코스피 야간선물']) }}
    </div>
    
    <div class="section-title">🌐 2. 매크로 및 시장 심리</div>
    <div class="grid">
        {{ render_metric('달러 인덱스', data.macros['달러 인덱스']) }}{{ render_metric('원/달러', data.macros['원/달러 환율'], False, '원') }}{{ render_metric('미국채 10년', data.macros['미국채 10년물'], False, '%') }}{{ render_metric('빅스(VIX)', data.macros['빅스(VIX)']) }}
        {{ render_metric('CNN 공포지수', data.cnn, True) }}
    </div>

    <div class="section-title">💧 3. 연준(FED) 유동성 지표</div>
    <div class="grid">
        {% if data.fed %}
            {{ render_metric('순유동성(Net)', data.fed['Net Liquidity'], True, 'M$') }}
            {{ render_metric('역레포(RRP)', data.fed['Reverse Repo'], True, 'M$') }}
            {{ render_metric('TGA 잔액', data.fed['TGA'], True, 'M$') }}
            {{ render_metric('총 자산', data.fed['Total Assets'], True, 'M$') }}
        {% else %}
            <div class="card"><div class="card-label">연준 유동성</div><div class="card-value" style="font-size: 1.5rem; color:#9ca3af;">조회 불가</div></div>
        {% endif %}
    </div>

    <div class="section-title">🛢️ 4. 원자재 및 귀금속</div>
    <div class="grid">
        {{ render_metric('WTI유', data.commodities['WTI유'], False, '$') }}
        {{ render_metric('브렌트유', data.commodities['브렌트유'], False, '$') }}
        {{ render_metric('금(1돈)', data.gold, True, '원') }}
        {{ render_metric('은(1돈)', data.silver, True, '원') }}
        {{ render_metric('구리(파운드)', data.copper, True, '원') }}
    </div>

    <div class="section-title">💻 5. 빅테크 & 소프트웨어</div>
    <div class="grid">{% for name, obj in data.tech_soft.items() %}{{ render_metric(name, obj, False, '$') }}{% endfor %}</div>
    <div class="section-title">🧠 6. 반도체 & AI 하드웨어</div>
    <div class="grid">{% for name, obj in data.semi_ai.items() %}{{ render_metric(name, obj, False, '$') }}{% endfor %}</div>
    <div class="section-title">⚡ 7. 에너지 & 인프라</div>
    <div class="grid">{% for name, obj in data.energy_infra.items() %}{{ render_metric(name, obj, False, '$') }}{% endfor %}</div>
    <div class="section-title">🏥 8. 제약 & 헬스케어</div>
    <div class="grid">{% for name, obj in data.health.items() %}{{ render_metric(name, obj, False, '$') }}{% endfor %}</div>
    <div class="section-title">🚀 9. 우주항공 & 모빌리티</div>
    <div class="grid">{% for name, obj in data.space_mobility.items() %}{{ render_metric(name, obj, False, '$') }}{% endfor %}</div>
    <div class="section-title">🏦 10. 금융 & 투자</div>
    <div class="grid">{% for name, obj in data.finance.items() %}{{ render_metric(name, obj, False, '$') }}{% endfor %}</div>
    <div class="section-title">🛍️ 11. 소비재 & 리테일</div>
    <div class="grid">{% for name, obj in data.consumer.items() %}{{ render_metric(name, obj, False, '$') }}{% endfor %}</div>
</div>

<script>
    let chatHistory = [];
    
    async function sendChatMessage() {
        const inputEl = document.getElementById('chat-input');
        const message = inputEl.value.trim();
        
        if (!message) {
            alert("💬 질문을 먼저 입력해주세요!");
            inputEl.focus();
            return;
        }

        let apiKey = localStorage.getItem('gemini_api_key');
        if (!apiKey) {
            apiKey = prompt("AI 채팅을 사용하려면 Gemini API 키를 입력해주세요.\\n(키는 브라우저에만 안전하게 저장됩니다.)");
            if (!apiKey) return;
            localStorage.setItem('gemini_api_key', apiKey.trim());
        }

        if (chatHistory.length === 0) {
            const summaryText = document.getElementById('ai-summary-text').innerText;
            
            const newsNodes = document.querySelectorAll('.news-item');
            const newsList = Array.from(newsNodes).map((node, index) => {
                const title = node.querySelector('.news-link').innerText.replace(/\\n/g, ' ');
                const content = node.getAttribute('data-content') || "본문 요약 정보 없음";
                return `[뉴스 ${index + 1}] 제목: ${title}\\n핵심내용(기사 원문): ${content}`;
            }).join('\\n\\n');
            
            const calNodes = document.querySelectorAll('.cal-item');
            const calList = Array.from(calNodes).map(node => node.innerText).join('\\n- ');
            
            let trendInfos = "";
            document.querySelectorAll('.card').forEach(card => {
                const label = card.querySelector('.card-label')?.innerText.replace('🔥', '').trim();
                const trend = card.querySelector('.trend-badge')?.innerText;
                if(label && trend) {
                    trendInfos += `- ${label}: ${trend}\\n`;
                }
            });

            const today = new Date();
            const todayDateStr = `${today.getFullYear()}년 ${today.getMonth() + 1}월 ${today.getDate()}일`;
            
            const initialPrompt = `당신은 최고 수준의 객관성을 갖춘 거시경제 및 리스크 분석 AI입니다.
현재 기준 날짜는 [${todayDateStr}]입니다. 대화 시 반드시 이 날짜를 '오늘'로 인지하고 답변하세요.

아래 제공된 데이터를 바탕으로 사용자의 질문에 심도 있게 답하세요.

[★할루시네이션(정보 왜곡) 절대 차단 규칙★]
1. 답변 시 스스로 정보를 지어내지 말고, 반드시 아래 제공된 팩트 데이터와 당신(AI)이 가지고 있는 최신정보들을 기반으로 사실 관계를 확인하고 근거하세요.
2. 사용자가 지수 방향성이나 특정 종목군을 물어볼 때, 제공된 '각 지수 및 종목의 차트 추세(상승/하락/횡보)' 데이터를 적극 활용하여 기술적 흐름을 반영한 분석을 제공하세요.
3. 뉴스를 물어보면 제목만 보지 말고 '핵심내용(기사 원문)'을 정독한 후 구체적인 수치와 이유를 들어 답변하세요.
4. 마크다운 기호를 쓰지 말고 번호(1., 2. 등)를 매겨서 깔끔하게 답변하세요.

[현재 시장 기준 데이터]
- 오늘의 증시 요약: \\n${summaryText}\\n
- 각 지수별 실시간 차트 추세 (5일선/20일선 기준): \\n${trendInfos}\\n
- 최신 경제 뉴스 (기사 본문 요약 15개): \\n${newsList}\\n
- 주요 경제 지표: \\n- ${calList}\\n

위 내용을 모두 숙지했다면 즉시 분석 답변을 시작할 준비가 되었다고 짧게 응답하세요.`;
            
            chatHistory.push({ "role": "user", "parts": [{ "text": initialPrompt }] });
            chatHistory.push({ "role": "model", "parts": [{ "text": "네, 제공된 데이터와 기사 본문 요약, 그리고 실시간 차트 추세(기술적 흐름) 정보까지 모두 숙지했습니다. 팩트 기반의 심층 분석을 제공해 드릴 준비가 되었습니다. 무엇이 궁금하신가요?" }] });
        }

        appendMessage('user', message);
        inputEl.value = '';
        chatHistory.push({ "role": "user", "parts": [{ "text": message }] });
        
        const loadingId = 'msg-' + Date.now();
        appendMessage('ai', '실시간 차트 추세와 기사 원문을 바탕으로 분석 중...', loadingId);

        try {
            let response = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent?key=${apiKey}`, {
                method: 'POST', 
                headers: { 'Content-Type': 'application/json' }, 
                body: JSON.stringify({ contents: chatHistory })
            });
            
            let data = await response.json();
            
            if (!response.ok) {
                response = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent?key=${apiKey}`, {
                    method: 'POST', 
                    headers: { 'Content-Type': 'application/json' }, 
                    body: JSON.stringify({ contents: chatHistory })
                });
                data = await response.json();
                if (!response.ok) throw new Error(data.error?.message || '알 수 없는 API 오류가 발생했습니다.');
            }

            const replyText = data.candidates[0].content.parts[0].text;
            chatHistory.push({ "role": "model", "parts": [{ "text": replyText }] });
            updateMessage(loadingId, replyText);
            
        } catch (error) {
            console.error("API 통신 에러:", error);
            chatHistory.pop(); 
            updateMessage(loadingId, `🚨 오류 발생: ${error.message}<br>잠시 서버 트래픽 지연이 발생했습니다. 새로고침 후 다시 시도해주세요.`);
        }
    }
    
    function appendMessage(role, text, id = null) {
        const historyEl = document.getElementById('chat-history');
        const msgDiv = document.createElement('div');
        msgDiv.className = 'chat-msg ' + role;
        if (id) msgDiv.id = id;
        msgDiv.innerHTML = text.replace(/\\n/g, '<br>');
        historyEl.appendChild(msgDiv); 
        
        historyEl.scrollTop = historyEl.scrollHeight;
    }
    
    function updateMessage(id, text) {
        const historyEl = document.getElementById('chat-history');
        const msgDiv = document.getElementById(id);
        
        if (msgDiv) {
            msgDiv.innerHTML = text.replace(/\\n/g, '<br>');
            historyEl.scrollTo({
                top: msgDiv.offsetTop - 15,
                behavior: 'smooth'
            });
        }
    }
    
    document.getElementById('chat-input').addEventListener('keydown', e => { 
        if (e.key === 'Enter' && !e.isComposing) {
            e.preventDefault();
            sendChatMessage(); 
        }
    });
</script>
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
