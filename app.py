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
    
    # 야후 파이낸스 티커를 트레이딩뷰 심볼로 변환하는 매핑 딕셔너리
    tv_mapping = {
        '^GSPC': 'SPX',
        '^DJI': 'DJI',
        '^NDX': 'NDX',
        '^SOX': 'SOX',
        '^NBI': 'NBI',
        'DX-Y.NYB': 'DXY',
        '^TNX': 'US10Y',
        '^TYX': 'US30Y',
        '^VIX': 'VIX',
        'CL=F': 'USOIL',
        'BZ=F': 'UKOIL',
        'KRW=X': 'USDKRW',
        'JPY=X': 'USDJPY'
    }
    
    for name, ticker in tickers.items():
        tv_ticker = tv_mapping.get(ticker, ticker)
        try:
            hist = yf.Ticker(ticker).history(period="1y")
            if 'Close' in hist.columns and len(hist) >= 2:
                close_prices = hist['Close'].dropna()
                high_prices = hist['High'].dropna()
                
                if len(close_prices) >= 2:
                    current = float(close_prices.iloc[-1])
                    prev = float(close_prices.iloc[-2])
                    diff = current - prev
                    pct = (diff / prev) * 100 if prev != 0 else 0
                    
                    fifty_two_week_high = float(high_prices.max())
                    near_52w_high = current >= (fifty_two_week_high * 0.97)
                    
                    data[name] = {
                        'value': current, 
                        'diff': diff, 
                        'pct': pct, 
                        'near_52w_high': near_52w_high,
                        'ticker': tv_ticker
                    }
                    continue
            data[name] = {'value': "N/A", 'diff': 0, 'pct': 0, 'near_52w_high': False, 'ticker': tv_ticker}
        except:
            data[name] = {'value': "N/A", 'diff': 0, 'pct': 0, 'near_52w_high': False, 'ticker': tv_ticker}
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
        today_str = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y년 %m월 %d일")
        fed_net = f"{int(data['fed']['Net Liquidity']['value']):,} 백만 달러" if data.get('fed') else "조회 불가"
        fed_rrp = f"{int(data['fed']['Reverse Repo']['value']):,} 백만 달러" if data.get('fed') else "조회 불가"
        
        prompt = f"""
        [분석 기준 날짜: {today_str}]
        당신은 전세계 0.1% 거시경제 및 금융 애널리스트입니다. 아래 제공된 간밤의 미국 증시 및 전세계 매크로 데이터, 미국정치, 미국경제, 전 세계 지정학적 리스크, 국제유가를 심층 분석하여, 오늘 아침 한국 증시(코스피/코스닥) 개장을 준비하는 투자자들이 반드시 알아야 할 '핵심 인사이트와 시장 전망'을 도출해주세요.

        [분석 포인트]
        1. 지수 흐름: 분석 날짜 기준 S&P 500과 나스닥 지수를 분석하고 한국 증시의 주요 섹터(반도체, 수출주 등)에 미칠 방향성
        2. 매크로 및 환율: 미국채 금리와 원/달러 환율 변동이 국내 증시 외국인 수급에 미칠 파급력
        3. 투심 및 유동성: VIX, 공포탐욕지수, 연준 순유동성(Net Liquidity) 및 역레포(ON RRP) 추이를 바탕으로 한 글로벌 자금 환경 진단
        4. 정치, 경제 및 지정학적 리스크, 국제유가 : 분석 날짜 기준 S&P 500과 나스닥이 어떤 이유에서 상승과 하락하였는지 분석
        5. 미국 주요 경제지표 : 분석 날짜 기준으로 발표 예정인 미국 주요 경제지표에 따라 국내 증시의 영향에 대한 분석 

        [작성 지침]
        1. 전체 분량은 15문장 내외의 매끄러운 단일 문단(줄글)으로만 작성할 것.
        2. 마크다운 기호(*, #, - 등)는 일절 사용하지 말 것.
        3. 단순 수치 나열을 피하고 객관적이고 전문적인 보고서 어조를 유지할 것.
        4. 작성한 것에 대한 근거를 반드시 포함 할 것.
        
        [오늘의 데이터]
        - S&P 500: {data['indices'].get('S&P 500', {}).get('value')}
        - 나스닥 100: {data['indices'].get('나스닥 100', {}).get('value')}
        - 미국채 10년물 금리: {data['macros'].get('미국채 10년물', {}).get('value')}%
        - 원/달러 환율: {data['macros'].get('원/달러 환율', {}).get('value')}원
        - VIX 지수: {data['macros'].get('빅스(VIX)', {}).get('value')}
        - WTI유: {data['commodities'].get('WTI유', {}).get('value')}달러
        - 브렌트유: {data['commodities'].get('브렌트유', {}).get('value')}달러
        - CNN 공포탐욕지수: {data['cnn'].get('score') if data.get('cnn') else '조회 불가'}
        - 연준 순유동성: {fed_net}
        - 연준 역레포 잔액: {fed_rrp}
        """
        
        models_to_try = ['gemini-3.6-flash', 'gemini-3.5-flash-lite', 'gemini-3-flash']
        last_error = ""
        for model_name in models_to_try:
            try:
                print(f"🤖 {model_name} 모델로 분석 시도 중...")
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(prompt)
                return response.text.strip()
            except Exception as e:
                print(f"⚠️ {model_name} 실패: {e}")
                last_error = str(e)
                time.sleep(2.0)
                continue
        return f"⚠️ AI 분석 실패 (사유: {last_error})"
    except Exception as e:
        return f"⚠️ AI 설정 중 오류가 발생했습니다: {e}"

