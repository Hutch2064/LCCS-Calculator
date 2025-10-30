import streamlit as st
import pandas as pd
from calculator_core import compute_recommendation

st.set_page_config(page_title="Long Call Calendar Spread Calculator", page_icon="📈", layout="wide")

st.title("Long Call Calendar Spread Calculator")
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
        for col in ["Average Volume", "IV30 Days RV30 Days", "Term Structure Slope 0-45 Days"]:
            if col in df.columns:
                df[col] = df[col].map({True: "✅ PASS", False: "❌ FAIL"})

        st.subheader("Results")

        # Show a clean DataFrame without row index
        st.dataframe(df.reset_index(drop=True), use_container_width=True)

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






