# -*- coding: utf-8 -*-
"""
전국 연령대별 인구 비율 지도 (시군구 단위 단계구분도)
- 스트림릿 클라우드 배포용 main.py
- 인구 데이터: 전국 읍·면·동 인구 (2015~2026)
- 경계 데이터: 전국 시군구 255개 GeoJSON
- 연령대 지표(0~10세 ~ 60세 이상)와 연도를 각각 선택하면 그 기준으로 지도 색이 바뀐다.
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
st.set_page_config(page_title="전국 연령대별 인구 지도", layout="wide")

st.title("🗺️ 전국 시군구 연령대별 인구 지도")
st.write(
    "시군구별로 **선택한 연령대가 전체 인구에서 차지하는 비율**을 색으로 나타낸 "
    "단계구분도입니다. 아래에서 연령대 지표와 연도를 골라 볼 수 있습니다."
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


def extract_age(col_name: str) -> int:
    """'계_0세', '계_100세 이상' 같은 열 이름에서 나이 숫자만 뽑아낸다."""
    match = re.search(r"(\d+)", col_name)
    return int(match.group(1)) if match else -1


# -----------------------------------------------------------------------
# 2. 연령대 구간 정의 (0~10세 ~ 60세 이상, 10살 단위)
# -----------------------------------------------------------------------
# '60세 이상'은 51~60세 구간과 60세가 겹치지만, 고령 인구 비율을 보는
# 별도 지표로 일부러 겹치게 만든 것이다.
AGE_BANDS = [
    ("0~10세", lambda age: 0 <= age <= 10),
    ("11~20세", lambda age: 11 <= age <= 20),
    ("21~30세", lambda age: 21 <= age <= 30),
    ("31~40세", lambda age: 31 <= age <= 40),
    ("41~50세", lambda age: 41 <= age <= 50),
    ("51~60세", lambda age: 51 <= age <= 60),
    ("60세 이상", lambda age: age >= 60),
]
AGE_BAND_LABELS = [label for label, _ in AGE_BANDS]


# -----------------------------------------------------------------------
# 3. 데이터 불러오기 (한 번 불러오면 캐시에 저장해서 재사용)
# -----------------------------------------------------------------------
@st.cache_data(show_spinner="인구 데이터를 불러오는 중입니다...")
def load_population(url: str) -> pd.DataFrame:
    """읍·면·동 인구 데이터를 읽고, 필요한 계산을 미리 다 해둔다.

    '코드' 열은 계산에 쓰는 숫자가 아니라 지역을 구분하는 '이름표'이므로
    반드시 문자(str)로 읽어서 앞자리 0이 사라지지 않도록 한다.
    앞 5자리를 잘라 시군구 코드를 만들고, 옛 코드는 최신 코드로 바꿔 둔다.
    또한 연령대별 인구 합계를 미리 열로 만들어 둬서, 나중에 지표를 바꿀 때
    다시 계산하지 않아도 되게 한다.
    """
    df = pd.read_csv(url, compression="gzip", dtype={"코드": str})
    df["시군구코드"] = df["코드"].str[:5].map(remap_sigungu_code)

    # '계_'로 시작하는 열만 골라서 사용한다. (남_, 여_ 열은 사용하지 않는다.)
    age_cols = [c for c in df.columns if c.startswith("계_")]
    df[age_cols] = df[age_cols].apply(pd.to_numeric, errors="coerce").fillna(0)

    # 나이별 열 이름에서 나이 숫자를 미리 뽑아 둔다.
    ages = {c: extract_age(c) for c in age_cols}

    df["전체인구"] = df[age_cols].sum(axis=1)

    for label, condition in AGE_BANDS:
        cols_in_band = [c for c in age_cols if condition(ages[c])]
        df[label] = df[cols_in_band].sum(axis=1)

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
# 4. 시군구 단위로 합치는 함수 (연도 하나를 넣으면 그 해 집계를 돌려준다)
# -----------------------------------------------------------------------
def aggregate_by_sigungu(year: int) -> pd.DataFrame:
    """선택한 연도의 읍·면·동 인구를 시군구 단위로 합쳐서 돌려준다.

    반환되는 표에는 '전체인구'와 연령대별 인구 합계 열이 모두 들어 있다.
    """
    df_year = pop_raw[pop_raw["연도"] == year]
    agg_dict = {"전체인구": ("전체인구", "sum")}
    agg_dict.update({label: (label, "sum") for label in AGE_BAND_LABELS})
    return df_year.groupby("시군구코드").agg(**agg_dict).reset_index()


# -----------------------------------------------------------------------
# 5. 화면 상단: 연령대 지표 선택 + 연도 슬라이더
# -----------------------------------------------------------------------
col_select, col_slider = st.columns([1, 2])

with col_select:
    selected_label = st.selectbox(
        "연령대 지표 선택",
        options=AGE_BAND_LABELS,
        index=len(AGE_BAND_LABELS) - 1,  # 기본값: '60세 이상'
    )

min_year = int(pop_raw["연도"].min())
max_year = int(pop_raw["연도"].max())

with col_slider:
    selected_year = st.slider(
        "연도 선택",
        min_value=min_year,
        max_value=max_year,
        value=max_year,
        step=1,
        format="%d년",
    )


# -----------------------------------------------------------------------
# 6. 5단계 색 구간 경계값을 지표별로 자동 계산하기
# -----------------------------------------------------------------------
# 지표(연령대)마다 실제 값의 분포가 크게 다르므로(예: '0~10세'는 대부분 5~10%대,
# '60세 이상'은 10~60%대), 지표마다 다섯 덩어리로 나눈 실제 값을 따로 계산한다.
# 다만 연도를 바꿔도 같은 지표라면 항상 같은 경계값을 쓰도록, 가장 최신 연도
# 자료를 '기준 연도'로 삼아 경계값을 한 번만 계산해 고정해 둔다.
@st.cache_data(show_spinner=False)
def compute_breakpoints(reference_year: int) -> dict:
    """지표별 5단계 색 경계값(20%, 40%, 60%, 80% 지점)을 계산한다."""
    ref = aggregate_by_sigungu(reference_year)
    ref = geo_names.merge(ref, on="시군구코드", how="left")

    breakpoints = {}
    for label in AGE_BAND_LABELS:
        ratio = ref[label] / ref["전체인구"] * 100
        ratio = ratio.dropna()
        q = ratio.quantile([0.2, 0.4, 0.6, 0.8]).round(1).tolist()
        breakpoints[label] = q
    return breakpoints


breakpoints_by_label = compute_breakpoints(max_year)
b0, b1, b2, b3 = breakpoints_by_label[selected_label]

bins = [-np.inf, b0, b1, b2, b3, np.inf]
labels = [
    f"{b0}% 미만",
    f"{b0}%~{b1}%",
    f"{b1}%~{b2}%",
    f"{b2}%~{b3}%",
    f"{b3}% 이상",
]
# 낮은 단계는 옅은 색, 높은 단계는 진한 색 (5단계 그라데이션 팔레트)
colors = ["#fef0d9", "#fdcc8a", "#fc8d59", "#e34a33", "#b30000"]
GRAY_COLOR = "#cccccc"  # 코드가 안 맞아 자료가 없는 지역용 회색

st.caption(
    f"※ 색 구간 경계값은 {max_year}년 자료를 기준으로 '{selected_label}' 지표를 "
    "다섯 덩어리로 나눈 실제 값이며, 연도를 바꿔도 이 경계값은 그대로 유지됩니다."
)


# -----------------------------------------------------------------------
# 7. 선택한 연도의 데이터 계산하기
# -----------------------------------------------------------------------
grouped_year = aggregate_by_sigungu(selected_year)
grouped_year["비율"] = (grouped_year[selected_label] / grouped_year["전체인구"] * 100).round(2)

# 경계 파일에 있는 시군구 255개를 기준으로 인구 자료를 붙인다.
# 이렇게 하면, 그 해 인구 자료와 코드가 안 맞는 시군구도 목록에 남아서
# (비율이 비어있는 채로) 나중에 회색으로 표시할 수 있다.
merged = geo_names.merge(
    grouped_year[["시군구코드", "비율"]], on="시군구코드", how="left"
)

matched = merged[merged["비율"].notna()].copy()
unmatched = merged[merged["비율"].isna()].copy()

matched["등급"] = pd.cut(matched["비율"], bins=bins, labels=labels, right=False)


# -----------------------------------------------------------------------
# 8. 지도 그리기 (단계별로 트레이스를 나눠서 그리면 범례에 글자가 나온다)
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
            customdata=subset[["시도", "시군구", "비율"]].values,
            hovertemplate=(
                "<b>%{customdata[1]}</b><br>"
                "%{customdata[0]}<br>"
                f"{selected_label} 비율: " + "%{customdata[2]:.1f}%"
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
    legend=dict(title=f"{selected_label} 비율 구간", orientation="v", x=1.0, y=0.5),
)

st.plotly_chart(fig, use_container_width=True)


# -----------------------------------------------------------------------
# 9. 안내 문구: 코드가 안 맞아 회색으로 표시된 지역
# -----------------------------------------------------------------------
if not unmatched.empty:
    place_list = "、".join(
        f"{row.시도} {row.시군구}" for row in unmatched.itertuples()
    )
    st.warning(
        f"⚠️ {selected_year}년에는 아래 {len(unmatched)}개 지역의 행정구역 코드가 "
        f"경계 파일과 맞지 않아 지도에서 회색으로 표시했습니다 (이 해에는 비율을 "
        f"보여드릴 수 없습니다): {place_list}"
    )


# -----------------------------------------------------------------------
# 10. 비율 상위 10개 / 하위 10개 표
# -----------------------------------------------------------------------
def make_display_table(data: pd.DataFrame) -> pd.DataFrame:
    """표에 보여줄 형태로 다듬기: 비율에 % 표시 붙이기"""
    out = data[["시도", "시군구", "비율"]].copy()
    out[f"{selected_label} 비율(%)"] = out["비율"].map(lambda x: f"{x:.1f}%")
    out = out.drop(columns="비율").reset_index(drop=True)
    out.index = out.index + 1
    return out


top10 = matched.sort_values("비율", ascending=False).head(10)
bottom10 = matched.sort_values("비율", ascending=True).head(10)

st.subheader(f"{selected_year}년 '{selected_label}' 비율 상위 · 하위 10개 시군구")
col_left, col_right = st.columns(2)

with col_left:
    st.markdown(f"**🔺 '{selected_label}' 비율이 높은 지역 TOP 10**")
    st.dataframe(make_display_table(top10), use_container_width=True)

with col_right:
    st.markdown(f"**🔻 '{selected_label}' 비율이 낮은 지역 TOP 10**")
    st.dataframe(make_display_table(bottom10), use_container_width=True)
