import os
import re
import urllib.parse
import pandas as pd
import streamlit as st
import requests
from PIL import Image
from io import BytesIO

# --- 網頁設定 ---
st.set_page_config(page_title="動森全生物即時圖鑑", page_icon="🏝️", layout="wide")

# 路徑
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAVE_FOLDER = os.path.join(BASE_DIR, "data")

# 模擬瀏覽器標頭
IMG_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://kkplay3c.net/"
}


# --- !!! ---
def encode_chinese_url(url):
    if pd.isna(url) or not isinstance(url, str) or not url.startswith("http"):
        return url
    try:
        parsed_url = urllib.parse.urlparse(url)
        path_parts = parsed_url.path.split("/")
        encoded_parts = [urllib.parse.quote(p) for p in path_parts]
        new_path = "/".join(encoded_parts)

        if parsed_url.query:
            query_pairs = urllib.parse.parse_qsl(parsed_url.query, keep_blank_values=True)
            new_query = urllib.parse.urlencode(query_pairs)
        else:
            new_query = parsed_url.query

        return parsed_url._replace(path=new_path, query=new_query).geturl()
    except Exception:
        return url


# --- PIC ---
@st.cache_data(show_spinner=False, ttl=3600)
def get_safe_image(url):
    try:
        response = requests.get(url, headers=IMG_HEADERS, timeout=5)
        if response.status_code == 200:
            return response.content
    except Exception:
        pass
    return None


def render_image(url, width):
    if pd.isna(url) or not str(url).startswith("http"):
        st.image("https://placehold.co/60x60?text=No+Img", width=width)
        return

    img_bytes = get_safe_image(url)
    if img_bytes is None:
        st.image("https://placehold.co/60x60?text=No+Image", width=width)
    else:
        try:
            st.image(Image.open(BytesIO(img_bytes)), width=width)
        except Exception:
            st.image("https://placehold.co/60x60?text=No+Image", width=width)


# --- 讀資料 ---
@st.cache_data(show_spinner="正在載入資料...")
def load_and_combine_data(_refresh_token=0):
    fish_path = os.path.join(SAVE_FOLDER, "魚類資料庫.csv")
    insect_path = os.path.join(SAVE_FOLDER, "昆蟲資料庫.csv")
    sea_path = os.path.join(SAVE_FOLDER, "海洋生物資料庫.csv")

    all_dfs = []
    target_cols = ["種類", "圖片網址", "名稱", "出沒月份", "出沒時間", "價格"]

    def sanitize_and_align_df(df, type_label, rename_dict, default_values):
        possible_img_cols = ["圖片", "生物圖片", "Image", "img", "image_url"]
        for c in possible_img_cols:
            if c in df.columns and "圖片網址" not in rename_dict:
                rename_dict[c] = "圖片網址"

        df = df.rename(columns=rename_dict)
        df["種類"] = type_label

        for col, val in default_values.items():
            if col not in df.columns:
                df[col] = val
        for col in target_cols:
            if col not in df.columns:
                df[col] = "無資料"
        return df[target_cols]

    if os.path.exists(fish_path):
        try:
            df_fish = pd.read_csv(fish_path)
            df_fish = sanitize_and_align_df(
                df=df_fish, type_label="魚類",
                rename_dict={"魚種": "名稱", "售價": "價格"},
                default_values={}
            )
            all_dfs.append(df_fish)
        except Exception:
            pass

    if os.path.exists(insect_path):
        try:
            df_insect = pd.read_csv(insect_path)
            df_insect = sanitize_and_align_df(
                df=df_insect, type_label="昆蟲",
                rename_dict={"昆蟲生物": "名稱", "出沒月份(月)": "出沒月份", "售價": "價格"},
                default_values={"出沒時間": "全天"}
            )
            all_dfs.append(df_insect)
        except Exception:
            pass

    if os.path.exists(sea_path):
        try:
            df_sea = pd.read_csv(sea_path)
            df_sea = sanitize_and_align_df(
                df=df_sea, type_label="海產",
                rename_dict={"海洋生物": "名稱", "售價": "價格"},
                default_values={"出沒時間": "全天"}
            )
            all_dfs.append(df_sea)
        except Exception:
            pass

    if not all_dfs:
        return pd.DataFrame(columns=target_cols)

    combined_df = pd.concat(all_dfs, ignore_index=True)
    combined_df["出沒月份"] = combined_df["出沒月份"].astype(str).str.replace(" ", "")
    combined_df["圖片網址"] = combined_df["圖片網址"].apply(encode_chinese_url)
    return combined_df


