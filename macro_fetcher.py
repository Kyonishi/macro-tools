#!/usr/bin/env python3
"""
宏观市场数据获取器 v1.0
用途: 从 Yahoo Finance 拉取市场数据，写入 Supabase

用法:
  回填历史 (只跑一次):  python macro_fetcher.py backfill 10y
  每日更新 (GitHub Actions 自动跑): python macro_fetcher.py daily
"""

import sys
import os
import warnings
warnings.filterwarnings('ignore')

import yfinance as yf
import pandas as pd
from supabase import create_client
from datetime import datetime

# ── 从环境变量读取，绝对不要硬编码在代码里 ──
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')

# ── 追踪的资产 ──
ASSETS = {
    'DXY':    'DX-Y.NYB',
    'Gold':   'GC=F',
    'BTC':    'BTC-USD',
    'ETH':    'ETH-USD',
    'Oil':    'CL=F',
    'SP500':  '^GSPC',
    'Nasdaq': '^IXIC',
    'Silver': 'SI=F',
}


def fetch_and_upsert(period: str = '5d') -> int:
    if not SUPABASE_URL or not SUPABASE_KEY:
        print('❌ 缺少环境变量 SUPABASE_URL 或 SUPABASE_KEY')
        sys.exit(1)

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    print(f'\n📡 拉取数据 (period={period})...\n')
    rows = []

    for asset, ticker in ASSETS.items():
        try:
            raw = yf.download(ticker, period=period,
                              auto_adjust=True, progress=False)
            if raw.empty:
                print(f'  ⚠️  {asset:<8} 无数据')
                continue

            # yfinance 有时返回 MultiIndex，压平处理
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.droplevel(1)

            for date, row in raw.iterrows():
                rows.append({
                    'date':   date.strftime('%Y-%m-%d'),
                    'asset':  asset,
                    'ticker': ticker,
                    'close':  float(row['Close']) if pd.notna(row.get('Close')) else None,
                    'open':   float(row['Open'])  if pd.notna(row.get('Open'))  else None,
                    'high':   float(row['High'])  if pd.notna(row.get('High'))  else None,
                    'low':    float(row['Low'])   if pd.notna(row.get('Low'))   else None,
                    'volume': float(row['Volume']) if 'Volume' in row and pd.notna(row.get('Volume')) else None,
                })
            print(f'  ✅  {asset:<8} {len(raw)} 条')

        except Exception as e:
            print(f'  ❌  {asset:<8} 错误: {e}')

    if not rows:
        print('\n⚠️  没有任何数据，退出。')
        return 0

    # 分批 upsert（每批 500 条，避免超时）
    print(f'\n💾 写入 Supabase ({len(rows)} 条)...')
    batch_size = 500
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        supabase.table('market_daily') \
                .upsert(batch, on_conflict='date,asset') \
                .execute()
        print(f'  批次 {i // batch_size + 1}: {len(batch)} 条 ✅')

    print(f'\n🎉 完成！共写入 {len(rows)} 条数据')
    print(f'   时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    return len(rows)


if __name__ == '__main__':
    mode   = sys.argv[1] if len(sys.argv) > 1 else 'daily'
    period = sys.argv[2] if len(sys.argv) > 2 else '10y'

    if mode == 'backfill':
        print(f'🔄 回填模式，周期: {period}')
        fetch_and_upsert(period=period)

    elif mode == 'daily':
        print('📅 每日更新模式')
        fetch_and_upsert(period='5d')  # 拉5天防止节假日漏数据

    else:
        print(f'❌ 未知模式: {mode}，可选: backfill / daily')
        sys.exit(1)
