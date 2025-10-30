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
run_button = st.button("Run", type="primary")

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

        # Ensure the key columns exist
        cols = ["Average Volume", "IV30 Days RV30 Days", "Term Structure Slope 0-45 Days"]

        # Store both numeric values and PASS/FAIL
        for col in cols:
            if col in df.columns:
                # Create numeric copy
                df[col + " (Value)"] = df[col]
                # Replace boolean with PASS/FAIL
                df[col] = df[col].map({True: "✅ PASS", False: "❌ FAIL"})

        # Decision column — only Optimal if all three pass
        df["Decision"] = df.apply(
            lambda row: "✅ Optimal" if all(
                row.get(c) == "✅ PASS" for c in cols
            ) else "❌ Not Optimal",
            axis=1,
        )

        st.subheader("Results")
        st.dataframe(df.reset_index(drop=True), use_container_width=True)

        # Allow download as CSV
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download Results",
            data=csv,
            file_name="Long_Call_Calendar_Spread_Calculator.csv",
            mime="text/csv",
        )

        # Explanatory section
        st.markdown("---")
        st.subheader("Metric Explanations")
        st.markdown(
            """
            **Average Volume (≥ 1.5 million shares)**  
            Liquidity filter — ensures the option chain is active enough for reliable pricing and spreads.

            **IV30 Days / RV30 Days (≥ 1.25)**  
            Ratio of 30-day implied volatility (option-implied) to realized volatility (historical).  
            Values above 1.25 suggest options are pricing in higher future volatility — favorable for calendar spreads.

            **Term Structure Slope 0–45 Days (≤ −0.00406)**  
            Measures how implied volatility changes with time to expiry.  
            A negative slope indicates near-term IV is elevated relative to longer-term IV — ideal for a long call calendar setup.

            **Decision**  
            “✅ Optimal” = all three core filters satisfied.  
            “❌ Not Optimal” = one or more filters failed.
            """
        )

else:
    st.info("Enter tickers above and click 'Run'.")