# --- 月份判斷 ---
def _check_single_month_token(token, target_month):
    token = token.strip()
    if not token:
        return False
 
    match = re.match(r"^(\d+)~(\d+)$", token)
    if match:
        start, end = int(match.group(1)), int(match.group(2))
        if start <= end:
            return start <= target_month <= end
        else:
            # 跨年範圍，例如 11~2 代表 11,12,1,2 月
            return target_month >= start or target_month <= end
 
    if token.isdigit():
        return int(token) == target_month
 
    return False
 
 
def is_month_in_range(range_str, target_month):
    if pd.isna(range_str) or str(range_str) in ("nan", "全年"):
        return True
 
    range_str = str(range_str).strip()
 
    if "," in range_str:
        tokens = range_str.split(",")
        return any(_check_single_month_token(t, target_month) for t in tokens)
 
    # 沒有逗號的單一格式
    return _check_single_month_token(range_str, target_month)


# --- 介面 ---
st.title("🏝️ 集合啦！動物森友會 - 全生物即時圖鑑")

if "refresh_token" not in st.session_state:
    st.session_state.refresh_token = 0

if st.sidebar.button("🔄 重新載入 CSV 資料"):
    st.session_state.refresh_token += 1
    st.cache_data.clear()

df_all = load_and_combine_data(st.session_state.refresh_token)

if df_all.empty:
    st.error("❌ 無法載入任何資料，請檢查 CSV 檔案路徑！")
else:
    # --- 側邊欄：進階篩選器 ---
    st.sidebar.header("🔍 篩選條件")
    selected_types = st.sidebar.multiselect(
        "選擇生物種類：", options=["魚類", "昆蟲", "海產"],
        default=["魚類", "昆蟲", "海產"]
    )
    search_query = st.sidebar.text_input("搜尋生物名稱（如：海天使、皇帶魚）：")
    month_filter = st.sidebar.selectbox(
        "切換月份限定：", options=["全部"] + [f"{i}月" for i in range(1, 13)]
    )

    # --- 資料過濾計算邏輯 ---
    filtered_df = df_all[df_all["種類"].isin(selected_types)]

    if search_query:
        filtered_df = filtered_df[filtered_df["名稱"].astype(str).str.contains(search_query, na=False)]

    if month_filter != "全部":
        target_int = int(month_filter.replace("月", ""))
        month_mask = filtered_df["出沒月份"].apply(lambda x: is_month_in_range(x, target_int))
        filtered_df = filtered_df[month_mask]

    # --- 主要內容 ---
    st.metric("📊 目前篩選結果", f"{len(filtered_df)} 筆生物")
    st.markdown("---")

    st.subheader("📋 生物圖鑑")

    if filtered_df.empty:
        st.warning("⚠️ 沒有符合篩選條件的生物。")
    else:
        records = filtered_df.to_dict(orient="records")
 
        CARDS_PER_ROW = 3  # 電腦上每列 3 張卡片；手機自動變成單欄
        for i in range(0, len(records), CARDS_PER_ROW):
            row_items = records[i:i + CARDS_PER_ROW]
            cols = st.columns(CARDS_PER_ROW)
            for col, item in zip(cols, row_items):
                with col:
                    with st.container(border=True):
                        render_image(item["圖片網址"], width=100)
                        st.markdown(f"**{item['名稱']}**")
                        st.caption(f"🏷️ {item['種類']}")
                        st.write(f"💰 價格：{item['價格']}")
                        st.write(f"📅 月份：{item['出沒月份']}")
                        st.write(f"⏰ 時間：{item['出沒時間']}")
 
