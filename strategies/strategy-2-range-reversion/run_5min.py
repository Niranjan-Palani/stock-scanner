from dataclasses import replace
from data_loader import load_bars
from strategy import run_backtest, Params
from metrics import summarize
import pandas as pd

TICKERS = ['F','T','PLTR','SOFI','NIO','AAL','CCL','PBR','KGC','GRAB',
    'RIG','VALE','WBD','UAA','OPEN','CLSK','RIOT','MARA','AMCR','KVUE',
    'HBAN','KEY','CFG','RF','NCLH','UAL','DKNG','LYFT','PARA','SIRI']

base = Params(max_hold_bars=48)  # 4h at 5m bars (was 16 bars = 4h at 15m)

all_trades = []
for sym in TICKERS:
    df = load_bars(sym, '5min')
    trades, equity = run_backtest(df, base, timeframe_minutes=5)
    all_trades.extend(trades)

m = summarize(all_trades, pd.Series(dtype=float), timeframe_minutes=5)
print('5-min timeframe, full sample, 30 tickers')
print('date range:', end=' ')
df0 = load_bars(TICKERS[0], '5min')
print(df0.index.min(), '->', df0.index.max(), f'({len(df0)} bars)')
print(m)

all_trades.sort(key=lambda t: t.entry_time)
equity = 100.0
risk_pct = 0.01
peak = equity
max_dd = 0.0
wins = losses = 0
for t in all_trades:
    risk_dollars = equity * risk_pct
    pnl_dollars = risk_dollars * t.r_multiple
    equity += pnl_dollars
    peak = max(peak, equity)
    dd = (equity - peak) / peak
    max_dd = min(max_dd, dd)
    if t.pnl_pct > 0: wins += 1
    else: losses += 1

print()
print('Trades used in sim:', len(all_trades))
print('Wins/Losses:', wins, losses)
print('Final equity from $100 start:', round(equity,2))
print('Total return: {:.2f}%'.format((equity/100-1)*100))
print('Max drawdown: {:.2f}%'.format(max_dd*100))
