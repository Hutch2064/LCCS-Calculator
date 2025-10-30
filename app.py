import streamlit as st
import pandas as pd
from calculator_core import compute_recommendation

st.set_page_config(page_title="Earnings Position Checker", page_icon="📈", layout="wide")

st.title("📈 Earnings Position Checker (Web)")
st.markdown(
    "Enter one or more stock tickers separated by commas below, then click **Run Analysis** to see the key option metrics."
)

tickers_text = st.text_area(
    "Enter tickers (comma separated):",
    value="AAPL, MSFT, NVDA",
    height=100,
    placeholder="Example: AAPL, MSFT, NVDA"
)
run_button = st.button("Run Analysis", type="primary")

if run_button:
    tickers = [t.strip().upper() for t in tickers_text.split(",") if t.strip()]
    if not tickers:
        st.warning("Please enter at least one ticker.")
    else:
        st.info("Fetching data... please wait ⏳")
        results = []
        for t in tickers:
            results.append(compute_recommendation(t))

        df = pd.DataFrame(results)

        # Replace boolean True/False with PASS/FAIL strings
        for col in ["avg_volume", "iv30_rv30", "ts_slope_0_45"]:
            if col in df.columns:
                df[col] = df[col].map({True: "✅ PASS", False: "❌ FAIL"})

        st.subheader("Results")

        # Style the DataFrame: center text, color pass/fail
        def highlight_pass_fail(val):
            if isinstance(val, str) and "PASS" in val:
                return "background-color: #d1ffd6"  # light green
            elif isinstance(val, str) and "FAIL" in val:
                return "background-color: #ffd6d6"  # light red
            return ""

        styled_df = df.style.applymap(highlight_pass_fail)
        st.dataframe(styled_df, use_container_width=True)

        # Allow download as CSV
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="💾 Download Results as CSV",
            data=csv,
            file_name="earnings_checker_results.csv",
            mime="text/csv",
        )

else:
    st.info("Enter tickers above and click **Run Analysis**.")


