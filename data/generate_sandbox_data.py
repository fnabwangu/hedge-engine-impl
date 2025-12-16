#!/usr/bin/env python3
import pandas as pd
import numpy as np
from datetime import timedelta
import os

def make_etf_prices(ticker, start_date='2022-01-01', days=500, start_price=100.0):
    dates = [pd.Timestamp(start_date) + timedelta(days=i) for i in range(days)]
    rng = np.random.default_rng(abs(hash(ticker)) & 0xFFFFFFFF)
    returns = rng.normal(0, 0.01, days)
    prices = start_price * np.cumprod(1 + returns)
    df = pd.DataFrame({
        'date': dates,
        'ticker': ticker,
        'open': prices,
        'high': prices * 1.01,
        'low': prices * 0.99,
        'close': prices,
        'adj_close': prices,
        'volume': rng.integers(100000, 1000000, days)
    })
    return df

def main():
    os.makedirs('data', exist_ok=True)
    tickers = ['SPY','XLK','XLV','XLY','TLT','IEF','GLD','SHY','SMH','SOXX','SSO']
    frames = []
    for t in tickers:
        frames.append(make_etf_prices(t))
    df = pd.concat(frames).reset_index(drop=True)
    df.to_parquet('data/sandbox_etf_prices.parquet')

    # LETF NAVs (mock)
    letf_frames = []
    base = df[df['ticker']=='SPY'].copy()
    for t in ['SSO','SSO3x']:
        tmp = base[['date','adj_close']].copy()
        tmp['letf_ticker'] = t
        tmp['nav'] = tmp['adj_close'] * (3 if '3x' in t else 2)
        letf_frames.append(tmp[['date','letf_ticker','nav']])
    pd.concat(letf_frames).to_parquet('data/sandbox_letf_navs.parquet')

    # Minimal event calendar
    ev = pd.DataFrame([{
        'date': pd.Timestamp('2023-06-14'),
        'event_type': 'FOMC',
        'name': 'FOMC Jun 2023',
        'metadata': ''
    }])
    ev.to_csv('data/event_calendar.csv', index=False)

    print("Wrote sandbox data to ./data")

if __name__ == '__main__':
    main()
