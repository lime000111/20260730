# -*- coding: utf-8 -*-
"""
전국 고령화 지도 (시군구 단위, 65세 이상 인구 비율 단계구분도)
- 스트림릿 클라우드 배포용 main.py
- 인구 데이터: 전국 읍·면·동 인구 (2015~2026)
- 경계 데이터: 전국 시군구 255개 GeoJSON
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
    "가장 최근 연도 자료를 사용합니다."
)

# 데이터 주소
POP_URL = "https://raw.githubusercontent.com/greatsong/modudata/main/data/population_yearly.csv.gz"
GEOJSON_URL = "https://raw.githubusercontent.com/greatsong/modudata/main/data/boundaries/sigungu_kr.geojson"


# -----------------------------------------------------------------------
# 1. 데이터 불러오기 (한 번 불러오면 캐시에 저장해서 재사용)
# -----------------------------------------------------------------------
@st.cache_data(show_spinner="인구 데이터를 불러오는 중입니다...")
def load_population(url: str) -> pd.DataFrame:
    """읍·면·동 인구 데이터를 읽어온다.

    '코드' 열은 계산에 쓰는 숫자가 아니라 지역을 구분하는 '이름표'이므로
    반드시 문자(str)로 읽어서 앞자리 0이 사라지지 않도록 한다.
    """
    df = pd.read_csv(url, compression="gzip", dtype={"코드": str})
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


# -----------------------------------------------------------------------
# 2. 최신 연도만 골라내기
# -----------------------------------------------------------------------
latest_year = int(pop_raw["연도"].max())
df = pop_raw[pop_raw["연도"] == latest_year].copy()

st.caption(f"※ {latest_year}년 인구 자료를 기준으로 그린 지도입니다.")


# -----------------------------------------------------------------------
# 3. 시군구 코드 만들기 (10자리 코드의 앞 5자리)
# -----------------------------------------------------------------------
# '코드'는 행정동 코드 10자리이며, 앞 5자리가 시군구를 나타낸다.
df["시군구코드"] = df["코드"].str[:5]


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

# 나이별 인구 열이 문자로 들어있을 수도 있으니 숫자로 변환(콤마 제거 등)
df[age_cols] = df[age_cols].apply(pd.to_numeric, errors="coerce").fillna(0)

df["전체인구"] = df[age_cols].sum(axis=1)
df["고령인구"] = df[elderly_cols].sum(axis=1)


# -----------------------------------------------------------------------
# 5. 읍·면·동 인구를 시군구 단위로 합치기
# -----------------------------------------------------------------------
grouped = (
    df.groupby("시군구코드")
    .agg(전체인구=("전체인구", "sum"), 고령인구=("고령인구", "sum"))
    .reset_index()
)

grouped["고령화율"] = (grouped["고령인구"] / grouped["전체인구"] * 100).round(2)

# 화면에 보여줄 시도·시군구 이름은 인구 데이터가 아니라 GeoJSON 쪽 이름을 쓴다.
# (인구 데이터의 '시군구' 이름은 세종시처럼 비어 있거나 최신 행정구역 개편이
#  반영되지 않은 경우가 있어, 지도 경계와 항상 짝이 맞는 GeoJSON 이름이 더 정확하다.)
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
grouped = grouped.merge(geo_names, on="시군구코드", how="left")


# -----------------------------------------------------------------------
# 6. 고령화율을 5단계로 나누기 (구간 경계값: 19%, 23%, 28%, 38%)
# -----------------------------------------------------------------------
bins = [-np.inf, 19, 23, 28, 38, np.inf]
labels = ["19% 미만", "19%~23%", "23%~28%", "28%~38%", "38% 이상"]
# 낮은 단계는 옅은 색, 높은 단계는 진한 색 (5단계 그라데이션 팔레트)
colors = ["#fef0d9", "#fdcc8a", "#fc8d59", "#e34a33", "#b30000"]

grouped["등급"] = pd.cut(grouped["고령화율"], bins=bins, labels=labels, right=False)


# -----------------------------------------------------------------------
# 7. 지도 그리기 (단계별로 트레이스를 나눠서 그리면 범례에 글자가 나온다)
# -----------------------------------------------------------------------
fig = go.Figure()

for label, color in zip(labels, colors):
    subset = grouped[grouped["등급"] == label]
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
# 8. 고령화율 상위 10개 / 하위 10개 표
# -----------------------------------------------------------------------
def make_display_table(data: pd.DataFrame) -> pd.DataFrame:
    """표에 보여줄 형태로 다듬기: 고령화율에 % 표시 붙이기"""
    out = data[["시도", "시군구", "고령화율"]].copy()
    out["고령화율(%)"] = out["고령화율"].map(lambda x: f"{x:.1f}%")
    out = out.drop(columns="고령화율").reset_index(drop=True)
    out.index = out.index + 1
    return out


top10 = grouped.sort_values("고령화율", ascending=False).head(10)
bottom10 = grouped.sort_values("고령화율", ascending=True).head(10)

st.subheader("고령화율 상위 · 하위 10개 시군구")
col_left, col_right = st.columns(2)

with col_left:
    st.markdown("**🔺 고령화율이 높은 지역 TOP 10**")
    st.dataframe(make_display_table(top10), use_container_width=True)

with col_right:
    st.markdown("**🔻 고령화율이 낮은 지역 TOP 10**")
    st.dataframe(make_display_table(bottom10), use_container_width=True)
