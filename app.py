# -*- coding: utf-8 -*-
"""PChome 商品價格爬蟲 + 視覺化 (Streamlit)

執行方式：
    pip install -r requirements.txt
    streamlit run app.py
"""
import re
import time
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

API_URL = "https://ecshweb.pchome.com.tw/search/v3.3/all/results"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

st.set_page_config(page_title="PChome 價格分析", page_icon="🛒", layout="wide")


# ---------------------------------------------------------------- 爬蟲 ----
@st.cache_data(show_spinner=False, ttl=600)
def fetch_pchome(keyword: str, pages: int, delay: float) -> pd.DataFrame:
    """抓取指定關鍵字的前 N 頁商品資料，回傳 DataFrame。"""
    frames = []
    for page in range(1, pages + 1):
        params = {"q": keyword, "page": page, "sort": "sale/dc"}
        resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        prods = resp.json().get("prods", [])
        if not prods:  # 已無更多資料
            break
        frames.append(pd.DataFrame(prods))
        if page < pages:
            time.sleep(delay)  # 禮貌性延遲，避免被封鎖
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


# -------------------------------------------------------------- 資料處理 ----
def extract_brand(name: str) -> str:
    """從商品名稱擷取品牌，例如「【Anker】xxx」→ Anker；抓不到則為「其他」。"""
    m = re.match(r"^\s*[【\[](.+?)[】\]]", str(name))
    return m.group(1).strip() if m else "其他"


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    out = df[["name", "price"]].copy()
    out["price"] = pd.to_numeric(out["price"], errors="coerce")
    out = out.dropna(subset=["price"]).reset_index(drop=True)
    out["品牌"] = out["name"].map(extract_brand)

    # 價格區間（等寬分箱）
    bins = np.linspace(out["price"].min(), out["price"].max() + 1, 6)
    bins = np.unique(np.round(bins).astype(int))
    if len(bins) < 2:  # 所有價格相同
        out["價格區間"] = f"{int(out['price'].iloc[0])}"
    else:
        labels = [f"{bins[i]}~{bins[i + 1] - 1}" for i in range(len(bins) - 1)]
        out["價格區間"] = pd.cut(
            out["price"], bins=bins, labels=labels, right=False, include_lowest=True
        ).astype(str)
    return out


# ------------------------------------------------------------------ UI ----
st.title("🛒 PChome 商品價格爬蟲與視覺化")

with st.sidebar:
    st.header("搜尋條件")
    keyword = st.text_input("產品名稱", value="行動電源")
    pages = st.number_input("爬取頁數", min_value=1, max_value=20, value=2, step=1)
    delay = st.slider("每頁間隔秒數", 0.0, 10.0, 1.0, 0.5, help="頁數多時建議拉長，避免被網站封鎖")
    top_n = st.slider("圓餅圖顯示前 N 個品牌", 3, 20, 8)
    run = st.button("開始爬取", type="primary", use_container_width=True)

if run:
    if not keyword.strip():
        st.warning("請輸入產品名稱")
        st.stop()
    try:
        with st.spinner("爬取中，請稍候…"):
            raw = fetch_pchome(keyword.strip(), int(pages), float(delay))
    except requests.RequestException as e:
        st.error(f"請求失敗：{e}")
        st.stop()
    except ValueError as e:
        st.error(f"回傳資料不是有效的 JSON：{e}")
        st.stop()

    if raw.empty or "price" not in raw.columns:
        st.warning("查無資料，請換個關鍵字試試。")
        st.stop()

    st.session_state["raw"] = raw
    st.session_state["keyword"] = keyword.strip()

if "raw" not in st.session_state:
    st.info("請在左側輸入產品名稱與頁數，然後按「開始爬取」。")
    st.stop()

raw = st.session_state["raw"]
kw = st.session_state["keyword"]
df = prepare(raw)

if df.empty:
    st.warning("資料中沒有有效的價格欄位。")
    st.stop()

mean_price = df["price"].mean()

# 統計指標
c1, c2, c3, c4 = st.columns(4)
c1.metric("商品數量", f"{len(df):,}")
c2.metric("平均價格", f"{mean_price:,.0f}")
c3.metric("最高價格", f"{df['price'].max():,.0f}")
c4.metric("最低價格", f"{df['price'].min():,.0f}")

tab_line, tab_pie, tab_sun, tab_data = st.tabs(["📈 折線圖", "🥧 圓餅圖", "☀️ 旭日圖", "📄 資料"])

# 折線圖：各商品價格（以熱銷排序）+ 平均線
with tab_line:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df.index + 1,
            y=df["price"],
            mode="lines+markers",
            name="價格",
            customdata=df["name"],
            hovertemplate="第 %{x} 名<br>%{customdata}<br>價格：%{y:,}<extra></extra>",
        )
    )
    fig.add_hline(
        y=mean_price,
        line_dash="dash",
        line_color="red",
        annotation_text=f"平均 {mean_price:,.0f}",
    )
    fig.update_layout(
        title=f"PChome 電商網站上「{kw}」售價",
        xaxis_title="商品排序（依銷量）",
        yaxis_title="價格",
        height=550,
    )
    st.plotly_chart(fig, use_container_width=True)

# 圓餅圖：品牌占比（前 N 名，其餘合併為「其他品牌」）
with tab_pie:
    brand_cnt = df["品牌"].value_counts()
    top = brand_cnt.head(top_n)
    rest = brand_cnt.iloc[top_n:].sum()
    pie_df = top.rename_axis("品牌").reset_index(name="數量")
    if rest > 0:
        pie_df = pd.concat(
            [pie_df, pd.DataFrame({"品牌": ["其他品牌"], "數量": [rest]})], ignore_index=True
        )
    fig = px.pie(pie_df, names="品牌", values="數量", title=f"「{kw}」品牌占比（前 {top_n} 名）")
    fig.update_traces(textposition="inside", textinfo="percent+label")
    fig.update_layout(height=550)
    st.plotly_chart(fig, use_container_width=True)
    st.caption("品牌取自商品名稱開頭的【】或[]，無標示者歸類為「其他」。")

# 旭日圖：價格區間 → 品牌
with tab_sun:
    sun_df = df.groupby(["價格區間", "品牌"]).size().reset_index(name="數量")
    fig = px.sunburst(
        sun_df,
        path=["價格區間", "品牌"],
        values="數量",
        title=f"「{kw}」價格區間 → 品牌 分布",
    )
    fig.update_traces(textinfo="label+percent parent")
    fig.update_layout(height=650)
    st.plotly_chart(fig, use_container_width=True)

# 原始資料與下載
with tab_data:
    st.dataframe(df, use_container_width=True, height=500)
    fname = f"{datetime.now():%Y%m%d}_PCHOME_{kw}.csv"
    st.download_button(
        "下載完整資料 CSV",
        data=raw.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
        file_name=fname,
        mime="text/csv",
    )
