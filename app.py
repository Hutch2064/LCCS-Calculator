# ==========================================================
# LONG CALL CALENDAR SPREAD CALCULATOR — Streamlit Version
# Verbatim legacy logic, identical calculations (with IV scaling + diagnostics)
# ==========================================================

import streamlit as st
import yfinance as yf
from datetime import datetime, timedelta
from scipy.interpolate import interp1d
import numpy as np
import pandas as pd
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import requests
import gc

# ---------------------------
# Helper functions (verbatim)
# ---------------------------

def filter_dates(dates):
    today = datetime.today().date()
    cutoff_date = today + timedelta(days=45)
    sorted_dates = sorted(datetime.strptime(date, "%Y-%m-%d").date() for date in dates)

    arr = []
    for i, date in enumerate(sorted_dates):
        if date >= cutoff_date:
            arr = [d.strftime("%Y-%m-%d") for d in sorted_dates[:i+1]]
            break

    if len(arr) > 0:
        if arr[0] == today.strftime("%Y-%m-%d"):
            return arr[1:]
        return arr

    raise ValueError("No date 45 days or more in the future found.")


def yang_zhang(price_data, window=30, trading_periods=252, return_last_only=True):
    log_ho = (price_data['High'] / price_data['Open']).apply(np.log)
    log_lo = (price_data['Low'] / price_data['Open']).apply(np.log)
    log_co = (price_data['Close'] / price_data['Open']).apply(np.log)

    log_oc = (price_data['Open'] / price_data['Close'].shift(1)).apply(np.log)
    log_oc_sq = log_oc**2

    log_cc = (price_data['Close'] / price_data['Close'].shift(1)).apply(np.log)
    log_cc_sq = log_cc**2

    rs = log_ho * (log_ho - log_co) + log_lo * (log_lo - log_co)

    close_vol = log_cc_sq.rolling(
        window=window,
        center=False
    ).sum() * (1.0 / (window - 1.0))

    open_vol = log_oc_sq.rolling(
        window=window,
        center=False
    ).sum() * (1.0 / (window - 1.0))

    window_rs = rs.rolling(
        window=window,
        center=False
    ).sum() * (1.0 / (window - 1.0))

    k = 0.34 / (1.34 + ((window + 1) / (window - 1)) )
    result = (open_vol + k * close_vol + (1 - k) * window_rs).apply(np.sqrt) * np.sqrt(trading_periods)

    if return_last_only:
        return result.iloc[-1]
    else:
        return result.dropna()


def build_term_structure(days, ivs):
    days = np.array(days)
    ivs = np.array(ivs)

    sort_idx = days.argsort()
    days = days[sort_idx]
    ivs = ivs[sort_idx]

    spline = interp1d(days, ivs, kind='linear', fill_value="extrapolate")

    def term_spline(dte):
        if dte < days[0]:
            return ivs[0]
        elif dte > days[-1]:
            return ivs[-1]
        else:
            return float(spline(dte))

    return term_spline


def get_current_price(ticker):
    todays_data = ticker.history(period='1d')
    return todays_data['Close'][0]


