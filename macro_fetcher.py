#!/usr/bin/env python3
"""
宏观市场数据获取器 v2.0
新增: FRED 宏观指标 (美联储利率/CPI/M2/国债收益率)
新增资产: VIX / 铜价 / EUR/USD / JPY

用法:
  首次回填: python macro_fetcher.py backfill 10y
  每日更新: python macro_fetcher.py daily
"""

import sys, os, warnings
warnings.filterwarnings('ignore')

import yfinance as yf
import pandas as pd
import requests
from supabase import create_client
from datetime import datetime, timedelta

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
FRED_KEY     = os.environ.get('FRED_API_KEY')

# ── 价格资产 → market_daily ──
ASSETS = {
    'DXY':    'DX-Y.NYB',
    'Gold':   'GC=F',
    'BTC':    'BTC-USD',
    'ETH':    'ETH-USD',
    'Oil':    'CL=F',
    'SP500':  '^GSPC',
    'Nasdaq': '^IXIC',
    'Silver': 'SI=F',
    'VIX':    '^VIX',
    'Copper': 'HG=F',
    'EURUSD': 'EURUSD=X',
    'JPYUSD': 'JPY=X',
}

# ── FRED 指标 → macro_indicators ──
FRED_SERIES = {
    'yield_2y':     {'id': 'DGS2',     'unit': '%',        'frequency': 'daily'},
    'yield_10y':    {'id': 'DGS10',    'unit': '%',        'frequency': 'daily'},
    'yield_spread': {'id': 'T10Y2Y',   'unit': '%',        'frequency': 'daily'},
    'fed_rate':     {'id': 'FEDFUNDS', 'unit': '%',        'frequency': 'monthly'},
    'cpi':          {'id': 'CPIAUCSL', 'unit': 'index',    'frequency': 'monthly'},
    'core_cpi':     {'id': 'CPILFESL', 'unit': 'index',    'frequency': 'monthly'},
    'm2':           {'id': 'M2SL',     'unit': 'billions', 'frequency': 'monthly'},
}

def get_supabase():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print('❌ 缺少 SUPABASE_URL 或 SUPABASE_KEY')
        sys.exit(1)
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def fetch_prices(period='5d'):
    sb = get_supabase()
    print(f'\n📡 价格数据 (period={period})...\n')
    rows = []
    for asset, ticker in ASSETS.items():
        try:
            raw = yf.download(ticker, period=period, auto_adjust=True, progress=False)
            if raw.empty:
                print(f'  ⚠️  {asset:<10} 无数据'); continue
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.droplevel(1)
            for date, row in raw.iterrows():
                rows.append({
                    'date': date.strftime('%Y-%m-%d'), 'asset': asset, 'ticker': ticker,
                    'close':  float(row['Close'])  if pd.notna(row.get('Close'))  else None,
                    'open':   float(row['Open'])   if pd.notna(row.get('Open'))   else None,
                    'high':   float(row['High'])   if pd.notna(row.get('High'))   else None,
                    'low':    float(row['Low'])    if pd.notna(row.get('Low'))    else None,
                    'volume': float(row['Volume']) if 'Volume' in row and pd.notna(row.get('Volume')) else None,
                })
            print(f'  ✅  {asset:<10} {len(raw)} 条')
        except Exception as e:
            print(f'  ❌  {asset:<10} {e}')
    for i in range(0, len(rows), 500):
        sb.table('market_daily').upsert(rows[i:i+500], on_conflict='date,asset').execute()
    print(f'\n  💾 价格写入完成：{len(rows)} 条')
    return len(rows)

def fetch_macro(period='5d'):
    if not FRED_KEY:
        print('\n  ⚠️  未设置 FRED_API_KEY，跳过宏观指标')
        print('     申请: https://fred.stlouisfed.org/docs/api/api_key.html')
        return 0
    sb = get_supabase()
    days = {'5d':10,'1mo':40,'3mo':100,'6mo':200,'1y':400,'2y':750,'5y':1900,'10y':3700}.get(period, 400)
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    print(f'\n📊 FRED 指标 (从 {cutoff})...\n')
    rows = []
    for name, meta in FRED_SERIES.items():
        try:
            resp = requests.get('https://api.stlouisfed.org/fred/series/observations', params={
                'series_id': meta['id'], 'api_key': FRED_KEY,
                'file_type': 'json', 'limit': 1000, 'sort_order': 'desc'
            }, timeout=15)
            obs = resp.json().get('observations', [])
            count = 0
            for o in obs:
                if o['date'] < cutoff: continue
                try: val = float(o['value'])
                except: continue
                rows.append({'date': o['date'], 'indicator': name, 'value': val,
                             'frequency': meta['frequency'], 'unit': meta['unit'], 'source': 'fred'})
                count += 1
            print(f'  ✅  {name:<15} {count} 条')
        except Exception as e:
            print(f'  ❌  {name:<15} {e}')
    for i in range(0, len(rows), 500):
        sb.table('macro_indicators').upsert(rows[i:i+500], on_conflict='date,indicator').execute()
    print(f'\n  💾 宏观指标写入完成：{len(rows)} 条')
    return len(rows)

if __name__ == '__main__':
    mode   = sys.argv[1] if len(sys.argv) > 1 else 'daily'
    period = sys.argv[2] if len(sys.argv) > 2 else '10y'
    yf_p   = period if mode == 'backfill' else '5d'
    print(f'{"🔄 回填" if mode=="backfill" else "📅 每日"} | {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print('=' * 50)
    fetch_prices(yf_p)
    fetch_macro(yf_p)
    print('\n🎉 全部完成')