# --- 메모리 캐시 ---
CACHE = {}

def get_dashboard_data():
    if 'data' in CACHE and time.time() - CACHE['time'] < 600: return CACHE['data']
    
    data = {
        'indices': fetch_yfinance_data({'S&P 500': '^GSPC', '다우존스': '^DJI', '나스닥 100': '^NDX', '필라델피아 반도체': '^SOX', '나스닥 생명공학': '^NBI'}),
        'macros': fetch_yfinance_data({'달러 인덱스': 'DX-Y.NYB', '원/달러 환율': 'KRW=X', '엔/달러 환율': 'JPY=X', '미국채 10년물': '^TNX', '미국채 30년물': '^TYX', '빅스(VIX)': '^VIX'}),
        'cnn': get_fear_and_greed(),
        'commodities': fetch_yfinance_data({'WTI유': 'CL=F', '브렌트유': 'BZ=F'}),
        'copper': get_copper_krw_price(),
        'silver': get_silver_don_price(),
        'gold': get_gold_don_price(),
        'fed': get_fed_liquidity(),
        
        'tech_soft': fetch_yfinance_data({
            'Apple': 'AAPL', 'Microsoft': 'MSFT', 'Alphabet': 'GOOGL', 'Amazon': 'AMZN', 
            'Meta': 'META', 'Oracle': 'ORCL', '크라우드스트라이크': 'CRWD', '클라우드플레어': 'NET', 
            '세일스포스': 'CRM', '팔로알토 네트웍스': 'PANW', '앱러빈': 'APP', '넷플릭스': 'NFLX'
        }),
        'semi_ai': fetch_yfinance_data({
            'NVIDIA': 'NVDA', 'AMD': 'AMD', 'TSMC': 'TSM', 'Micron': 'MU', '인텔': 'INTC', 
            '퀄컴': 'QCOM', '브로드컴': 'AVGO', 'ASML': 'ASML', '램리서치': 'LRCX', 
            'Palantir': 'PLTR', '템퍼스 AI': 'TEM', '웨스턴디지털': 'WDC', '셀레스티카': 'CLS',
            '델테크놀로지': 'DELL'
        }),
        'energy_infra': fetch_yfinance_data({
            '엑슨모빌': 'XOM', '셰브론': 'CVX', 'GE버노바': 'GEV', '뉴스케일파워': 'SMR', '오클로': 'OKLO', 
            'T1에너지': 'TE', '비스트라 에너지': 'VST', '블룸에너지': 'BE', 'BWX 테크놀로지스': 'BWXT', 
            '버티브홀딩스': 'VRT', '콴타서비시스': 'PWR', '카메코': 'CCJ', '파월 인더스트리스': 'POWL', '마스텍': 'MTZ'
        }),
        'health': fetch_yfinance_data({
            'Eli Lilly': 'LLY', '화이자': 'PFE', '존슨앤드존슨': 'JNJ', '유나이티드헬스': 'UNH', '모더나': 'MRNA', '암젠': 'AMGN'
        }),
        'space_mobility': fetch_yfinance_data({
            'Tesla': 'TSLA', '스페이스X': 'SPCX', '로켓랩': 'RKLB', 'GE에어로스페이스': 'GE'
        }),
        'finance': fetch_yfinance_data({
            'JP모건': 'JPM', '뱅크오브아메리카': 'BAC', '웰스파고': 'WFC', '모건스탠리': 'MS', '찰스슈왑': 'SCHW',
            '비자': 'V', '마스터카드': 'MA', '버크셔해서웨이': 'BRK-B', '블랙록': 'BLK', 'KKR & CO': 'KKR'
        }),
        'consumer': fetch_yfinance_data({
            '월마트': 'WMT', '코스트코': 'COST', '코카콜라': 'KO', '펩시코': 'PEP', '맥도날드': 'MCD'
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
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>실시간 미국 증시 대시보드</title>

    <meta name="theme-color" content="#f3f4f6">
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="미국증시">
    <link rel="apple-touch-icon" href="https://cdn-icons-png.flaticon.com/512/2942/2942269.png">
    <link rel="manifest" href="./manifest.json">

    <link rel="stylesheet" as="style" crossorigin href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css" />
    <style>
        body { 
            font-family: 'Pretendard', sans-serif; background-color: #f3f4f6; color: #1f2937; margin: 0; padding: 10px; 
            -webkit-tap-highlight-color: transparent; -webkit-touch-callout: none; user-select: none; 
            padding-bottom: env(safe-area-inset-bottom);
        }
        input { user-select: auto; } 

        .container { max-width: 1600px; margin: 0 auto; padding: 10px; }
        .header-title { text-align: center; font-size: 2.2rem; font-weight: 900; margin: 20px 0 30px 0; color: #111827; word-break: keep-all; }
        .section-title { font-size: 1.5rem; font-weight: 800; border-left: 6px solid #3b82f6; padding-left: 12px; margin: 30px 0 15px 0; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 15px; align-items: stretch; }
        
        .card-link { text-decoration: none; color: inherit; display: block; height: 100%; }
        .card { 
            background: #ffffff; border-radius: 12px; padding: 20px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); 
            text-align: center; height: 100%; box-sizing: border-box; 
            border: 2px solid transparent; transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease; 
        }
        .card-link:hover .card { transform: translateY(-4px); box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1); border-color: #3b82f6; }

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
        
        /* 채팅 UI 스타일 추가 */
        .chat-container { margin-top: 20px; background: #f9fafb; border-radius: 10px; padding: 15px; border: 1px solid #e5e7eb; }
        .chat-history { max-height: 350px; overflow-y: auto; margin-bottom: 15px; display: flex; flex-direction: column; gap: 12px; padding-right: 5px; }
        .chat-msg { padding: 12px 16px; border-radius: 14px; max-width: 85%; font-size: 1.05rem; line-height: 1.5; word-break: break-word; user-select: text; }
        .chat-msg.user { background: #3b82f6; color: white; align-self: flex-end; border-bottom-right-radius: 4px; }
        .chat-msg.ai { background: #e5e7eb; color: #1f2937; align-self: flex-start; border-bottom-left-radius: 4px; }
        .chat-input-area { display: flex; gap: 10px; }
        .chat-input-area input { flex: 1; padding: 14px; border: 1px solid #d1d5db; border-radius: 8px; font-size: 1rem; outline: none; }
        .chat-input-area input:focus { border-color: #3b82f6; box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2); }
        .chat-input-area button { padding: 12px 24px; background: #111827; color: white; border: none; border-radius: 8px; font-weight: bold; cursor: pointer; transition: background 0.2s; white-space: nowrap; }
        .chat-input-area button:hover { background: #374151; }

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
            .chat-input-area { flex-direction: column; }
        }
    </style>
</head>
<body>
<!-- 🔐 비밀번호 잠금 화면 -->
<div id="lock-screen" style="position: fixed; top: 0; left: 0; width: 100%; height: 100%; background-color: #f3f4f6; z-index: 9999; display: flex; flex-direction: column; justify-content: center; align-items: center;">
    <div style="background: white; padding: 40px; border-radius: 15px; box-shadow: 0 10px 25px rgba(0,0,0,0.1); text-align: center;">
        <h2 style="margin-top: 0; margin-bottom: 20px; color: #111827; font-weight: 800;">🔒 대시보드 잠금</h2>
        <input type="password" id="pw-input" placeholder="비밀번호를 입력하세요" style="width: 100%; box-sizing: border-box; padding: 12px; font-size: 1.1rem; border: 1.5px solid #d1d5db; border-radius: 8px; margin-bottom: 15px; outline: none; text-align: center;">
        <button onclick="checkPassword()" style="width: 100%; padding: 12px; font-size: 1.1rem; background-color: #3b82f6; color: white; border: none; border-radius: 8px; cursor: pointer; font-weight: bold;">입장하기</button>
        <p id="pw-error" style="color: #ef4444; margin-top: 15px; font-weight: 600; display: none;">비밀번호가 틀렸습니다.</p>
    </div>
</div>

<script>
    function checkPassword() {
        const input = document.getElementById('pw-input').value;
        const _hash = [0x1e, 0x18, 0x1a, 0x19]; 
        const _k = 0x2a; 
        let isAuth = (input.length === _hash.length);
        if (isAuth) {
            for (let i = 0; i < _hash.length; i++) {
                if ((input.charCodeAt(i) ^ _k) !== _hash[i]) {
                    isAuth = false; break;
                }
            }
        }
        if (isAuth) {
            document.getElementById('lock-screen').style.display = 'none';
            sessionStorage.setItem('isUnlocked', 'true');
        } else {
            document.getElementById('pw-error').style.display = 'block';
        }
    }
    window.onload = function() {
        if (sessionStorage.getItem('isUnlocked') === 'true') {
            document.getElementById('lock-screen').style.display = 'none';
        }
        document.getElementById('pw-input').addEventListener('keypress', function (e) {
            if (e.key === 'Enter') checkPassword();
        });
    }
</script>

<!-- 매크로: 52주 신고가 근접(3% 이내) 시 불꽃 마크 및 트레이딩뷰 링크 연결 -->
{% macro render_metric(label, data_obj, is_int=False, suffix='') %}
    {% set has_ticker = data_obj is mapping and data_obj.get('ticker') %}
    {% if has_ticker %}
    <a href="https://kr.tradingview.com/chart/?symbol={{ data_obj.ticker }}" target="_blank" class="card-link" title="트레이딩뷰 차트 보기">
    {% endif %}
    
    <div class="card">
        <div class="card-label">
            {{ label }}
            {% if data_obj is mapping and data_obj.get('near_52w_high') %}
                <span title="52주 신고가(3% 이내) 근접" style="font-size: 1.2rem; margin-left: 2px;">🔥</span>
            {% endif %}
        </div>
        {% if data_obj is mapping and data_obj.get('value') != "N/A" and data_obj.get('value') is not none %}
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
    
    {% if has_ticker %}</a>{% endif %}
{% endmacro %}

<div class="container">
    <div class="header-title">📊 실시간 미국 증시 대시보드</div>

    <div class="section-title" style="margin-top: 0; border-left-color: #8b5cf6; color: #6d28d9;">✨ 🤖 AI 오늘의 증시 3줄 요약</div>
    <div class="list-box" style="margin-bottom: 0; background: linear-gradient(145deg, #f3f4f6, #ffffff); border: 2px solid #e5e7eb;">
        <p style="white-space: pre-wrap; font-size: 1.2rem; font-weight: 600; line-height: 1.8; color: #374151; margin: 0;" id="ai-summary-text">{{ data.ai_summary }}</p>
        
        <!-- 💬 AI 대화창 UI -->
        <hr style="border: 0; height: 1px; background: #d1d5db; margin: 25px 0;">
        <h3 style="margin: 0 0 12px 0; font-size: 1.3rem; color: #111827;">💬 AI와 시황 대화하기</h3>
        <div class="chat-container">
            <div id="chat-history" class="chat-history">
                <div class="chat-msg ai">오늘의 증시 요약 내용을 바탕으로 대답해 드릴 준비가 되었습니다. 궁금하신 점이나 특정 종목에 대해 자유롭게 물어보세요!</div>
            </div>
            <div class="chat-input-area">
                <input type="text" id="chat-input" placeholder="예: 오늘 나스닥이 왜 올랐어? 반도체 관련 이슈는?">
                <button onclick="sendChatMessage()">질문하기</button>
            </div>
        </div>
    </div>

    <!-- AI 요약 아래로 이동된 뉴스 및 캘린더 -->
    <div class="dual-grid" style="margin-top: 20px; margin-bottom: 40px;">
        <div>
            <div class="section-title" style="margin-top:0;">📰 주요 경제 및 빅테크 뉴스</div>
            <div class="list-box">
                {% if data.news %}
                    {% for item in data.news %}
                        <div class="news-item"><a href="{{ item.link }}" target="_blank" class="news-link">{{ item.title }}</a><br><span class="news-date">({{ item.date }})</span></div>
                    {% endfor %}
                {% endif %}
            </div>
        </div>
        <div>
            <div class="section-title" style="margin-top:0;">📅 주간 주요 달러(USD) 경제 지표</div>
            <div class="list-box">
                {% if data.calendar %}
                    {% for event in data.calendar %}
                        <div class="cal-item">{{ event.title }}</div>
                    {% endfor %}
                {% endif %}
            </div>
        </div>
    </div>

    <!-- 1. 지수 -->
    <div class="section-title">📈 1. 미국 주요 지수</div>
    <div class="grid">
        {{ render_metric('S&P 500', data.indices['S&P 500']) }}
        {{ render_metric('다우존스', data.indices['다우존스']) }}
        {{ render_metric('나스닥 100', data.indices['나스닥 100']) }}
        {{ render_metric('필라델피아 반도체', data.indices['필라델피아 반도체']) }}
        {{ render_metric('나스닥 생명공학', data.indices['나스닥 생명공학']) }}
    </div>

    <!-- 2. 매크로 -->
    <div class="section-title">🌐 2. 매크로 및 시장 심리 지표</div>
    <div class="grid">
        {{ render_metric('달러 인덱스', data.macros['달러 인덱스']) }}
        {{ render_metric('원/달러 환율', data.macros['원/달러 환율'], False, '원') }}
        {{ render_metric('엔/달러 환율', data.macros['엔/달러 환율'], False, '엔') }}
        {{ render_metric('미국채 10년물 (%)', data.macros['미국채 10년물'], False, '%') }}
        {{ render_metric('미국채 30년물 (%)', data.macros['미국채 30년물'], False, '%') }}
        {{ render_metric('빅스(VIX) 지수', data.macros['빅스(VIX)']) }}
        <div class="card" style="height: 100%; box-sizing: border-box;">
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

    <!-- 3. 원자재 -->
    <div class="section-title">🛢️ 3. 원자재 및 귀금속 시세</div>
    <div class="grid">
        {{ render_metric('WTI유 ($/bbl)', data.commodities['WTI유']) }}
        {{ render_metric('브렌트유 ($/bbl)', data.commodities['브렌트유']) }}
        {{ render_metric('구리 가격 (lb)', data.copper, True, '원') }}
        {{ render_metric('국내 금시세 (1돈)', data.gold, True, '원') }}
        {{ render_metric('국내 은시세 (1돈)', data.silver, True, '원') }}
    </div>

    <!-- 4. 연준 -->
    <div class="section-title">🏦 4. 연준(Fed) 유동성 현황 (단위: 백만 $)</div>
    {% if data.fed %}
    <div class="grid">
        {{ render_metric('순유동성 (Net Liquidity)', data.fed['Net Liquidity'], True) }}
        {{ render_metric('역레포 잔액 (ON RRP)', data.fed['Reverse Repo'], True) }}
        {{ render_metric('은행 지급준비금', data.fed['Bank Reserves'], True) }}
        {{ render_metric('재무부 일반계정 (TGA)', data.fed['TGA'], True) }}
    </div>
    {% endif %}

    <!-- 5~11. 섹터별 관심 종목 -->
    <div class="section-title">💻 5. 빅테크 & 소프트웨어</div>
    <div class="grid">{% for name, obj in data.tech_soft.items() %}{{ render_metric(name, obj, False, '$') }}{% endfor %}</div>
    <div class="section-title">🧠 6. 반도체 & AI 하드웨어</div>
    <div class="grid">{% for name, obj in data.semi_ai.items() %}{{ render_metric(name, obj, False, '$') }}{% endfor %}</div>
    <div class="section-title">⚡ 7. 원자력, 에너지 & 인프라</div>
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

<!-- 채팅 기능 스크립트 -->
<script>
    const GEMINI_API_KEY = "{{ api_key }}";
    
    // AI 요약 내용을 프롬프트 컨텍스트에 삽입
    const summaryText = document.getElementById('ai-summary-text').innerText;
    let chatHistory = [
        {
            "role": "user",
            "parts": [{ "text": `너는 거시경제 및 금융 애널리스트야. 다음은 오늘 아침 생성된 미국 증시 요약 내용이야. 이 내용을 바탕으로 나의 질문에 전문적이고 친절하게 대답해줘.\n\n[오늘의 증시 요약]\n${summaryText}` }]
        },
        {
            "role": "model",
            "parts": [{ "text": "네, 오늘의 증시 요약 내용을 완벽히 숙지했습니다. 시장 상황이나 특정 섹터에 대해 궁금한 점을 질문해 주시면 자세히 답변해 드리겠습니다." }]
        }
    ];

    async function sendChatMessage() {
        if (!GEMINI_API_KEY) {
            alert("API 키가 설정되지 않아 채팅을 사용할 수 없습니다.");
            return;
        }

        const inputEl = document.getElementById('chat-input');
        const message = inputEl.value.trim();
        if (!message) return;

        // 화면에 유저 메시지 표시
        appendMessageToUI('user', message);
        inputEl.value = '';

        // 기록에 유저 메시지 추가
        chatHistory.push({ "role": "user", "parts": [{ "text": message }] });

        // 화면에 로딩 상태 표시
        const loadingId = 'msg-' + Date.now();
        appendMessageToUI('ai', '생각 중...', loadingId);

        try {
            const response = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=${GEMINI_API_KEY}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ contents: chatHistory })
            });

            if (!response.ok) throw new Error('API Request Failed');
            
            const data = await response.json();
            const replyText = data.candidates[0].content.parts[0].text;

            // 기록에 AI 답변 추가
            chatHistory.push({ "role": "model", "parts": [{ "text": replyText }] });

            // 화면 업데이트
            updateMessageInUI(loadingId, replyText);
        } catch (error) {
            console.error(error);
            updateMessageInUI(loadingId, '오류가 발생했습니다. 잠시 후 다시 시도해주세요.');
        }
    }

    function appendMessageToUI(role, text, id = null) {
        const historyEl = document.getElementById('chat-history');
        const msgDiv = document.createElement('div');
        msgDiv.className = 'chat-msg ' + role;
        if (id) msgDiv.id = id;
        
        // 텍스트 내 볼드체(**)와 줄바꿈(\n)을 HTML로 치환하여 렌더링
        let formattedText = text.replace(/\*\*(.*?)\*\*/g, '<b>$1</b>').replace(/\n/g, '<br>');
        msgDiv.innerHTML = formattedText;
        
        historyEl.appendChild(msgDiv);
        historyEl.scrollTop = historyEl.scrollHeight;
    }

    function updateMessageInUI(id, text) {
        const msgDiv = document.getElementById(id);
        if (msgDiv) {
            let formattedText = text.replace(/\*\*(.*?)\*\*/g, '<b>$1</b>').replace(/\n/g, '<br>');
            msgDiv.innerHTML = formattedText;
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        const inputEl = document.getElementById('chat-input');
        if (inputEl) {
            inputEl.addEventListener('keypress', function(e) {
                if (e.key === 'Enter') sendChatMessage();
            });
        }
    });

    if ('serviceWorker' in navigator) {
        window.addEventListener('load', () => {
            navigator.serviceWorker.register('./sw.js').catch(err => {
                console.log('Service Worker registration failed: ', err);
            });
        });
    }
</script>
</body>
</html>
"""

def generate_html():
    with app.app_context():
        dashboard_data = get_dashboard_data()
        
        # 깃허브 시크릿에 등록된 API 키를 HTML로 전달 (인앱 채팅용)
        api_key = os.environ.get("GEMINI_API_KEY", "")
        
        rendered = render_template_string(HTML_TEMPLATE, data=dashboard_data, api_key=api_key)
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(rendered)

if __name__ == "__main__":
    generate_html()
