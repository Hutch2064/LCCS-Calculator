import streamlit as st
import pandas as pd
from calculator_core import compute_recommendation

# -----------------------------------------------------------
# Streamlit UI
# -----------------------------------------------------------

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

        # Expected columns returned from calculator_core.py
        cols = ["Average Volume", "IV30 Days RV30 Days", "Term Structure Slope 0-45 Days"]

        # Build DataFrame directly from calculator output
        df = pd.DataFrame(results)

        # Add decision column: all three must be PASS
        cols = ["Average Volume", "IV30 Days RV30 Days", "Term Structure Slope 0-45 Days"]
        df["Decision"] = df.apply(
            lambda row: "✅ Optimal" if all("✅ PASS" in str(row.get(c, "")) for c in cols)
            else "❌ Not Optimal",
            axis=1,
        )

        # Add decision column: all three must be PASS
        df["Decision"] = df.apply(
            lambda row: "✅ Optimal" if all(row.get(c) == "✅ PASS" for c in cols) else "❌ Not Optimal",
            axis=1,
        )

        st.subheader("Results")
        st.dataframe(df.reset_index(drop=True), use_container_width=True)

        # Download button
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

# -----------------------------------------------------------
        # Diagnostic section: show raw numeric values for verification
        # -----------------------------------------------------------
        st.markdown("---")
        st.subheader("Raw Metric Values (for verification)")

        # Try to extract raw numbers from calculator output
        numeric_rows = []
        for res in results:
            # You must already have calculator values like avg_volume, iv30_rv30, ts_slope_0_45, expected_move
            # If not, we'll show placeholders
            numeric_rows.append({
                "Ticker": res.get("Ticker", res.get("ticker", "")),
                "Average Volume (Raw)": round(res.get("avg_volume_raw", res.get("avg_volume", 0)), 2)
                    if isinstance(res.get("avg_volume", 0), (int, float)) else "N/A",
                "IV30/RV30 (Raw)": round(res.get("iv30_rv30_raw", res.get("iv30_rv30", 0)), 3)
                    if isinstance(res.get("iv30_rv30", 0), (int, float)) else "N/A",
                "Term Structure Slope 0–45 (Raw)": round(res.get("ts_slope_0_45_raw", res.get("ts_slope_0_45", 0)), 6)
                    if isinstance(res.get("ts_slope_0_45", 0), (int, float)) else "N/A",
                "Expected Move": res.get("Expected Move", res.get("expected_move", "N/A"))
            })

        raw_df = pd.DataFrame(numeric_rows)
        st.dataframe(raw_df, use_container_width=True)

else:
    st.info("Enter tickers above and click 'Run'.")


