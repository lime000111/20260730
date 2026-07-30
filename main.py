# -*- coding: utf-8 -*-
"""
전국 고령화 지도 (시군구 단위, 65세 이상 인구 비율 단계구분도)
- 스트림릿 클라우드 배포용 main.py
- 인구 데이터: 전국 읍·면·동 인구 (2015~2026)
- 경계 데이터: 전국 시군구 255개 GeoJSON
- 연도를 슬라이더로 선택하면 그 해 기준으로 지도 색이 바뀐다.
"""

import re

import requests
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

# -----------------------------------------------------------------------
# 0. 기본 화면 설정
# -----------------------------------------------------------------------
st.set_page_config(page_title="전국 고령화 지도", layout="wide")

st.title("🗺️ 전국 시군구 고령화 지도")
st.write(
    "시군구별 **65세 이상 인구 비율(고령화율)** 을 색으로 나타낸 단계구분도입니다. "
    "아래 슬라이더로 연도를 바꿔 가며 볼 수 있습니다."
)

# 데이터 주소
POP_URL = "https://raw.githubusercontent.com/greatsong/modudata/main/data/population_yearly.csv.gz"
GEOJSON_URL = "https://raw.githubusercontent.com/greatsong/modudata/main/data/boundaries/sigungu_kr.geojson"


# -----------------------------------------------------------------------
# 1. 옛 행정구역 코드를 최신 코드로 바꾸는 함수
# -----------------------------------------------------------------------
def remap_sigungu_code(code: str) -> str:
    """예전에 쓰던 시군구 코드를 지금 경계 파일이 쓰는 코드로 바꿔준다.

    - 강원도(옛 코드 42로 시작) -> 강원특별자치도(51로 시작)
    - 전라북도(옛 코드 45로 시작) -> 전북특별자치도(52로 시작)
    - 군위군(옛 코드 47720, 경상북도) -> 27720(대구광역시로 편입)

    이 세 가지에 해당하지 않으면 코드를 그대로 돌려준다.
    """
    if code == "47720":
        return "27720"
    if code.startswith("42"):
        return "51" + code[2:]
    if code.startswith("45"):
        return "52" + code[2:]
    return code


# -----------------------------------------------------------------------
# 2. 데이터 불러오기 (한 번 불러오면 캐시에 저장해서 재사용)
# -----------------------------------------------------------------------
@st.cache_data(show_spinner="인구 데이터를 불러오는 중입니다...")
def load_population(url: str) -> pd.DataFrame:
    """읍·면·동 인구 데이터를 읽어온다.

    '코드' 열은 계산에 쓰는 숫자가 아니라 지역을 구분하는 '이름표'이므로
    반드시 문자(str)로 읽어서 앞자리 0이 사라지지 않도록 한다.
    앞 5자리를 잘라 시군구 코드를 만들고, 옛 코드는 최신 코드로 바꿔 둔다.
    """
    df = pd.read_csv(url, compression="gzip", dtype={"코드": str})
    df["시군구코드"] = df["코드"].str[:5].map(remap_sigungu_code)
    return df


@st.cache_data(show_spinner="지도 경계 데이터를 불러오는 중입니다...")
def load_geojson(url: str) -> dict:
    """시군구 경계 GeoJSON 파일을 읽어온다."""
    res = requests.get(url)
    res.raise_for_status()
    return res.json()


try:
    pop_raw = load_population(POP_URL)
    geojson = load_geojson(GEOJSON_URL)
except Exception as e:  # 네트워크 오류 등 문제 발생 시 안내 후 중단
    st.error(f"데이터를 불러오는 중 문제가 발생했습니다: {e}")
    st.stop()

# 경계 파일이 갖고 있는 시군구 255개의 코드·이름 목록 (지도의 '바탕'이 되는 표)
geo_names = pd.DataFrame(
    [
        {
            "시군구코드": f["properties"]["코드"],
            "시도": f["properties"]["시도"],
            "시군구": f["properties"]["시군구"],
        }
        for f in geojson["features"]
    ]
)


