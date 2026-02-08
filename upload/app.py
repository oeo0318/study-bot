import streamlit as st
import os

st.title("📂 多資料夾檔案上傳工具")

# --- 設定四個目標資料夾 ---
# 根目錄為當前執行腳本的位置
BASE_DIR = "."

UPLOAD_DIRS = {
    "自然": os.path.join(BASE_DIR, "upload/natural"),
    "社會": os.path.join(BASE_DIR, "upload/social"),
    "國文": os.path.join(BASE_DIR, "upload/chinese"),
    "數學": os.path.join(BASE_DIR, "upload/math")
}

# 確保所有目標資料夾都存在
for path in UPLOAD_DIRS.values():
    if not os.path.exists(path):
        os.makedirs(path)

# --- 網站介面與邏輯 ---

# 讓使用者選擇要上傳到哪個資料夾
selected_folder_name = st.selectbox("### 1. 選擇資料夾入口", list(UPLOAD_DIRS.keys()))

# 獲取實際的儲存路徑
save_directory = UPLOAD_DIRS[selected_folder_name]

st.write(f"您選擇的路徑是: `{save_directory}`")

# 檔案上傳元件
uploaded_file = st.file_uploader("### 2. 上傳檔案")

if uploaded_file is not None:
    # 直接在目標資料夾內建立檔案，不需要額外子資料夾
    file_path = os.path.join(save_directory, uploaded_file.name)

    # 寫入檔案
    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    st.success(f"✅ 檔案已成功儲存至 **{selected_folder_name}** 資料夾！")
