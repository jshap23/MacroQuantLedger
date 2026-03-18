import ast
files = [
    'app.py',
    'components/macro_views.py',
    'components/quant_tracker.py',
    'components/reconciliation.py',
    'components/status_bar.py',
    'models/schema.py',
    'storage/persistence.py',
    'export/excel.py',
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
