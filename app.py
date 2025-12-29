import streamlit as st
import pandas as pd
from googleapiclient.discovery import build
import isodate
from datetime import datetime, timezone, timedelta
import requests
from youtube_transcript_api import YouTubeTranscriptApi
import os # OS 모듈 추가

# --- 1. 페이지 설정 ---
st.set_page_config(layout="wide", page_title="Solinker YouTube Insight", page_icon="🎬")
st.markdown("""
<style>
    .stButton>button {width: 100%; border-radius: 5px;}
    img {border-radius: 10px;}
</style>
""", unsafe_allow_html=True)

# --- 2. 상태 초기화 ---
if 'search_results' not in st.session_state:
    st.session_state.search_results = None
if 'analysis_store' not in st.session_state:
    st.session_state.analysis_store = {}
if 'toggle_states' not in st.session_state:
    st.session_state.toggle_states = {}

# --- 3. 함수 정의 ---

@st.cache_data(show_spinner=False)
def load_image_from_url(url):
    try:
        return requests.get(url).content
    except:
        return None

def get_youtube(key):
    try: return build('youtube', 'v3', developerKey=key)
    except: return None

def get_channel_id(yt, query):
    try:
        if query.startswith("UC") and len(query) > 20: return query
        res = yt.search().list(q=query, type="channel", part="id", maxResults=1).execute()
        if res['items']: return res['items'][0]['id']['channelId']
        return None
    except: return None

def get_transcript_text(video_id):
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['ko', 'en', 'en-US'])
        full_text = " ".join([t['text'] for t in transcript_list])
        return full_text[:5000] 
    except: return None

def calc_date_filter(option):
    now = datetime.now(timezone.utc)
    if option == "최근 1개월": return (now - timedelta(days=30)).isoformat()
    elif option == "최근 3개월": return (now - timedelta(days=90)).isoformat()
    elif option == "최근 6개월": return (now - timedelta(days=180)).isoformat()
    elif option == "최근 1년": return (now - timedelta(days=365)).isoformat()
    return None

def parse_duration(d):
    try: return isodate.parse_duration(d).total_seconds()
    except: return 0

