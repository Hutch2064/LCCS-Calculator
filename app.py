# ==========================================================
# LONG CALL CALENDAR SPREAD CALCULATOR — Streamlit Version
# Verbatim legacy logic, with PASS/FAIL and raw value display
# ==========================================================

import streamlit as st
import yfinance as yf
from datetime import datetime, timedelta
from scipy.interpolate import interp1d
import numpy as np
import pandas as pd
import traceback

# ==========================================================
# Helper functions
# ==========================================================
def filter_dates(dates):
    today = datetime.today().date()
    cutoff_date = today + timedelta(days=45)
    sorted_dates = sorted(datetime.strptime(date, "%Y-%m-%d").date() for date in dates)

    arr = []
    for i, date in enumerate(sorted_dates):
        if date >= cutoff_date:
            arr = [d.strftime("%Y-%m-%d") for d in sorted_dates[:i + 1]]
            break

    if len(arr) > 0:
        if arr[0] == today.strftime("%Y-%m-%d"):
            return arr[1:]
        return arr
    raise ValueError("No date 45 days or more in the future found.")


def yang_zhang(price_data, window=30, trading_periods=252, return_last_only=True):
    log_ho = (price_data["High"] / price_data["Open"]).apply(np.log)
    log_lo = (price_data["Low"] / price_data["Open"]).apply(np.log)
    log_co = (price_data["Close"] / price_data["Open"]).apply(np.log)

    log_oc = (price_data["Open"] / price_data["Close"].shift(1)).apply(np.log)
    log_oc_sq = log_oc ** 2
    log_cc = (price_data["Close"] / price_data["Close"].shift(1)).apply(np.log)
    log_cc_sq = log_cc ** 2
    rs = log_ho * (log_ho - log_co) + log_lo * (log_lo - log_co)

    close_vol = log_cc_sq.rolling(window=window).sum() / (window - 1.0)
    open_vol = log_oc_sq.rolling(window=window).sum() / (window - 1.0)
    window_rs = rs.rolling(window=window).sum() / (window - 1.0)

    k = 0.34 / (1.34 + ((window + 1) / (window - 1)))
    result = (open_vol + k * close_vol + (1 - k) * window_rs).apply(np.sqrt) * np.sqrt(trading_periods)

    return result.iloc[-1] if return_last_only else result.dropna()


def build_term_structure(days, ivs):
    days = np.array(days)
    ivs = np.array(ivs)
    sort_idx = days.argsort()
    days = days[sort_idx]
    ivs = ivs[sort_idx]
    spline = interp1d(days, ivs, kind="linear", fill_value="extrapolate")

    def term_spline(dte):
        if dte < days[0]:
            return ivs[0]
        elif dte > days[-1]:
            return ivs[-1]
        else:
            return float(spline(dte))

    return term_spline


def get_current_price(ticker):
    todays_data = ticker.history(period="1d", auto_adjust=False, actions=False)
    return todays_data["Close"][0]


