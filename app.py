import os
import re
import urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
import requests
from PIL import Image
from io import BytesIO

# --- 網頁基礎設定 ---
st.set_page_config(page_title="動森全生物即時圖鑑", page_icon="🏝️", layout="wide")

# 設定儲存 CSV 的資料夾路徑
# 使用相對路徑，讓程式不論在本機或部署到 Streamlit Cloud 都能正確找到資料
# CSV 檔案需放在與本程式同一層的 "data" 資料夾內
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAVE_FOLDER = os.path.join(BASE_DIR, "data")

# 模擬瀏覽器標頭，防止網站防盜鏈阻擋 Streamlit 讀取圖片
IMG_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://kkplay3c.net/"
}


# --- 智慧網址轉譯函式 ---
def encode_chinese_url(url):
    """
    對網址的路徑(含每一段)與 query string 做安全編碼，
    避免中文字出現在路徑中間或 query string 時無法正確編碼。
    """
    if pd.isna(url) or not isinstance(url, str) or not url.startswith("http"):
        return url
    try:
        parsed_url = urllib.parse.urlparse(url)

        # 對路徑每一段都做 quote（原本只處理最後一段）
        path_parts = parsed_url.path.split("/")
        encoded_parts = [urllib.parse.quote(p) for p in path_parts]
        new_path = "/".join(encoded_parts)

        # 對 query string 做編碼（保留 key=value 結構）
        if parsed_url.query:
            query_pairs = urllib.parse.parse_qsl(parsed_url.query, keep_blank_values=True)
            new_query = urllib.parse.urlencode(query_pairs)
        else:
            new_query = parsed_url.query

        return parsed_url._replace(path=new_path, query=new_query).geturl()
    except Exception:
        return url


# --- 智慧圖片下載器（破解防盜鏈，加上快取避免重複下載） ---
@st.cache_data(show_spinner=False, ttl=3600)
def get_safe_image(url):
    try:
        response = requests.get(url, headers=IMG_HEADERS, timeout=5)
        if response.status_code == 200:
            # 快取的是圖片的 bytes，避免快取 PIL Image 物件造成的潛在問題
            return response.content
    except Exception:
        pass
    return None


def render_image(url, width):
    """統一處理圖片顯示邏輯，找不到圖時顯示預設圖"""
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


# --- 讀取並統一欄位資料（加上快取，並提供手動刷新按鈕） ---
@st.cache_data(show_spinner="正在載入資料...")
def load_and_combine_data(_refresh_token=0):
    fish_path = os.path.join(SAVE_FOLDER, "魚類資料庫.csv")
    insect_path = os.path.join(SAVE_FOLDER, "昆蟲資料庫.csv")
    sea_path = os.path.join(SAVE_FOLDER, "海洋生物資料庫.csv")

    all_dfs = []
    target_cols = ["種類", "圖片網址", "名稱", "出沒月份", "出沒時間", "價格"]
    debug_messages = []  # 收集讀取過程中的錯誤，方便排查問題

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

    def try_load_csv(path, type_label, rename_dict, default_values):
        """嘗試讀取 CSV，若失敗會記錄詳細錯誤原因（含常見編碼備援）"""
        if not os.path.exists(path):
            debug_messages.append(f"❌ {type_label}：找不到檔案 → {path}")
            return None

        df = None
        last_error = None
        # 依序嘗試常見編碼，避免 Excel 存成 Big5 / GBK 導致 UTF-8 讀取失敗
        for encoding in ["utf-8", "utf-8-sig", "big5", "cp950", "gbk"]:
            try:
                df = pd.read_csv(path, encoding=encoding)
                if encoding != "utf-8":
                    debug_messages.append(f"⚠️ {type_label}：使用 {encoding} 編碼成功讀取（原本 UTF-8 讀取失敗）")
                break
            except Exception as e:
                last_error = e
                continue

        if df is None:
            debug_messages.append(f"❌ {type_label}：所有編碼嘗試皆失敗 → {last_error}")
            return None

        try:
            df = sanitize_and_align_df(df=df, type_label=type_label, rename_dict=rename_dict, default_values=default_values)
            return df
        except Exception as e:
            debug_messages.append(f"❌ {type_label}：欄位整理失敗 → {e}（實際欄位：{list(df.columns)}）")
            return None

    df_fish = try_load_csv(fish_path, "魚類", {"魚種": "名稱", "售價": "價格"}, {})
    if df_fish is not None:
        all_dfs.append(df_fish)

    df_insect = try_load_csv(insect_path, "昆蟲", {"昆蟲生物": "名稱", "出沒月份(月)": "出沒月份", "售價": "價格"}, {"出沒時間": "全天"})
    if df_insect is not None:
        all_dfs.append(df_insect)

    df_sea = try_load_csv(sea_path, "海產", {"海洋生物": "名稱", "售價": "價格"}, {"出沒時間": "全天"})
    if df_sea is not None:
        all_dfs.append(df_sea)

    if not all_dfs:
        return pd.DataFrame(columns=target_cols), debug_messages

    combined_df = pd.concat(all_dfs, ignore_index=True)
    combined_df["出沒月份"] = combined_df["出沒月份"].astype(str).str.replace(" ", "")
    combined_df["圖片網址"] = combined_df["圖片網址"].apply(encode_chinese_url)
    return combined_df, debug_messages


