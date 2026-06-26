#!/usr/bin/env python3
"""
宏观市场数据获取器 v3.0
新增: 实际利率 / PCE / 全球M2 / BTC主导率 / 稳定币市值 / 恐惧贪婪指数历史

用法:
  python macro_fetcher.py backfill 10y
  python macro_fetcher.py daily
"""

import sys, os, warnings, time
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
    # 每日
    'yield_2y':       {'id': 'DGS2',           'unit': '%',        'frequency': 'daily'},
    'yield_10y':      {'id': 'DGS10',           'unit': '%',        'frequency': 'daily'},
    'yield_spread':   {'id': 'T10Y2Y',          'unit': '%',        'frequency': 'daily'},
    'real_yield_10y': {'id': 'DFII10',          'unit': '%',        'frequency': 'daily'},
    # 月度
    'fed_rate':       {'id': 'FEDFUNDS',        'unit': '%',        'frequency': 'monthly'},
    'cpi':            {'id': 'CPIAUCSL',        'unit': 'index',    'frequency': 'monthly'},
    'core_cpi':       {'id': 'CPILFESL',        'unit': 'index',    'frequency': 'monthly'},
    'pce':            {'id': 'PCEPI',           'unit': 'index',    'frequency': 'monthly'},
    'core_pce':       {'id': 'PCEPILFE',        'unit': 'index',    'frequency': 'monthly'},
    'm2':             {'id': 'M2SL',            'unit': 'billions', 'frequency': 'monthly'},
    'm2_euro':        {'id': 'MABMM301EZM189S', 'unit': 'billions', 'frequency': 'monthly'},
    'm2_japan':       {'id': 'MYAGM2JPM189S',   'unit': 'billions', 'frequency': 'monthly'},
    'm2_china':       {'id': 'MYAGM2CNM189S',   'unit': 'billions', 'frequency': 'monthly'},
}

def get_sb():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print('❌ 缺少 SUPABASE_URL 或 SUPABASE_KEY'); sys.exit(1)
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def upsert(sb, table, rows, conflict):
    for i in range(0, len(rows), 500):
        sb.table(table).upsert(rows[i:i+500], on_conflict=conflict).execute()

# ═══════════════════════════════════
# 1. 价格数据
# ═══════════════════════════════════
def fetch_prices(period='5d'):
    sb = get_sb()
    print(f'\n📡 价格数据 (period={period})...\n')
    rows = []
    for asset, ticker in ASSETS.items():
        try:
            raw = yf.download(ticker, period=period, auto_adjust=True, progress=False)
            if raw.empty: print(f'  ⚠️  {asset:<10} 无数据'); continue
            if isinstance(raw.columns, pd.MultiIndex): raw.columns = raw.columns.droplevel(1)
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
    upsert(sb, 'market_daily', rows, 'date,asset')
    print(f'\n  💾 价格写入完成：{len(rows)} 条')
    return len(rows)

# ═══════════════════════════════════
# 2. FRED 宏观指标
# ═══════════════════════════════════
def fetch_macro(period='5d'):
    if not FRED_KEY:
        print('\n  ⚠️  未设置 FRED_API_KEY，跳过'); return 0
    sb = get_sb()
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
            print(f'  ✅  {name:<18} {count} 条')
            time.sleep(0.3)  # FRED 限速保护
        except Exception as e:
            print(f'  ❌  {name:<18} {e}')
    upsert(sb, 'macro_indicators', rows, 'date,indicator')
    print(f'\n  💾 FRED 指标写入完成：{len(rows)} 条')
    return len(rows)

# ═══════════════════════════════════
# 3. CoinGecko 指标（BTC主导率 + 稳定币）
# ═══════════════════════════════════
def fetch_coingecko():
    sb = get_sb()
    print('\n🪙 CoinGecko 指标...\n')
    rows = []
    try:
        resp = requests.get('https://api.coingecko.com/api/v3/global', timeout=15)
        data = resp.json().get('data', {})
        today = datetime.now().strftime('%Y-%m-%d')

        # BTC 主导率
        btc_dom = data.get('market_cap_percentage', {}).get('btc')
        if btc_dom:
            rows.append({'date': today, 'indicator': 'btc_dominance',
                         'value': round(btc_dom, 2), 'frequency': 'daily',
                         'unit': '%', 'source': 'coingecko'})
            print(f'  ✅  btc_dominance    {btc_dom:.2f}%')

        # 稳定币市值（USDT + USDC，换算成十亿美元）
        total_mc = data.get('total_market_cap', {}).get('usd', 0)
        usdt_pct = data.get('market_cap_percentage', {}).get('usdt', 0)
        usdc_pct = data.get('market_cap_percentage', {}).get('usdc', 0)
        if total_mc:
            stable_b = (usdt_pct + usdc_pct) / 100 * total_mc / 1e9
            rows.append({'date': today, 'indicator': 'stablecoin_mcap',
                         'value': round(stable_b, 1), 'frequency': 'daily',
                         'unit': 'billions', 'source': 'coingecko'})
            print(f'  ✅  stablecoin_mcap  ${stable_b:.0f}B')

    except Exception as e:
        print(f'  ❌  CoinGecko: {e}')

    if rows:
        upsert(sb, 'macro_indicators', rows, 'date,indicator')
    return len(rows)

# ═══════════════════════════════════
# 4. 恐惧贪婪指数历史（Alternative.me）
# ═══════════════════════════════════
def fetch_fear_greed(limit=2000):
    sb = get_sb()
    print('\n😱 恐惧贪婪指数历史...\n')
    try:
        resp = requests.get(f'https://api.alternative.me/fng/?limit={limit}', timeout=15)
        data = resp.json().get('data', [])
        rows = []
        for d in data:
            date = datetime.fromtimestamp(int(d['timestamp'])).strftime('%Y-%m-%d')
            rows.append({'date': date, 'indicator': 'fear_greed',
                         'value': int(d['value']), 'frequency': 'daily',
                         'unit': 'index', 'source': 'alternative.me'})
        upsert(sb, 'macro_indicators', rows, 'date,indicator')
        print(f'  ✅  fear_greed  {len(rows)} 条')
        return len(rows)
    except Exception as e:
        print(f'  ❌  恐惧贪婪指数: {e}'); return 0

# ═══════════════════════════════════
# 主入口
# ═══════════════════════════════════
if __name__ == '__main__':
    mode   = sys.argv[1] if len(sys.argv) > 1 else 'daily'
    period = sys.argv[2] if len(sys.argv) > 2 else '10y'
    yf_p   = period if mode == 'backfill' else '5d'
    fg_lim = 2000   if mode == 'backfill' else 7

    print(f'{"🔄 回填" if mode=="backfill" else "📅 每日"} | {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print('=' * 55)

    p = fetch_prices(yf_p)
    m = fetch_macro(yf_p)
    c = fetch_coingecko()
    f = fetch_fear_greed(fg_lim)

    print(f'\n🎉 全部完成 | 价格={p} 宏观={m} CoinGecko={c} 恐惧贪婪={f}')
