"""Internal subprocess, deliberately keeps third-party errors off UI/logs."""
import sys


def main():
    import akshare as ak
    from quantlab.market_rules import validate_symbol
    source, symbol, start, end, output = sys.argv[1:]
    market = validate_symbol(symbol)
    if source == "tencent":
        df = ak.stock_zh_a_hist_tx(symbol=market + symbol, start_date=start, end_date=end,
                                   adjust="", timeout=12)
        # AKShare 1.19.1 excludes sz000* from its lot->share conversion.
        # Reconcile amount/volume against OHLC to catch that upstream ambiguity.
        active = (df.volume > 0) & (df.amount > 0)
        if not active.any():
            raise ValueError("No volume/amount to verify units")
        implied = df.loc[active, "amount"] / df.loc[active, "volume"]
        low, high = df.loc[active, "low"] * .98, df.loc[active, "high"] * 1.02
        if ((implied >= low) & (implied <= high)).all():
            pass
        elif ((implied / 100 >= low) & (implied / 100 <= high)).all():
            df["volume"] = df.volume * 100
        else:
            raise ValueError("Cannot verify Tencent volume/amount units")
    else:
        start, end = start.replace("-", ""), end.replace("-", "")
        df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start,
                                end_date=end, adjust="", timeout=12)
        df = df.rename(columns={"日期": "date", "开盘": "open", "收盘": "close", "最高": "high",
                                "最低": "low", "成交量": "volume", "成交额": "amount"})
        df["volume"] = df["volume"] * 100  # Eastmoney reports lots, 100 shares per lot.
    cols = [c for c in ("date", "open", "high", "low", "close", "volume", "amount") if c in df]
    df[cols].to_csv(output, index=False)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(1)