# -----------------------------------------------------------------------
# 3. 연도 슬라이더
# -----------------------------------------------------------------------
min_year = int(pop_raw["연도"].min())
max_year = int(pop_raw["연도"].max())

selected_year = st.slider(
    "연도 선택",
    min_value=min_year,
    max_value=max_year,
    value=max_year,
    step=1,
    format="%d년",
)

df = pop_raw[pop_raw["연도"] == selected_year].copy()


# -----------------------------------------------------------------------
# 4. 전체 인구 / 65세 이상 인구 계산하기
# -----------------------------------------------------------------------
# '계_0세' ~ '계_100세 이상' 처럼 '계_'로 시작하는 열만 골라서
# 나이 숫자를 정규식으로 뽑아낸다. (남_, 여_ 열은 사용하지 않는다.)
age_cols = [c for c in df.columns if c.startswith("계_")]


def extract_age(col_name: str) -> int:
    """'계_0세', '계_100세 이상' 같은 열 이름에서 나이 숫자만 뽑아낸다."""
    match = re.search(r"(\d+)", col_name)
    return int(match.group(1)) if match else -1


elderly_cols = [c for c in age_cols if extract_age(c) >= 65]

# 나이별 인구 열이 문자로 들어있을 수도 있으니 숫자로 변환
df[age_cols] = df[age_cols].apply(pd.to_numeric, errors="coerce").fillna(0)

df["전체인구"] = df[age_cols].sum(axis=1)
df["고령인구"] = df[elderly_cols].sum(axis=1)


# -----------------------------------------------------------------------
# 5. 읍·면·동 인구를 시군구 단위로 합치기
# -----------------------------------------------------------------------
grouped_year = (
    df.groupby("시군구코드")
    .agg(전체인구=("전체인구", "sum"), 고령인구=("고령인구", "sum"))
    .reset_index()
)
grouped_year["고령화율"] = (
    grouped_year["고령인구"] / grouped_year["전체인구"] * 100
).round(2)

# 경계 파일에 있는 시군구 255개를 기준으로 인구 자료를 붙인다.
# 이렇게 하면, 그 해 인구 자료와 코드가 안 맞는 시군구도 목록에 남아서
# (고령화율이 비어있는 채로) 나중에 회색으로 표시할 수 있다.
merged = geo_names.merge(
    grouped_year[["시군구코드", "고령화율"]], on="시군구코드", how="left"
)

matched = merged[merged["고령화율"].notna()].copy()
unmatched = merged[merged["고령화율"].isna()].copy()


# -----------------------------------------------------------------------
# 6. 고령화율을 5단계로 나누기 (구간 경계값: 19%, 23%, 28%, 38%)
# -----------------------------------------------------------------------
# ※ 이 경계값은 연도를 바꿔도 항상 똑같이 고정한다.
#   그래야 다른 연도끼리도 같은 기준으로 색을 비교할 수 있다.
bins = [-np.inf, 19, 23, 28, 38, np.inf]
labels = ["19% 미만", "19%~23%", "23%~28%", "28%~38%", "38% 이상"]
# 낮은 단계는 옅은 색, 높은 단계는 진한 색 (5단계 그라데이션 팔레트)
colors = ["#fef0d9", "#fdcc8a", "#fc8d59", "#e34a33", "#b30000"]
GRAY_COLOR = "#cccccc"  # 코드가 안 맞아 자료가 없는 지역용 회색

matched["등급"] = pd.cut(matched["고령화율"], bins=bins, labels=labels, right=False)


# -----------------------------------------------------------------------
# 7. 지도 그리기 (단계별로 트레이스를 나눠서 그리면 범례에 글자가 나온다)
# -----------------------------------------------------------------------
fig = go.Figure()

