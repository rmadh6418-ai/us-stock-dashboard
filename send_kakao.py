import requests
import json
import yfinance as yf
import cloudscraper

# 1. 본인의 REST API 키 입력
REST_API_KEY = "cf664905828cfa82863a5ece28304fc8"

def refresh_token():
    with open("kakao_token.json", "r") as fp:
        tokens = json.load(fp)

    url = "https://kauth.kakao.com/oauth/token"
    data = {
        "grant_type": "refresh_token",
        "client_id": REST_API_KEY,
        "refresh_token": tokens["refresh_token"]
    }
    response = requests.post(url, data=data)
    result = response.json()

    tokens["access_token"] = result["access_token"]
    if "refresh_token" in result:
        tokens["refresh_token"] = result["refresh_token"]

    with open("kakao_token.json", "w") as fp:
        json.dump(tokens, fp)

    return tokens["access_token"]

def get_briefing_data():
    data_text = "📊 [오전 7시 미국 마감 브리핑]\n\n"
    
    try:
        sp500 = yf.Ticker("^GSPC").history(period="1d")['Close'].iloc[-1]
        krw = yf.Ticker("KRW=X").history(period="1d")['Close'].iloc[-1]
        data_text += f"✔️ S&P 500: {sp500:,.2f}\n"
        data_text += f"✔️ 원/달러 환율: {krw:,.2f}원\n"
    except:
        data_text += "✔️ 지수/환율: 조회 실패\n"
        
try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://edition.cnn.com",
            "Referer": "https://edition.cnn.com/"
        }
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            data_text += f"✔ 공포탐욕지수: {int(data['fear_and_greed']['score'])} ({data['fear_and_greed']['rating']})\n"
        else:
            data_text += "✔ 공포탐욕지수: 조회 실패\n"
    except:
        data_text += "✔ 공포탐욕지수: 조회 실패\n"
        
    data_text += "\n오늘도 성공적인 투자 되세요!"
    return data_text

def send_kakao_message(text):
    access_token = refresh_token()
    url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    headers = {"Authorization": f"Bearer {access_token}"}
    
    template = {
        "object_type": "text",
        "text": text,
        "link": {"web_url": "https://rmadh6418-ai.github.io/us-stock-dashboard/", "mobile_web_url": "https://rmadh6418-ai.github.io/us-stock-dashboard/"},
        "button_title": "대시보드 열기"
    }
    
    data = {"template_object": json.dumps(template)}
    response = requests.post(url, headers=headers, data=data)
    
    if response.status_code == 200:
        print("✅ 브리핑 전송 완료! 카카오톡을 확인해 보세요.")
    else:
        print(f"❌ 전송 실패: {response.text}")

if __name__ == "__main__":
    briefing_text = get_briefing_data()
    send_kakao_message(briefing_text)
