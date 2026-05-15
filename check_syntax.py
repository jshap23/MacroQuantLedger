import ast
files = [
    'app.py',
    'config.py',
    'models/schema.py',
    'storage/persistence.py',
    'storage/fred_client.py',
    'storage/trade_prices.py',
    'services/talking_points.py',
    'services/llm_polish.py',
    'components/status_bar.py',
    'components/macro_views.py',
    'components/asset_views.py',
    'components/briefing_strip.py',
    'components/briefing.py',
    'components/reconciliation.py',
    'components/fred_panel.py',
    'components/trades.py',
    'export/excel.py',
    'export/obsidian.py',
]
all_ok = True
for f in files:
    try:
        ast.parse(open(f).read())
        print(f'OK: {f}')
    except SyntaxError as e:
        print(f'FAIL: {f} — {e}')
        all_ok = False
if all_ok:
    print('\nAll files pass syntax check.')
