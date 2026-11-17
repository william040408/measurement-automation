# UP/UN 경계 판정 기준 — 앱 시작 시 app_settings.json 값으로 덮어씀
MARGIN_LIMIT = 0.003   # 절대값 기준 (mm)
RATIO_LIMIT  = 0.85    # 비율 기준 (0–1)
# OR | AND | MARGIN_ONLY | RATIO_ONLY
MODE = "OR"


def update(margin_limit=None, ratio_limit=None, mode=None):
    global MARGIN_LIMIT, RATIO_LIMIT, MODE
    if margin_limit is not None:
        MARGIN_LIMIT = float(margin_limit)
    if ratio_limit is not None:
        RATIO_LIMIT = float(ratio_limit)
    if mode is not None:
        MODE = str(mode)