# --- 月份判斷函式（支援單一數字、範圍、逗號分隔的多組範圍/數字混合、全年） ---
def _check_single_month_token(token, target_month):
    """判斷單一個 token（可能是 '11~2' 這種範圍，也可能是 '7' 這種單一數字）"""
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

    # 支援逗號分隔多組資料，每一組可以是範圍（11~2）或單一數字（7）
    # 例如："11~2,6~9" 或 "3,7,8" 或 "11~2,7"
    if "," in range_str:
        tokens = range_str.split(",")
        return any(_check_single_month_token(t, target_month) for t in tokens)

    # 沒有逗號的單一格式
    return _check_single_month_token(range_str, target_month)


# --- 時間判斷函式（支援單一時段、跨凌晨範圍、逗號分隔多組時段、全天） ---
def _check_single_time_token(token, target_hour):
    """判斷單一個 token（可能是 '16~21' 這種時段，也可能是 '9' 這種單一整點）"""
    token = token.strip()
    if not token:
        return False

    match = re.match(r"^(\d+)~(\d+)$", token)
    if match:
        start, end = int(match.group(1)), int(match.group(2))
        if start <= end:
            return start <= target_hour <= end
        else:
            # 跨凌晨範圍，例如 21~4 代表 21,22,23,0,1,2,3,4 點
            return target_hour >= start or target_hour <= end

    if token.isdigit():
        return int(token) == target_hour

    return False


def is_time_in_range(range_str, target_hour):
    if pd.isna(range_str) or str(range_str) in ("nan", "全天"):
        return True

    range_str = str(range_str).strip()

    # 支援逗號分隔多組時段，例如 "16~21,4~9"
    if "," in range_str:
        tokens = range_str.split(",")
        return any(_check_single_time_token(t, target_hour) for t in tokens)

    return _check_single_time_token(range_str, target_hour)


# --- 網頁介面呈現 ---
st.title("🏝️ 集合啦！動物森友會 - 全生物即時圖鑑")

# 側邊欄：手動刷新按鈕（因為資料讀取現在有快取，CSV 更新後需要手動刷新）
if "refresh_token" not in st.session_state:
    st.session_state.refresh_token = 0

if st.sidebar.button("🔄 重新載入 CSV 資料"):
    st.session_state.refresh_token += 1
    st.cache_data.clear()

df_all, debug_messages = load_and_combine_data(st.session_state.refresh_token)

# 顯示讀取過程中的錯誤/警告訊息（例如某個 CSV 讀取失敗、編碼問題、欄位對不上等）
if debug_messages:
    with st.expander("⚠️ 資料讀取診斷訊息（點我展開）", expanded=True):
        for msg in debug_messages:
            st.write(msg)

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

    # 現在時刻模式：打勾就只顯示現在時間出沒的生物，沒打勾就是全圖鑑
    now_taiwan = datetime.now(ZoneInfo("Asia/Taipei"))
    use_current_time = st.sidebar.checkbox("⏰ 只顯示現在時刻出沒的生物")
    if use_current_time:
        st.sidebar.caption(f"目前判斷時間：{now_taiwan.strftime('%H:%M')}（台灣時間）")

    # --- 資料過濾計算邏輯 ---
    filtered_df = df_all[df_all["種類"].isin(selected_types)]

    if search_query:
        filtered_df = filtered_df[filtered_df["名稱"].astype(str).str.contains(search_query, na=False)]

    if month_filter != "全部":
        target_int = int(month_filter.replace("月", ""))
        month_mask = filtered_df["出沒月份"].apply(lambda x: is_month_in_range(x, target_int))
        filtered_df = filtered_df[month_mask]

    if use_current_time:
        current_hour = now_taiwan.hour
        time_mask = filtered_df["出沒時間"].apply(lambda x: is_time_in_range(x, current_hour))
        filtered_df = filtered_df[time_mask]

    # --- 主要內容 ---
    if use_current_time:
        st.metric("📊 目前篩選結果（現在時刻模式）", f"{len(filtered_df)} 筆生物")
    else:
        st.metric("📊 目前篩選結果", f"{len(filtered_df)} 筆生物")
    st.markdown("---")

    st.subheader("📋 生物圖鑑清單")

    if filtered_df.empty:
        st.warning("⚠️ 沒有符合篩選條件的生物。")
    else:
        # 改用卡片式版面：電腦螢幕會排成多欄，手機（窄螢幕）
        # Streamlit 會自動把欄位改成單欄垂直堆疊，資訊完整不會被擠壓。
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