for label, color in zip(labels, colors):
    subset = matched[matched["등급"] == label]
    if subset.empty:
        continue

    fig.add_trace(
        go.Choropleth(
            geojson=geojson,
            featureidkey="properties.코드",     # geojson 쪽 지역 코드 위치
            locations=subset["시군구코드"],       # 우리 데이터 쪽 지역 코드
            z=[0] * len(subset),                 # 색은 colorscale로 고정하므로 값은 의미 없음
            zmin=0,
            zmax=1,
            colorscale=[[0, color], [1, color]],  # 트레이스마다 한 가지 색만 사용
            showscale=False,
            showlegend=True,
            name=label,                          # 범례에 표시될 구간 글자
            marker_line_color="white",
            marker_line_width=0.6,
            customdata=subset[["시도", "시군구", "고령화율"]].values,
            hovertemplate=(
                "<b>%{customdata[1]}</b><br>"
                "%{customdata[0]}<br>"
                "고령화율: %{customdata[2]:.1f}%"
                "<extra></extra>"
            ),
        )
    )

# 그 해 자료와 코드가 안 맞는 지역은 회색으로 표시
if not unmatched.empty:
    fig.add_trace(
        go.Choropleth(
            geojson=geojson,
            featureidkey="properties.코드",
            locations=unmatched["시군구코드"],
            z=[0] * len(unmatched),
            zmin=0,
            zmax=1,
            colorscale=[[0, GRAY_COLOR], [1, GRAY_COLOR]],
            showscale=False,
            showlegend=True,
            name="자료 없음 (코드 불일치)",
            marker_line_color="white",
            marker_line_width=0.6,
            customdata=unmatched[["시도", "시군구"]].values,
            hovertemplate=(
                "<b>%{customdata[1]}</b><br>"
                "%{customdata[0]}<br>"
                f"{selected_year}년 자료 없음"
                "<extra></extra>"
            ),
        )
    )

# 배경 지도 타일 없이 경계선만 보이도록 설정
fig.update_geos(
    visible=False,
    showcountries=False,
    showsubunits=False,
    showland=False,
    showocean=False,
    showlakes=False,
    showrivers=False,
    showcoastlines=False,
    bgcolor="rgba(0,0,0,0)",
    fitbounds="locations",
)

fig.update_layout(
    height=750,
    margin=dict(l=0, r=0, t=10, b=0),
    legend=dict(title="고령화율 구간", orientation="v", x=1.0, y=0.5),
)

st.plotly_chart(fig, use_container_width=True)


# -----------------------------------------------------------------------
# 8. 안내 문구: 코드가 안 맞아 회색으로 표시된 지역
# -----------------------------------------------------------------------
if not unmatched.empty:
    place_list = "、".join(
        f"{row.시도} {row.시군구}" for row in unmatched.itertuples()
    )
    st.warning(
        f"⚠️ {selected_year}년에는 아래 {len(unmatched)}개 지역의 행정구역 코드가 "
        f"경계 파일과 맞지 않아 지도에서 회색으로 표시했습니다 (이 해에는 고령화율을 "
        f"보여드릴 수 없습니다): {place_list}"
    )


# -----------------------------------------------------------------------
# 9. 고령화율 상위 10개 / 하위 10개 표
# -----------------------------------------------------------------------
def make_display_table(data: pd.DataFrame) -> pd.DataFrame:
    """표에 보여줄 형태로 다듬기: 고령화율에 % 표시 붙이기"""
    out = data[["시도", "시군구", "고령화율"]].copy()
    out["고령화율(%)"] = out["고령화율"].map(lambda x: f"{x:.1f}%")
    out = out.drop(columns="고령화율").reset_index(drop=True)
    out.index = out.index + 1
    return out


top10 = matched.sort_values("고령화율", ascending=False).head(10)
bottom10 = matched.sort_values("고령화율", ascending=True).head(10)

st.subheader(f"{selected_year}년 고령화율 상위 · 하위 10개 시군구")
col_left, col_right = st.columns(2)

with col_left:
    st.markdown("**🔺 고령화율이 높은 지역 TOP 10**")
    st.dataframe(make_display_table(top10), use_container_width=True)

with col_right:
    st.markdown("**🔻 고령화율이 낮은 지역 TOP 10**")
    st.dataframe(make_display_table(bottom10), use_container_width=True)