def compute_recommendation(ticker):
    try:
        ticker = ticker.strip().upper()
        if not ticker:
            return "No stock symbol provided."

        try:
            stock = yf.Ticker(ticker)
            if len(stock.options) == 0:
                raise KeyError()
        except KeyError:
            return f"Error: No options found for stock symbol '{ticker}'."

        exp_dates = list(stock.options)
        try:
            exp_dates = filter_dates(exp_dates)
        except:
            return "Error: Not enough option data."

        options_chains = {}
        for exp_date in exp_dates:
            options_chains[exp_date] = stock.option_chain(exp_date)

        try:
            underlying_price = get_current_price(stock)
            if underlying_price is None:
                raise ValueError("No market price found.")
        except Exception:
            return "Error: Unable to retrieve underlying stock price."

        atm_iv = {}
        straddle = None
        i = 0
        for exp_date, chain in options_chains.items():
            calls = chain.calls
            puts = chain.puts

            if calls.empty or puts.empty:
                continue

            call_diffs = (calls['strike'] - underlying_price).abs()
            call_idx = call_diffs.idxmin()
            call_iv = calls.loc[call_idx, 'impliedVolatility']

            put_diffs = (puts['strike'] - underlying_price).abs()
            put_idx = put_diffs.idxmin()
            put_iv = puts.loc[put_idx, 'impliedVolatility']

            atm_iv_value = (call_iv + put_iv) / 2.0
            atm_iv[exp_date] = atm_iv_value

        if i == 0:
            call_bid = calls.loc[call_idx, 'bid']
            call_ask = calls.loc[call_idx, 'ask']
            put_bid  = puts.loc[put_idx,  'bid']
            put_ask  = puts.loc[put_idx,  'ask']

            def safe_mid(bid, ask, last):
                if pd.notna(bid) and pd.notna(ask) and bid > 0 and ask > 0:
                    return (bid + ask) / 2.0
                elif pd.notna(last) and last > 0:
                    return float(last)
                else:
                    return np.nan

        call_mid = safe_mid(call_bid, call_ask, calls.loc[call_idx, 'lastPrice'])
        put_mid  = safe_mid(put_bid,  put_ask,  puts.loc[put_idx,  'lastPrice'])

        if pd.notna(call_mid) and pd.notna(put_mid):
            straddle = float(call_mid + put_mid)
        else:
            straddle = None

            i += 1

        if not atm_iv:
            return "Error: Could not determine ATM IV for any expiration dates."

        today = datetime.today().date()
        dtes = []
        ivs = []
        for exp_date, iv in atm_iv.items():
            exp_date_obj = datetime.strptime(exp_date, "%Y-%m-%d").date()
            days_to_expiry = (exp_date_obj - today).days
            dtes.append(days_to_expiry)
            ivs.append(iv)

        term_spline = build_term_structure(dtes, ivs)
        ts_slope_0_45 = (term_spline(45) - term_spline(dtes[0])) / (45 - dtes[0])

        price_history = stock.history(period='3mo')
        iv30_rv30 = term_spline(30) / yang_zhang(price_history)

        avg_volume = price_history['Volume'].rolling(30).mean().dropna().iloc[-1]

        expected_move = str(round(straddle / underlying_price * 100,2)) + "%" if straddle else None

        raw_values = {
            'avg_volume_raw': avg_volume,
            'iv30_rv30_raw': iv30_rv30,
            'ts_slope_0_45_raw': ts_slope_0_45
        }

        return {
            'avg_volume': avg_volume >= 1500000,
            'iv30_rv30': iv30_rv30 >= 1.25,
            'ts_slope_0_45': ts_slope_0_45 <= -0.00406,
            'expected_move': expected_move,
            **raw_values
        }
    except Exception:
        raise Exception('Error occured processing')


# ---------------------------
# Streamlit UI (thin shell)
# ---------------------------
st.set_page_config(page_title="Earnings Position Checker", page_icon="📈", layout="wide")
st.title("📈 Earnings Position Checker (Streamlit)")

ticker = st.text_input("Enter Stock Symbol:", "AAPL")
run = st.button("Submit")