def compute_recommendation(ticker):
    try:
        ticker = ticker.strip().upper()
        if not ticker:
            return {"Ticker": ticker, "Error": "No stock symbol provided."}

        stock = yf.Ticker(ticker)
        if len(stock.options) == 0:
            return {"Ticker": ticker, "Error": f"No options found for {ticker}."}

        exp_dates = list(stock.options)
        try:
            exp_dates = filter_dates(exp_dates)
        except Exception:
            return {"Ticker": ticker, "Error": "Not enough option data."}

        options_chains = {}
        for exp_date in exp_dates:
            options_chains[exp_date] = stock.option_chain(exp_date)

        try:
            underlying_price = get_current_price(stock)
            if underlying_price is None:
                raise ValueError("No market price found.")
        except Exception:
            return {"Ticker": ticker, "Error": "Unable to retrieve stock price."}

        atm_iv = {}
        straddle = None
        i = 0
        for exp_date, chain in options_chains.items():
            calls = chain.calls
            puts = chain.puts
            if calls.empty or puts.empty:
                continue

            call_idx = (calls["strike"] - underlying_price).abs().idxmin()
            put_idx = (puts["strike"] - underlying_price).abs().idxmin()
            call_iv = calls.loc[call_idx, "impliedVolatility"]
            put_iv = puts.loc[put_idx, "impliedVolatility"]
            atm_iv[exp_date] = (call_iv + put_iv) / 2.0

            if i == 0:
                call_bid = calls.loc[call_idx, "bid"]
                call_ask = calls.loc[call_idx, "ask"]
                put_bid = puts.loc[put_idx, "bid"]
                put_ask = puts.loc[put_idx, "ask"]

                if call_bid is not None and call_ask is not None:
                    call_mid = (call_bid + call_ask) / 2.0
                else:
                    call_mid = None
                if put_bid is not None and put_ask is not None:
                    put_mid = (put_bid + put_ask) / 2.0
                else:
                    put_mid = None
                if call_mid is not None and put_mid is not None:
                    straddle = call_mid + put_mid
            i += 1

        if not atm_iv:
            return {"Ticker": ticker, "Error": "Could not determine ATM IV."}

        today = datetime.today().date()
        dtes, ivs = [], []
        for exp_date, iv in atm_iv.items():
            d = datetime.strptime(exp_date, "%Y-%m-%d").date()
            dtes.append((d - today).days)
            ivs.append(iv)

        term_spline = build_term_structure(dtes, ivs)
        ts_slope_0_45 = (term_spline(45) - term_spline(dtes[0])) / (45 - dtes[0])

        price_history = stock.history(period="3mo")
        iv30_rv30 = term_spline(30) / yang_zhang(price_history)
        avg_volume = price_history["Volume"].rolling(30).mean().dropna().iloc[-1]

        if straddle is not None and not np.isnan(straddle) and straddle > 0:
            expected_move = f"{round((straddle / underlying_price) * 100, 2)}%"
        else:
            expected_move = "N/A"

        return {
            "Ticker": ticker,
            "Average Volume": f"{'PASS' if avg_volume >= 1_500_000 else 'FAIL'} ({round(avg_volume, 2):,.0f})",
            "IV30/RV30": f"{'PASS' if iv30_rv30 >= 1.25 else 'FAIL'} ({iv30_rv30:.2f})",
            "Term Structure Slope 0–45": f"{'PASS' if ts_slope_0_45 <= -0.00406 else 'FAIL'} ({ts_slope_0_45:.5f})",
            "Expected Move": expected_move,
        }

    except Exception as e:
        traceback.print_exc()
        return {"Ticker": ticker, "Error": str(e)}

# ==========================================================
# Streamlit UI
# ==========================================================
st.set_page_config(page_title="Long Call Calendar Spread Calculator", page_icon="📈", layout="wide")
st.title("📈 Long Call Calendar Spread Calculator")

tickers_text = st.text_area("Enter one or more stock tickers (comma separated):", "AAPL, MSFT, NVDA", height=100)
run_button = st.button("Run", type="primary")

if run_button:
    tickers = [t.strip().upper() for t in tickers_text.split(",") if t.strip()]
    if not tickers:
        st.warning("Please enter at least one ticker.")
    else:
        st.info("Fetching data... please wait ⏳")

        results = [compute_recommendation(t) for t in tickers]
        df = pd.DataFrame(results)

        st.subheader("Results")
        st.dataframe(df, use_container_width=True)

        st.markdown("---")
        st.subheader("Metric Thresholds")
        st.markdown("""
        - **Average Volume ≥ 1.5 million shares**
        - **IV30/RV30 ≥ 1.25**
        - **Term Structure Slope (0–45 Days) ≤ −0.00406**
        """)

else:
    st.info("Enter tickers above and click **Run**.")
