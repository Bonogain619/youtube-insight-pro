import streamlit as st
from googleapiclient.discovery import build
import pandas as pd
import plotly.express as px
from datetime import datetime
import isodate
from openai import OpenAI

# 1. 페이지 설정
st.set_page_config(page_title="Solinker Channel Doctor", page_icon="🏥", layout="wide")

# 세션 상태 초기화
if "channel_data" not in st.session_state:
    st.session_state.channel_data = None
if "video_df" not in st.session_state:
    st.session_state.video_df = None
if "ai_report" not in st.session_state:
    st.session_state.ai_report = None

# -------------------------------------------------------------------
# 2. 사이드바: 설정 및 메뉴 선택
# -------------------------------------------------------------------
with st.sidebar:
    st.title("🏥 채널 종합 검진")
    
    # 1) API 키 입력 (강의용 Manual Input)
    with st.expander("🔐 API 키 설정", expanded=True):
        yt_key = st.text_input("YouTube API Key", type="password")
        ai_key = st.text_input("OpenAI API Key", type="password")

    st.divider()
    
    # 2) 채널 입력
    st.header("1️⃣ 환자(채널) 등록")
    handle_input = st.text_input("채널 핸들 (예: @kimwriter)", placeholder="@핸들명")
    
    if st.button("🚀 검진 시작", type="primary"):
        if not yt_key:
            st.error("YouTube API 키를 입력하세요.")
        elif not handle_input:
            st.warning("채널 핸들을 입력하세요.")
        else:
            # 로직 실행 트리거
            st.session_state.run_analysis = True
    
    st.divider()

    # 3) 진단 모듈 선택 (강의 효율성 UP!)
    st.header("2️⃣ 진단 항목 선택")
    analysis_mode = st.radio(
        "보고 싶은 결과를 선택하세요:",
        ["1. 🩺 기초 체력 (구독자/조회수)", 
         "2. ⚖️ 포맷 분석 (쇼츠 vs 롱폼)", 
         "3. 📈 성장 추세 (최근 성과)", 
         "4. 🤖 AI 종합 컨설팅"]
    )

# -------------------------------------------------------------------
# 3. 핵심 로직 함수 (비용 최적화 적용)
# -------------------------------------------------------------------
def get_youtube(api_key):
    return build("youtube", "v3", developerKey=api_key)

def get_channel_stats(yt, handle):
    try:
        # 핸들로 채널 ID 찾기
        res = yt.search().list(part="id,snippet", q=handle, type="channel", maxResults=1).execute()
        if not res["items"]: return None
        
        ch_id = res["items"][0]["id"]["channelId"]
        
        # 채널 통계 및 업로드 재생목록 ID 가져오기
        ch_res = yt.channels().list(part="statistics,contentDetails,snippet", id=ch_id).execute()
        item = ch_res["items"][0]
        
        stats = {
            "title": item["snippet"]["title"],
            "thumbnail": item["snippet"]["thumbnails"]["high"]["url"],
            "subs": int(item["statistics"]["subscriberCount"]),
            "views": int(item["statistics"]["viewCount"]),
            "video_count": int(item["statistics"]["videoCount"]),
            "upload_id": item["contentDetails"]["relatedPlaylists"]["uploads"] # 여기가 핵심!
        }
        return stats
    except Exception as e:
        st.sidebar.error(f"채널 검색 실패: {e}")
        return None

def get_recent_videos(yt, upload_id, limit=50):
    try:
        # 업로드 재생목록에서 영상 가져오기 (Quota 절약)
        videos = []
        request = yt.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=upload_id,
            maxResults=limit
        )
        response = request.execute()
        
        vid_ids = []
        for item in response["items"]:
            vid_ids.append(item["contentDetails"]["videoId"])
            
        # 영상 세부 정보(Duration 등) 조회
        vid_res = yt.videos().list(
            part="statistics,contentDetails,snippet",
            id=",".join(vid_ids)
        ).execute()
        
        for item in vid_res["items"]:
            dur = isodate.parse_duration(item["contentDetails"]["duration"]).total_seconds()
            
            videos.append({
                "title": item["snippet"]["title"],
                "publishedAt": item["snippet"]["publishedAt"],
                "viewCount": int(item["statistics"].get("viewCount", 0)),
                "likeCount": int(item["statistics"].get("likeCount", 0)),
                "commentCount": int(item["statistics"].get("commentCount", 0)),
                "duration": dur,
                "type": "Shorts" if dur <= 60 else "Video"
            })
            
        return pd.DataFrame(videos)
    except Exception as e:
        st.sidebar.error(f"영상 데이터 수집 실패: {e}")
        return pd.DataFrame()