if run:
    try:
        result = compute_recommendation(ticker)
        if isinstance(result, str):
            st.error(result)
        else:
            avg_volume_bool = result['avg_volume']
            iv30_rv30_bool = result['iv30_rv30']
            ts_slope_bool = result['ts_slope_0_45']
            expected_move = result['expected_move']

            if avg_volume_bool and iv30_rv30_bool and ts_slope_bool:
                title = "Recommended"
                title_color = "green"
            elif ts_slope_bool and ((avg_volume_bool and not iv30_rv30_bool) or (iv30_rv30_bool and not avg_volume_bool)):
                title = "Consider"
                title_color = "orange"
            else:
                title = "Avoid"
                title_color = "red"

            st.markdown(f"### <span style='color:{title_color}'>{title}</span>", unsafe_allow_html=True)
            st.write(f"avg_volume: {'PASS' if avg_volume_bool else 'FAIL'}")
            st.write(f"iv30_rv30: {'PASS' if iv30_rv30_bool else 'FAIL'}")
            st.write(f"ts_slope_0_45: {'PASS' if ts_slope_bool else 'FAIL'}")
            st.write(f"Expected Move: {expected_move}")

            st.markdown("---")
            st.subheader("Raw Values for Verification")
            st.write(f"Average Volume (Raw): {result.get('avg_volume_raw', 'N/A'):,}")
            st.write(f"IV30/RV30 (Raw): {result.get('iv30_rv30_raw', 'N/A'):.4f}")
            st.write(f"Term Structure Slope 0-45 (Raw): {result.get('ts_slope_0_45_raw', 'N/A'):.6f}")

            st.markdown("---")
            st.subheader("Selection Criteria")
            st.write("✅ avg_volume ≥ 1,500,000")
            st.write("✅ iv30_rv30 ≥ 1.25")
            st.write("✅ ts_slope_0_45 ≤ -0.00406")

    except Exception as e:
        st.error(str(e))


# ==========================================================
# Screener Mode: Earnings Next 5 Days
# ==========================================================
st.markdown("---")
st.subheader("Screener: Earnings in Next Trading Day")

from pandas.tseries.offsets import BDay

def get_upcoming_earnings(days_ahead=1):
    today = datetime.now().date()
    tickers = set()
    for i in range(days_ahead + 1):
        query_date = today + timedelta(days=i)
        url = f"https://api.nasdaq.com/api/calendar/earnings?date={query_date.strftime('%Y-%m-%d')}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json, text/plain, */*",
        }
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                rows = data.get("data", {}).get("rows", [])
                for row in rows:
                    symbol = row.get("symbol")
                    if symbol:
                        tickers.add(symbol.strip().upper())
        except Exception:
            continue
    return sorted(list(tickers))

# ----------------------------------------------------------
# Run Screener button and progress output
# ----------------------------------------------------------
if st.button("Run Screener"):
    try:
        st.info("Fetching upcoming earnings tickers from Nasdaq...")
        tickers = get_upcoming_earnings(5)
        st.write(f"Found {len(tickers)} tickers with earnings in next 5 days.")

        if len(tickers) == 0:
            st.warning("No upcoming earnings found. Nasdaq data may refresh overnight (try again later).")
        else:
            # Defensive cleanup to prevent session contamination between Yahoo calls
            try:
                yf.utils._requests.session.close()
            except Exception:
                pass
            gc.collect()

            progress_bar = st.progress(0)
            results = []
            total = len(tickers)
            done = 0

            # Limit max workers & throttle slightly to avoid Yahoo rate-limits
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {executor.submit(compute_recommendation, t): t for t in tickers if t.isalpha() and len(t) <= 5}
                for future in as_completed(futures):
                    t = futures[future]
                    try:
                        res = future.result()
                        if isinstance(res, dict):
                            a, b, c = res['avg_volume'], res['iv30_rv30'], res['ts_slope_0_45']
                            if a and b and c:
                                results.append({
                                    'Ticker': t,
                                    'Average Volume (Raw)': f"{res['avg_volume_raw']:,}",
                                    'IV30/RV30 (Raw)': f"{res['iv30_rv30_raw']:.4f}",
                                    'Term Slope 0–45 (Raw)': f"{res['ts_slope_0_45_raw']:.6f}",
                                    'Expected Move': res['expected_move']
                                })
                    except Exception:
                        pass
                    done += 1
                    progress_bar.progress(min(int(done / total * 100), 100))
                    time.sleep(0.25)  # small delay to avoid throttling

            # Close Yahoo session cleanly again
            try:
                yf.utils._requests.session.close()
            except Exception:
                pass
            gc.collect()

            if len(results) == 0:
                st.warning("No stocks met all criteria.")
            else:
                st.success(f"{len(results)} stocks passed all criteria.")
                st.dataframe(pd.DataFrame(results))

    except Exception as e:
        st.error(f"Error running screener: {e}")