def calc_vph(pub, views):
    try:
        p = datetime.strptime(pub, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        h = (datetime.now(timezone.utc) - p).total_seconds() / 3600
        return round(views/h) if h>=1 else views
    except: return 0

def analyze_ai_deep(title, description, transcript, key):
    if not key: return "API 키가 필요합니다."
    source_text = f"자막 내용(일부): {transcript}" if transcript else f"영상 설명: {description}"
    has_transcript = "있음" if transcript else "없음 (설명글로 분석)"

    prompt = f"""
    [영상 정보]
    - 제목: {title}
    - 자막 여부: {has_transcript}
    - 내용: {source_text}

    위 정보를 바탕으로 이 영상의 [떡상 이유, 초반 후킹 요소, 구성/시나리오 흐름]을 분석해서 마크다운으로 정리해줘.
    """
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e: return f"AI 오류: {e}"

def search(yt, q, n=10, order='viewCount', vtype='any', ch_query=None, pub_after=None):
    try:
        ch_id = None
        if ch_query:
            ch_id = get_channel_id(yt, ch_query)
            if not ch_id: st.warning(f"채널 '{ch_query}'를 찾을 수 없어 키워드로만 검색합니다.")
        
        params = {'q': q, 'part': 'snippet', 'maxResults': 50, 'order': order, 'type': 'video'}
        if ch_id: params['channelId'] = ch_id
        if pub_after: params['publishedAfter'] = pub_after
        
        res = yt.search().list(**params).execute()
        raw_items = res.get('items', [])
        
        video_ids = [item['id']['videoId'] for item in raw_items]
        if not video_ids: return pd.DataFrame()
        
        vres = yt.videos().list(part='snippet,statistics,contentDetails', id=','.join(video_ids[:50])).execute()
        
        cids = list(set([i['snippet']['channelId'] for i in vres['items']]))
        cstats = {}
        if cids:
            cres = yt.channels().list(part='statistics', id=','.join(cids[:50])).execute()
            cstats = {i['id']: int(i['statistics']['subscriberCount']) for i in cres['items'] if 'subscriberCount' in i['statistics']}

        data = []
        for i in vres['items']:
            v, s, st = i['id'], i['snippet'], i['statistics']
            dur = parse_duration(i['contentDetails']['duration'])
            is_short = dur <= 60 and dur > 0
            if vtype == 'shorts' and not is_short: continue
            if vtype == 'video' and is_short: continue

            views = int(st.get('viewCount', 0))
            subs = cstats.get(s['channelId'], 1)
            
            data.append({
                'VideoID': v, 'Title': s['title'], 'Thumbnail': s['thumbnails']['high']['url'],
                'Channel': s['channelTitle'], 'Views': views, 'Subs': subs,
                'Performance(%)': round((views/subs)*100, 1) if subs>0 else 0,
                'VPH': calc_vph(s['publishedAt'], views), 'Published': s['publishedAt'][:10],
                'Description': s['description'], 'Link': f"https://www.youtube.com/watch?v={v}",
                'Tags': ', '.join(s.get('tags', []))
            })
        
        df = pd.DataFrame(data)
        if not df.empty:
            if order == 'viewCount':
                df = df.sort_values(by='Views', ascending=False)
            elif order == 'date':
                df = df.sort_values(by='Published', ascending=False)
            df = df.head(n)
            
        return df
    except Exception as e: st.error(f"Error: {e}"); return pd.DataFrame()

# --- 4. UI 구성 ---
st.title("🎥 Solinker YouTube Insight (Pro)")

with st.sidebar:
    st.header("⚙️ 설정")
    
    # [수정됨] 금고가 없어도 에러나지 않게 보호막(Try-Except) 설치
    def get_secret_safe(key_name):
        try:
            return st.secrets.get(key_name)
        except: # 파일이 없어서 에러가 나면 그냥 None을 줘라
            return None

    # 1. YouTube 키 확인
    auto_k1 = get_secret_safe("YOUTUBE_KEY")
    if auto_k1:
        k1 = auto_k1
        st.success("✅ YouTube 키 자동 로드 완료")
    else:
        k1 = st.text_input("YouTube API Key", type="password")
    
    # 2. OpenAI 키 확인
    auto_k2 = get_secret_safe("OPENAI_KEY")
    if auto_k2:
        k2 = auto_k2
        st.success("✅ OpenAI 키 자동 로드 완료")
    else:
        k2 = st.text_input("OpenAI API Key (선택)", type="password")
    
    st.divider()
    st.header("🔍 검색 필터")
    q = st.text_input("검색 키워드", placeholder="예: 스마트폰 영상 편집", key="search_query_input")
    ch_input = st.text_input("특정 채널 검색 (선택)", placeholder="예: 김작가TV")
    
    date_opt = st.selectbox("📅 조회 기간", ["전체", "최근 1년", "최근 6개월", "최근 3개월", "최근 1개월"])
    vtype = st.selectbox("영상 타입", ["any", "video", "shorts"])
    order = st.selectbox("정렬 기준", ["viewCount", "date", "rating"])
if st.button("🚀 분석 시작", type="primary"):
    if not k1:
        st.error("YouTube API 키를 입력하세요.")
    elif not q:
        st.warning("검색 키워드를 입력해주세요!")
    else:
        yt = get_youtube(k1)
            if yt:
                pub_date = calc_date_filter(date_opt)
                with st.spinner("데이터 분석 중..."):
                    df = search(yt, q, 10, order, vtype, ch_input, pub_date)
                    st.session_state.search_results = df
                    st.session_state.analysis_store = {}
                    st.session_state.toggle_states = {}

# --- 5. 메인 화면 ---
if st.session_state.search_results is not None:
    df = st.session_state.search_results
    if not df.empty:
        t1, t2 = st.tabs(["영상 리스트", "데이터 다운로드"])
        
        with t1:
            for i, r in df.iterrows():
                with st.container(border=True):
                    c1, c2 = st.columns([1, 2])
                    with c1:
                        st.image(r['Thumbnail'])
                        
                        img_data = load_image_from_url(r['Thumbnail'])
                        if img_data:
                            st.download_button("📥 썸네일 다운로드", img_data, f"thumb_{r['VideoID']}.jpg", "image/jpeg", key=f"btn_{i}")
                    
                    with c2:
                        st.subheader(r['Title'])
                        st.caption(f"📺 {r['Channel']} | 🗓️ {r['Published']}")
                        st.markdown(f"**👁️ 조회수:** {r['Views']:,} | **🔥 기여도:** {r['Performance(%)']}% | **⚡ VPH:** {r['VPH']:,}")
                        
                        with st.expander("🔽 영상 설명 보기 (Description)"):
                            st.info(r['Description'])
                            st.markdown(f"[👉 유튜브 바로가기]({r['Link']})")
                        
                        vid = r['VideoID']
                        is_open = st.session_state.toggle_states.get(vid, False)
                        btn_text = "🔼 분석 접기 (숨기기)" if is_open else "🤖 AI 시나리오/떡상 분석"
                        
                        if k2:
                            if st.button(btn_text, key=f"deep_btn_{i}"):
                                st.session_state.toggle_states[vid] = not is_open
                                st.rerun()
                            
                            if st.session_state.toggle_states.get(vid, False):
                                if vid not in st.session_state.analysis_store:
                                    with st.spinner("AI 분석 중..."):
                                        transcript = get_transcript_text(vid)
                                        result = analyze_ai_deep(r['Title'], r['Description'], transcript, k2)
                                        st.session_state.analysis_store[vid] = result
                                
                                st.success("분석 결과")
                                st.markdown(st.session_state.analysis_store[vid])
                        else:
                            st.warning("AI 분석을 하려면 OpenAI 키가 필요합니다.")
        with t2:
            st.dataframe(df)
            st.download_button("엑셀(CSV) 저장", df.to_csv(index=False).encode('utf-8-sig'), "data.csv")
    else:
        st.warning("검색 결과가 없습니다.")