import streamlit as st
from openai import OpenAI

# ---------------------------------------------------------
# 1. 화면 기본 설정
# ---------------------------------------------------------
st.set_page_config(page_title="AI 채팅", page_icon="💬")
st.title("💬 AI 채팅봇")

# ---------------------------------------------------------
# 2. Solar API에 연결하기
#    - API 키는 코드에 직접 적지 않고, 스트림릿의 "비밀 금고(secrets)"에서 꺼내온다.
#    - 스트림릿 클라우드에 올릴 때는 앱 설정의 Secrets 메뉴에
#      SOLAR_API_KEY = "발급받은 키" 형식으로 넣어주면 된다.
#    - openai 라이브러리는 원래 OpenAI 회사 것이지만, base_url만 바꿔주면
#      같은 방식으로 다른 회사(여기서는 Upstage)의 API도 쓸 수 있다.
# ---------------------------------------------------------
client = OpenAI(
    api_key=st.secrets["SOLAR_API_KEY"],
    base_url="https://api.upstage.ai/v1",
)

# ---------------------------------------------------------
# 3. AI의 성격(시스템 프롬프트)
#    - 이 문장은 AI에게만 전달되고, 화면에는 절대 보여주지 않는다.
#    - 그래서 st.chat_message나 st.markdown으로 출력하는 코드가 없다.
# ---------------------------------------------------------
SYSTEM_PROMPT = (
    "너는 중고등학생에게 설명하는 친절한 정보 선생님이야. "
    "어려운 말은 쉬운 말로 바꿔 주고, 반드시 순수 한국어로만 답해."
)

# ---------------------------------------------------------
# 4. 대화 기록 저장 공간 만들기
#    - st.session_state는 스트림릿이 새로고침 사이에도 값을 기억하게 해주는 공간이다.
#    - 여기에 지금까지 나눈 대화(사용자 질문 + AI 답변)를 차곡차곡 쌓아서
#      "이전 대화를 기억하며 이어서 답하기"를 구현한다.
# ---------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []

# ---------------------------------------------------------
# 5. 지금까지의 대화를 화면에 말풍선으로 그려주기
#    - 스트림릿은 사용자가 뭔가를 입력할 때마다 코드를 처음부터 다시 실행하기 때문에,
#      매번 저장된 기록을 다시 그려줘야 대화가 이어져 보인다.
# ---------------------------------------------------------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ---------------------------------------------------------
# 6. 화면 맨 아래에 채팅 입력창 만들기
#    - 사용자가 뭔가를 입력하고 엔터를 치면, user_input에 그 글자가 담긴다.
#    - 아무것도 입력하지 않았다면 user_input은 None이라서 아래 if문이 실행되지 않는다.
# ---------------------------------------------------------
user_input = st.chat_input("궁금한 걸 물어보세요")

if user_input:
    # 6-1. 사용자가 입력한 메시지를 기록에 추가하고, 화면에도 바로 보여준다.
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # 6-2. AI에게 보낼 전체 대화 내용을 만든다.
    #      맨 앞에 성격(시스템) 문장을 넣고, 그 뒤에 지금까지 나눈 대화를 그대로 이어 붙인다.
    #      이렇게 매번 전체 대화를 같이 보내주기 때문에 AI가 이전 내용을 "기억"하는 것처럼 보인다.
    api_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + st.session_state.messages

    # 6-3. AI의 답변을 말풍선 안에 실시간으로(타자 치듯이) 흘려서 보여준다.
    with st.chat_message("assistant"):
        placeholder = st.empty()  # 글자가 계속 바뀌어 나갈 빈 자리
        full_answer = ""

        try:
            # stream=True로 요청하면, 답을 한 번에 받는 게 아니라
            # 글자(토큰) 조각들을 순서대로 조금씩 받아올 수 있다.
            stream = client.chat.completions.create(
                model="solar-open2",       # 모델 이름은 그대로 사용 (바꾸지 않음)
                messages=api_messages,
                reasoning_effort="none",   # 생각(추론) 과정을 끄고 바로 답하게 해서 속도를 높인다
                stream=True,
            )

            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    full_answer += delta
                    # 아직 다 안 끝났다는 느낌을 주려고 커서(▌)를 깜빡이듯 붙여준다.
                    placeholder.markdown(full_answer + "▌")

            # 다 받았으면 커서를 떼고 최종 답을 보여준다.
            placeholder.markdown(full_answer)

        except Exception:
            # 요청이 실패했을 때 빨간 기술 오류 화면 대신,
            # 학생들도 이해할 수 있는 친절한 한국어 안내 문구 한 줄만 보여준다.
            full_answer = "앗, 지금은 답을 가져오지 못했어요. 잠시 후 다시 시도해 주세요."
            placeholder.markdown(full_answer)

    # 6-4. AI의 답변도 기록에 추가해서, 다음 질문을 할 때 이어서 기억하게 만든다.
    st.session_state.messages.append({"role": "assistant", "content": full_answer})
