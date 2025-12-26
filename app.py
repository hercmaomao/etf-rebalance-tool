import streamlit as st
import pandas as pd
import json

# 页面配置
st.set_page_config(page_title="ETF调仓辅助助手", layout="wide")

st.title("⚖️ ETF 持仓偏离分析与调仓助手")

# --- 1. 加载配置 ---
try:
    with open('config.json', 'r', encoding='utf-8') as f:
        CONFIG = json.load(f)
except FileNotFoundError:
    st.error("❌ 配置文件 config.json 未找到，请确保文件在项目根目录下。")
    st.stop()

TARGET_WEIGHTS = CONFIG['target_weights']
COLS = CONFIG['columns']

# --- 3. 核心计算函数 ---
def analyze_data(df):
    # 列名映射与检查，提高健壮性
    # 从配置中获取列名
    col_acc = COLS['account_id']
    col_ticker = COLS['ticker']
    col_mv = COLS['market_value']
    
    required_cols = {col_acc, col_ticker, col_mv}
    if not required_cols.issubset(df.columns):
        # 尝试简单的列名清洗或映射，这里仅做简单提示
        missing = required_cols - set(df.columns)
        st.error(f"数据缺失必要列: {missing}。请确保Excel包含: {required_cols}")
        return pd.DataFrame()

    df[col_ticker] = df[col_ticker].astype(str).str.strip().str.upper()
    results = []
    
    # 获取所有账号的分组
    for acc_id, group in df.groupby(col_acc):
        total_mv = group[col_mv].sum()
        row = {col_acc: str(acc_id)}
        total_abs_diff = 0.0
        holdings_mv = {} # 暂存各Ticker市值用于后续组合计算
        
        for ticker, target_wgt in TARGET_WEIGHTS.items():
            # 计算实际比例
            actual_mv = group[group[col_ticker] == ticker][col_mv].sum()
            holdings_mv[ticker] = actual_mv
            actual_ratio = actual_mv / total_mv if total_mv > 0 else 0
            
            # 计算差距 (实际 - 目标)
            diff = actual_ratio - target_wgt
            total_abs_diff += abs(diff)
            
            # 展示格式：10.50% (偏离 +1.50%)
            diff_str = f"{diff:+.2%}" if diff != 0 else "0.00%"
            row[ticker] = f"{actual_ratio:.2%} ({diff_str})"
            
        drift_divisor = CONFIG['app_settings'].get('drift_divisor', 2.0)
        row["总偏离率"] = total_abs_diff / drift_divisor

        # --- 轻舟规则计算 ---
        # 1. VTI + SPY
        actual_us = holdings_mv.get('VTI', 0) + holdings_mv.get('SPY', 0)
        target_us = TARGET_WEIGHTS.get('VTI', 0) + TARGET_WEIGHTS.get('SPY', 0)
        ratio_us = actual_us / total_mv if total_mv > 0 else 0

        # 2. MCHI + ASHR
        actual_cn = holdings_mv.get('MCHI', 0) + holdings_mv.get('ASHR', 0)
        target_cn = TARGET_WEIGHTS.get('MCHI', 0) + TARGET_WEIGHTS.get('ASHR', 0)
        ratio_cn = actual_cn / total_mv if total_mv > 0 else 0

        # 3. 判定逻辑: 任意一个组合偏离 > 2%
        is_warning = abs(ratio_us - target_us) > 0.02 or abs(ratio_cn - target_cn) > 0.02
        labels = CONFIG.get('status_labels', {"warning": "🚨 需调仓", "normal": "✅ 正常"})
        row["轻舟预警状态"] = labels['warning'] if is_warning else labels['normal']

        # 4. 组合比例展示 (带偏离度) - 移到状态后面
        diff_us = ratio_us - target_us
        diff_us_str = f"{diff_us:+.2%}" if diff_us != 0 else "0.00%"
        row["VTI+SPY 比例"] = f"{ratio_us:.2%} ({diff_us_str})"

        diff_cn = ratio_cn - target_cn
        diff_cn_str = f"{diff_cn:+.2%}" if diff_cn != 0 else "0.00%"
        row["MCHI+ASHR 比例"] = f"{ratio_cn:.2%} ({diff_cn_str})"
        
        results.append(row)
    
    return pd.DataFrame(results)

