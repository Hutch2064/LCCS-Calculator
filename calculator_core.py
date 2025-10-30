# ==========================================================
# CORE LOGIC — Streamlit-compatible version (renamed only)
# ==========================================================
import yfinance as yf
from datetime import datetime, timedelta
from scipy.interpolate import interp1d
import numpy as np
import time
import traceback
import pandas as pd

# ---------------------------
# Helpers: retry + polite delay
# ---------------------------

def _sleep(s):
    try:
        time.sleep(s)
    except Exception:
        pass

def _is_rate_limit(err: Exception) -> bool:
    msg = str(err).lower()
    return ("429" in msg) or ("too many" in msg) or ("rate limit" in msg) or ("temporarily unavailable" in msg)

def with_retry(fn, *, attempts=4, base_wait=5.0, between_calls_delay=1.2, desc=""):
    """Retry wrapper for yfinance calls with exponential backoff."""
    last_err = None
    wait = base_wait
    for i in range(attempts):
        try:
            out = fn()
            _sleep(between_calls_delay)
            return out
        except Exception as e:
            last_err = e
            if _is_rate_limit(e):
                print(f"[{desc}] Rate limited. Cooling down {wait:.1f}s (attempt {i+1}/{attempts})...")
                _sleep(wait)
                wait *= 2.0
                continue
            else:
                print(f"[{desc}] Non rate-limit error: {e}")
                break
    raise last_err if last_err else RuntimeError(f"{desc} failed")

# ---------------------------
# Core analytics (identical to your version)
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

    close_vol = log_cc_sq.rolling(window=window).sum() / (window - 1.0)
    open_vol  =  log_oc_sq.rolling(window=window).sum() / (window - 1.0)
    window_rs = rs.rolling(window=window).sum() / (window - 1.0)

    k = 0.34 / (1.34 + ((window + 1) / (window - 1)))
    result = (open_vol + k * close_vol + (1 - k) * window_rs).apply(np.sqrt) * np.sqrt(trading_periods)

    return result.iloc[-1] if return_last_only else result.dropna()

def build_term_structure(days, ivs):
    days = np.array(days)
    ivs  = np.array(ivs)

    sort_idx = days.argsort()
    days = days[sort_idx]
    ivs  = ivs[sort_idx]

    spline = interp1d(days, ivs, kind='linear', fill_value="extrapolate")

    def term_spline(dte):
        if dte < days[0]:
            return ivs[0]
        elif dte > days[-1]:
            return ivs[-1]
        else:
            return float(spline(dte))
    return term_spline

def get_current_price_yf(ticker_obj: yf.Ticker):
    # Try fast path first
    try:
        fp = getattr(ticker_obj, "fast_info", None)
        if fp is not None and getattr(fp, "last_price", None) is not None:
            return float(fp.last_price)
    except Exception:
        pass

    # Fallback to 1d history with retry
    def _call():
        return ticker_obj.history(period='1d', auto_adjust=False, actions=False)
    todays_data = with_retry(_call, desc="history(1d)")
    return float(todays_data['Close'].iloc[-1])

# ---------------------------
# Main logic used by Streamlit
# ---------------------------

def compute_recommendation(ticker):
    try:
        ticker = ticker.strip().upper()
        if not ticker:
            return {"Ticker": ticker, "error": "No stock symbol provided."}

        stock = yf.Ticker(ticker)
        all_opts = list(getattr(stock, "options", []) or [])
        if len(all_opts) == 0:
            return {"Ticker": ticker, "error": f"No options found for {ticker}."}

        try:
            exp_dates = filter_dates(all_opts)
        except Exception:
            return {"Ticker": ticker, "error": "Not enough option data."}
        exp_dates = exp_dates[:12]

        options_chains = {}
        for exp_date in exp_dates:
            def _call_chain(d=exp_date):
                return stock.option_chain(d)
            chain = with_retry(_call_chain, desc=f"option_chain({exp_date})")
            options_chains[exp_date] = chain

        try:
            underlying_price = get_current_price_yf(stock)
            if underlying_price is None:
                raise ValueError("No market price found.")
        except Exception:
            return {"Ticker": ticker, "error": "Unable to retrieve stock price."}

        atm_iv = {}
        straddle = None
        for i, (exp_date, chain) in enumerate(options_chains.items()):
            calls = chain.calls
            puts  = chain.puts
            if calls.empty or puts.empty:
                continue

            call_idx = (calls['strike'] - underlying_price).abs().idxmin()
            put_idx  = (puts['strike']  - underlying_price).abs().idxmin()

            call_iv = float(calls.loc[call_idx, 'impliedVolatility'])
            put_iv  = float(puts.loc[put_idx,  'impliedVolatility'])
            atm_iv[exp_date] = (call_iv + put_iv) / 2.0

            if i == 0:
                call_bid = calls.loc[call_idx, 'bid']
                call_ask = calls.loc[call_idx, 'ask']
                put_bid  = puts.loc[put_idx,  'bid']
                put_ask  = puts.loc[put_idx,  'ask']

                def safe_mid(bid, ask, fallback):
                    if pd.notna(bid) and pd.notna(ask) and bid > 0 and ask > 0:
                        return (bid + ask) / 2.0
                    elif pd.notna(fallback) and fallback > 0:
                        return fallback
                    else:
                        return np.nan

                call_mid = safe_mid(call_bid, call_ask, calls.loc[call_idx, 'lastPrice'])
                put_mid  = safe_mid(put_bid,  put_ask,  puts.loc[put_idx,  'lastPrice'])
                straddle = call_mid + put_mid if pd.notna(call_mid) and pd.notna(put_mid) else np.nan

        if not atm_iv:
            return {"Ticker": ticker, "error": "Could not determine ATM IV."}

        today = datetime.today().date()
        dtes, ivs = [], []
        for exp_date, iv in atm_iv.items():
            d = datetime.strptime(exp_date, "%Y-%m-%d").date()
            dtes.append((d - today).days)
            ivs.append(iv)
        ivs = [v * 100.0 for v in ivs]
        term_spline   = build_term_structure(dtes, ivs)
        ts_slope_0_45 = (term_spline(45) - term_spline(dtes[0])) / (45 - dtes[0])

        def _hist():
            return stock.history(period='3mo', auto_adjust=False, actions=False)
        price_history = with_retry(_hist, desc="history(3mo)")
        iv30_rv30     = term_spline(30) / yang_zhang(price_history)
        avg_volume    = float(price_history['Volume'].rolling(30).mean().dropna().iloc[-1])
        expected_move = f"{round((straddle / underlying_price) * 100, 2)}%" if straddle else None

        print(f"DEBUG: avg_volume={avg_volume:.2f}, iv30_rv30={iv30_rv30:.3f}, ts_slope_0_45={ts_slope_0_45:.5f}, expected_move={expected_move}")

        return {
            "Ticker": ticker,
            "Average Volume": avg_volume >= 1_500_000,
            "IV30 Days RV30 Days": iv30_rv30 >= 1.25,
            "Term Structure Slope 0-45 Days": ts_slope_0_45 <= -0.00406,
            "Expected Move": expected_move,
        }

    except Exception as e:
        traceback.print_exc()
        return {"Ticker": ticker, "error": str(e)}
