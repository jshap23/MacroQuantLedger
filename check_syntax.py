import ast
files = [
    'app.py',
    'config.py',
    'models/schema.py',
    'models/interview.py',
    'storage/persistence.py',
    'storage/fred_client.py',
    'storage/trade_prices.py',
    'storage/interview_store.py',
    'storage/user_settings.py',
    'services/talking_points.py',
    'services/llm_polish.py',
    'services/interview_llm.py',
    'services/interview_prompts.py',
    'services/interview_speech.py',
    'services/interview_speech_worker.py',
    'services/interview_controller.py',
    'services/topic_views.py',
    'components/status_bar.py',
    'components/today.py',
    'components/macro_views.py',
    'components/asset_views.py',
    'components/briefing_strip.py',
    'components/interview_practice.py',
    'components/topic_views.py',
    'components/interview_speech.py',
    'components/reconciliation.py',
    'components/fred_panel.py',
    'components/trades.py',
    'components/attribution.py',
    'export/common.py',
    'export/excel.py',
    'export/topics.py',
    'storage/topic_view_markdown.py',
    'storage/topic_view_sync.py',
    'validate_topic_view_sync.py',
    'setup_speech_runtime.py',
    'launch.py',
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