# --- 4. 文件上传逻辑 ---
uploaded_file = st.file_uploader("上传持仓 Excel", type=['xlsx', 'xls'])

if uploaded_file:
    try:
        user_df = pd.read_excel(uploaded_file)
        if user_df.empty:
            st.warning("上传的文件为空")
            st.stop()
            
        analysis_res = analyze_data(user_df)
        
        if analysis_res.empty:
            st.stop()

        # --- 5. 构建“目标置顶行” ---
        # 创建一行与结果表结构一样的数据，作为对比基准
        target_row = {
            COLS['account_id']: "🎯 目标持仓标准",
            "总偏离率": 0.0,
            "轻舟预警状态": "REFERENCE"
        }
        for ticker, target_wgt in TARGET_WEIGHTS.items():
            target_row[ticker] = f"{target_wgt:.2%} (0.00%)"
        
        # 补充组合目标比例
        t_us = TARGET_WEIGHTS.get('VTI', 0) + TARGET_WEIGHTS.get('SPY', 0)
        target_row["VTI+SPY 比例"] = f"{t_us:.2%} (0.00%)"
        t_cn = TARGET_WEIGHTS.get('MCHI', 0) + TARGET_WEIGHTS.get('ASHR', 0)
        target_row["MCHI+ASHR 比例"] = f"{t_cn:.2%} (0.00%)"
        
        target_df = pd.DataFrame([target_row])
        
        # 合并：目标行在上，用户行在下
        final_display_df = pd.concat([target_df, analysis_res], ignore_index=True)
        
        # 调整列顺序：将组合比例挪到预警状态后面，方便查看
        cols_order = [COLS['account_id'], "总偏离率", "轻舟预警状态", "VTI+SPY 比例", "MCHI+ASHR 比例"] + list(TARGET_WEIGHTS.keys())
        final_display_df = final_display_df[cols_order]
        
        # --- 6. 渲染表格并美化 ---
        st.subheader("持仓对比分析表")
        
        with st.expander("ℹ️ 规则说明：盈米规则 vs 轻舟规则"):
            st.markdown("""
            *   **盈米规则 (总偏离率)**: `Sum(|实际权重 - 目标权重|) / 2`。表示为了恢复目标比例，需要交易的总资产比例。
            *   **轻舟规则 (预警状态)**: 
                *   若 `VTI+SPY` 组合偏离 > 2% 或 `MCHI+ASHR` 组合偏离 > 2%，则触发“🚨 需调仓”。
            """)
            
        st.caption("提示：括号内百分比表示 [实际占比 - 目标占比]。正数代表超配，负数代表欠配。")

        def style_dataframe(df):
            # 定义样式：第一行(目标行)加粗变色，预警行文字变红
            warning_label = CONFIG.get('status_labels', {}).get('warning', "🚨")
            return df.style.apply(lambda x: [
                'background-color: #f0f2f6; font-weight: bold;' if x.name == 0 
                else ('color: red;' if warning_label in str(x['轻舟预警状态']) else '') 
                for _ in x], axis=1).format({"总偏离率": "{:.2%}"})

        st.dataframe(style_dataframe(final_display_df), use_container_width=True)

        # 下载功能
        csv = final_display_df.to_csv(index=False).encode('utf_8_sig')
        st.download_button("📥 导出分析报告", csv, "ETF_Analysis.csv", "text/csv")

    except Exception as e:
        st.error(f"解析失败，请检查Excel列名是否符合配置文件要求。报错: {e}")