def get_ai_advice(client, stats, df):
    # 데이터 요약
    avg_views = df["viewCount"].mean()
    shorts_count = len(df[df["type"] == "Shorts"])
    video_count = len(df[df["type"] == "Video"])
    
    prompt = f"""
    당신은 유튜브 채널 컨설턴트입니다. 아래 채널 데이터를 분석하여 진단 리포트를 작성해주세요.
    
    [채널 정보]
    - 채널명: {stats['title']}
    - 구독자: {stats['subs']}명
    - 최근 평균 조회수: {int(avg_views)}회
    - 최근 영상 구성: 롱폼 {video_count}개 vs 쇼츠 {shorts_count}개
    
    [요청사항]
    1. 칭찬 (강점): 데이터에 기반하여 잘하고 있는 점
    2. 지적 (약점): 구독자 대비 조회수나 업로드 불균형 등 문제점
    3. 처방 (솔루션): 앞으로의 운영 전략 및 최신 트렌드 제안
    
    이모지를 사용하여 읽기 쉽게 마크다운으로 작성하세요.
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI 분석 중 오류 발생: {e}"

# -------------------------------------------------------------------
# 4. 메인 실행 로직
# -------------------------------------------------------------------
if st.session_state.get("run_analysis", False):
    st.session_state.run_analysis = False # 트리거 리셋
    
    if yt_key:
        yt = get_youtube(yt_key)
        with st.spinner("🏥 채널 정밀 검진 중... (차트 그리는 중)"):
            stats = get_channel_stats(yt, handle_input)
            if stats:
                df = get_recent_videos(yt, stats["upload_id"])
                
                # 세션에 저장 (새로고침 방지)
                st.session_state.channel_data = stats
                st.session_state.video_df = df
                st.session_state.ai_report = None # AI 분석은 따로 요청 시 실행

# -------------------------------------------------------------------
# 5. 결과 대시보드 (선택된 모듈만 표시)
# -------------------------------------------------------------------
data = st.session_state.channel_data
df = st.session_state.video_df

if data is not None and df is not None:
    # 공통: 채널 프로필 헤더
    c1, c2 = st.columns([1, 5])
    with c1:
        st.image(data["thumbnail"], width=100)
    with c2:
        st.title(f"{data['title']}")
        st.caption(f"구독자: {data['subs']:,}명 | 총 조회수: {data['views']:,}회 | 분석 영상: 최근 {len(df)}개")
    st.divider()
    
    # ---------------------------
    # 모듈 1: 기초 체력
    # ---------------------------
    if "1." in analysis_mode:
        st.header("🩺 기초 체력 진단")
        col1, col2, col3 = st.columns(3)
        
        avg_v = df["viewCount"].mean()
        ratio = (avg_v / data["subs"]) * 100 if data["subs"] > 0 else 0
        
        col1.metric("최근 평균 조회수", f"{int(avg_v):,}회")
        col2.metric("구독자 대비 활성도", f"{ratio:.1f}%", help="보통 10% 이상이면 건강한 채널입니다.")
        col3.metric("평균 좋아요 수", f"{int(df['likeCount'].mean()):,}개")
        
        st.info("💡 **활성도(Active Ratio)**란? 구독자 중 실제 영상을 클릭하는 충성 시청자의 비율입니다.")

    # ---------------------------
    # 모듈 2: 포맷 분석
    # ---------------------------
    elif "2." in analysis_mode:
        st.header("⚖️ 포맷 효율 분석 (Shorts vs Video)")
        
        # 데이터 가공
        format_counts = df["type"].value_counts().reset_index()
        format_counts.columns = ["Type", "Count"]
        
        format_views = df.groupby("type")["viewCount"].mean().reset_index()
        
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("📊 업로드 비중")
            fig1 = px.pie(format_counts, values="Count", names="Type", title="영상 타입 비율")
            st.plotly_chart(fig1, use_container_width=True)
            
        with c2:
            st.subheader("👁️ 평균 조회수 비교")
            fig2 = px.bar(format_views, x="type", y="viewCount", color="type", title="타입별 성과 차이")
            st.plotly_chart(fig2, use_container_width=True)
            
        st.success("💡 **전략 포인트**: 조회수가 더 잘 나오는 포맷에 집중하되, 구독자 유입은 쇼츠, 수익화는 롱폼으로 균형을 맞추세요.")

    # ---------------------------
    # 모듈 3: 성장 추세
    # ---------------------------
    elif "3." in analysis_mode:
        st.header("📈 성장 추세 분석")
        
        # 시계열 차트
        df["publishedAt"] = pd.to_datetime(df["publishedAt"])
        df_sorted = df.sort_values("publishedAt")
        
        st.line_chart(df_sorted, x="publishedAt", y="viewCount")
        
        # 최근 5개 성과
        st.subheader("🔥 최근 5개 영상 퍼포먼스")
        st.dataframe(df_sorted.tail(5)[["title", "viewCount", "type"]].sort_values("viewCount", ascending=False), hide_index=True)

    # ---------------------------
    # 모듈 4: AI 종합 컨설팅
    # ---------------------------
    elif "4." in analysis_mode:
        st.header("🤖 AI 닥터 소견서")
        
        if not ai_key:
            st.warning("⚠️ OpenAI API 키가 필요합니다. 사이드바에 입력해주세요.")
        else:
            if st.session_state.ai_report is None:
                with st.spinner("AI가 진단서를 작성 중입니다..."):
                    client = OpenAI(api_key=ai_key)
                    report = get_ai_advice(client, data, df)
                    st.session_state.ai_report = report
            
            st.markdown(st.session_state.ai_report)