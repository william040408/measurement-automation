"""
CMM 화면 OCR 측정값 추출 모듈

사용법:
    from core.ocr_extractor import extract_measurements
    result = extract_measurements(pil_img)
    # result: {"format_key", "format_name", "items", "row_count", "di_count"}
    # or None if format cannot be detected
"""

import re
import numpy as np
from PIL import Image, ImageEnhance

_engine = None

# 모듈 레벨 패턴 상수
_DI_PAT       = re.compile(r'D\s*[Il1]\s*=')
_Y_LABEL_PAT  = re.compile(r'Y\s*=\s*([-+]?\d+\.?\d*)')
_LEADING_NUM  = re.compile(r'^([-+]?\d+\.?\d*)\s*[A-Za-z]')
# 행번호 OCR 오독 대비 폴백 패턴 (5자리→4자리→3자리 순)
_ROW_FALLBACK_PATS = [r"^0\d{3}$", r"^\d{3}$"]


def _get_engine():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
    return _engine


def _fix_num(s):
    s = re.sub(r'[Oo]', '0', s)
    s = re.sub(r'[Il](?=\d)', '1', s)
    s = re.sub(r'(\d)[,:\|](\d)', r'\1.\2', s)
    return s


def _is_number(s):
    s = _fix_num(s.replace(' ', ''))
    return bool(re.match(r'^[-+]?\d+\.?\d*$', s))


def _to_float(s):
    return float(_fix_num(s.replace(' ', '')))


def _in_range(text, row_range):
    """text를 int로 변환해 row_range 안에 있으면 True. row_range=None이면 항상 True."""
    if row_range is None:
        return True
    try:
        return row_range[0] <= int(text) <= row_range[1]
    except (ValueError, TypeError):
        return False


def _extract_di_values(boxes, num_boxes, y_tol=30):
    """DI= 라벨 오른쪽 숫자를 cy 순서대로 수집해 반환."""
    di_boxes = [b for b in boxes if _DI_PAT.search(b["text"])]
    result = []
    for di in sorted(di_boxes, key=lambda b: b["cy"]):
        cands = [n for n in num_boxes
                 if abs(n["cy"] - di["cy"]) < y_tol and n["lx"] > di["rx"]]
        if cands:
            nearest = min(cands, key=lambda n: n["lx"] - di["rx"])
            try:
                v = _to_float(nearest["text"])
                result.append({
                    "value":  v,
                    "score":  nearest["score"],
                    "raw":    nearest["text"],
                    "di_cy":  di["cy"],
                    "val_lx": nearest["lx"],
                })
            except ValueError:
                pass
    return result


def _do_extract(fmt_cfg, fmt_key, boxes, num_boxes, di_values_ordered, row_order, row_cy):
    """포맷 설정과 행 정보를 받아 측정값 dict를 반환."""

    # x_offset 자동 보정
    x_offset = 0
    if di_values_ordered:
        x_offset = int(di_values_ordered[0]["val_lx"]) - fmt_cfg["ref_di_val_lx"]

    col_x = fmt_cfg["col_x"]
    col_w = fmt_cfg["col_w"]
    col_y = fmt_cfg["col_y"]
    COL_X_LO = col_x[0] + x_offset;  COL_X_HI = col_x[1] + x_offset
    COL_W_LO = col_w[0] + x_offset;  COL_W_HI = col_w[1] + x_offset
    COL_Y_LO = col_y[0] + x_offset;  COL_Y_HI = col_y[1] + x_offset

    di_cys       = [d["di_cy"] for d in di_values_ordered]
    fallback_cfg = fmt_cfg.get("cy_fallback", {})

    def get_fallback_cy_range(label):
        if label not in fallback_cfg or not di_cys:
            return None
        lo_idx, lo_off, hi_idx, hi_off = fallback_cfg[label]
        try:
            return (max(0, di_cys[lo_idx] + lo_off), di_cys[hi_idx] + hi_off)
        except IndexError:
            return None

    def get_y_range(row_num):
        try:
            row_int = int(row_num)
        except (ValueError, TypeError):
            return None
        if row_int not in row_order:
            return None
        idx = row_order.index(row_int)
        cy  = row_cy[row_int]
        # 3px 여유를 y0에서 빼서 CMM 측정값이 행 라벨보다 위에 표시될 때의 경계 문제 방지
        y0  = ((row_cy[row_order[idx - 1]] + cy) / 2) - 3 if idx > 0 else cy - 80
        y1  = (cy + row_cy[row_order[idx + 1]]) / 2 if idx + 1 < len(row_order) else cy + 80
        return y0, y1

    def _scan_nums(y0, y1, lx_lo, lx_hi, val_ok):
        out = []
        for n in num_boxes:
            if not (y0 <= n["cy"] <= y1):
                continue
            if not (lx_lo <= n["lx"] <= lx_hi):
                continue
            try:
                v = _to_float(n["text"])
            except ValueError:
                continue
            if val_ok and not val_ok(v):
                continue
            out.append((n, v))
        return out

    def nums_in_row(row_num, lx_lo, lx_hi, val_ok=None, label=None):
        row_yr = get_y_range(row_num)
        yr = row_yr if row_yr is not None else (get_fallback_cy_range(label) if label else None)
        if yr is None:
            return []
        out = _scan_nums(yr[0], yr[1], lx_lo, lx_hi, val_ok)
        # 행 기반 탐색이 실패하면 cy_fallback 범위로 재시도
        if not out and row_yr is not None and label:
            fb_yr = get_fallback_cy_range(label)
            if fb_yr:
                out = _scan_nums(fb_yr[0], fb_yr[1], lx_lo, lx_hi, val_ok)
        return out

    def _y_search(y0, y1, val_ok):
        """y 범위 안에서 Y= 패턴 또는 COL_Y 컬럼 숫자를 탐색."""
        for b in sorted(boxes, key=lambda b: b["cy"]):
            if not (y0 <= b["cy"] <= y1):
                continue
            m = _Y_LABEL_PAT.search(b["text"])
            if m:
                try:
                    v = _to_float(m.group(1))
                    if val_ok is None or val_ok(v):
                        return {"value": v, "score": b["score"], "raw": b["text"]}
                except ValueError:
                    pass
        for b in sorted(boxes, key=lambda b: b["cy"]):
            if not (y0 <= b["cy"] <= y1):
                continue
            if not (COL_Y_LO <= b["lx"] <= COL_Y_HI):
                continue
            m = _LEADING_NUM.match(b["text"].strip())
            if m:
                try:
                    v = _to_float(m.group(1))
                    if val_ok is None or val_ok(v):
                        return {"value": v, "score": b["score"], "raw": b["text"]}
                except ValueError:
                    pass
        for n in sorted(num_boxes, key=lambda x: x["cy"]):
            if not (y0 <= n["cy"] <= y1):
                continue
            if not (COL_Y_LO <= n["lx"] <= COL_Y_HI):
                continue
            try:
                v = _to_float(n["text"])
                if val_ok is None or val_ok(v):
                    return {"value": v, "score": n["score"], "raw": n["text"]}
            except ValueError:
                pass
        return None

    def y_val_in_row(row_num, label, val_ok=None):
        row_yr = get_y_range(row_num)
        yr = row_yr if row_yr is not None else (get_fallback_cy_range(label) if label else None)
        if yr is None:
            return None
        result = _y_search(yr[0], yr[1], val_ok)
        # 행 기반 탐색이 실패하면 cy_fallback 범위로 재시도
        if result is None and row_yr is not None and label:
            fb_yr = get_fallback_cy_range(label)
            if fb_yr:
                result = _y_search(fb_yr[0], fb_yr[1], val_ok)
        return result

    pos_val_ok  = fmt_cfg.get("pos_val_ok",  {})
    yval_val_ok = fmt_cfg.get("yval_val_ok", {})

    items  = []
    di_idx = 0

    for t in fmt_cfg["targets"]:
        label, row_num, ext_type = t[0], t[1], t[2]

        if ext_type == "di":
            d = di_values_ordered[di_idx] if di_idx < len(di_values_ordered) else None
            di_idx += 1
            items.append({
                "label": label,
                "value": d["value"] if d else None,
                "score": d["score"] if d else 0.0,
                "raw":   d["raw"]   if d else "?",
            })

        elif ext_type == "yval":
            val_ok = yval_val_ok.get(label)
            d = y_val_in_row(row_num, label, val_ok)
            items.append({
                "label": label,
                "value": d["value"] if d else None,
                "score": d["score"] if d else 0.0,
                "raw":   d["raw"]   if d else "?",
            })

        elif ext_type == "pos_x":
            val_ok = pos_val_ok.get(label)
            cands  = nums_in_row(row_num, COL_X_LO, COL_X_HI, val_ok, label=label)
            if cands:
                n, v = min(cands, key=lambda x: x[0]["cy"])
                items.append({"label": label, "value": v, "score": n["score"], "raw": n["text"]})
            else:
                items.append({"label": label, "value": None, "score": 0.0, "raw": "?"})

        elif ext_type == "pos_w":
            val_ok = pos_val_ok.get(label)
            cands  = nums_in_row(row_num, COL_W_LO, COL_W_HI, val_ok, label=label)
            if cands:
                n, v = min(cands, key=lambda x: x[0]["cy"])
                items.append({"label": label, "value": v, "score": n["score"], "raw": n["text"]})
            else:
                items.append({"label": label, "value": None, "score": 0.0, "raw": "?"})

    return {
        "format_key":  fmt_key,
        "format_name": fmt_cfg["name"],
        "items":       items,
        "row_count":   len(row_order),
        "di_count":    len(di_values_ordered),
    }


def extract_measurements(pil_img, _log=None):
    """
    PIL 이미지에서 CMM 측정값을 추출합니다.

    _log: list를 넘기면 진단 로그 문자열들이 append됨.
    """
    from config.ocr_formats import FORMAT_CONFIGS
    from datetime import datetime

    def L(msg):
        if _log is not None:
            _log.append(str(msg))

    # -- 1. 전처리 -------------------------------------------------
    pil_img = pil_img.convert("RGB")
    w, h = pil_img.size
    L(f"=== OCR 진단 로그  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    L(f"이미지: {w}x{h}px")
    pil_img = ImageEnhance.Contrast(pil_img).enhance(1.8)
    base = np.array(pil_img)

    col_row_end   = int(w * 0.10)
    col_val_start = int(w * 0.20)
    col_val_end   = int(w * 0.97)
    strip = np.concatenate([
        base[:, 0:col_row_end, :],
        base[:, col_val_start:col_val_end, :]
    ], axis=1)
    strip_w = col_row_end + (col_val_end - col_val_start)
    L(f"strip: 행번호 0~{col_row_end}px + 값 {col_val_start}~{col_val_end}px = strip_w {strip_w}px")

    # strip_w < 700px이면 OCR 정확도 향상을 위해 업스케일
    SCALE = 1.0
    if strip_w < 500:
        SCALE = 3.0
    elif strip_w < 700:
        SCALE = 2.0
    L(f"SCALE: {SCALE}")

    strip_ocr = strip
    if SCALE > 1.0:
        sh, sw = strip.shape[:2]
        strip_ocr = np.array(
            Image.fromarray(strip).resize(
                (int(sw * SCALE), int(sh * SCALE)), Image.LANCZOS
            )
        )

    # -- 2. OCR ---------------------------------------------------
    engine = _get_engine()
    result, _ = engine(strip_ocr)
    if not result:
        L("OCR 결과 없음 → None 반환")
        return None

    # -- 3. 박스 정리 (strip x → 원본 x 복원) ----------------------
    boxes = []
    for item in result:
        box, text, score = item[0], item[1], item[2]
        cy   = (sum(p[1] for p in box) / 4) / SCALE
        s_lx = (min(p[0] for p in box)) / SCALE
        s_rx = (max(p[0] for p in box)) / SCALE
        if s_lx < col_row_end:
            lx, rx = s_lx, s_rx
        else:
            lx = s_lx - col_row_end + col_val_start
            rx = s_rx - col_row_end + col_val_start
        boxes.append({"text": text, "score": score, "cy": cy, "lx": lx, "rx": rx})
    L(f"\n=== OCR 박스 전체 ({len(boxes)}개) ===")
    for b in sorted(boxes, key=lambda x: x["cy"]):
        L(f"  cy={b['cy']:5.0f}  lx={b['lx']:5.0f}  rx={b['rx']:5.0f}  score={b['score']:.2f}  text={repr(b['text'])}")

    num_boxes = [b for b in boxes if _is_number(b["text"])]

    # -- 3.5 DI= 순서 기반 매칭 (포맷 감지 전에 수행) --------------
    # DI= 추출은 행번호와 무관하므로 먼저 수행해 폴백에서도 활용
    di_values_ordered = _extract_di_values(boxes, num_boxes)
    L(f"\n=== DI= 값 ({len(di_values_ordered)}개) ===")
    for i, d in enumerate(di_values_ordered):
        L(f"  [{i}] cy={d['di_cy']:.0f}  val={d['value']}  raw={repr(d['raw'])}")

    # -- 4. 포맷 감지 (행번호 패턴 + 수치 범위 매칭) ---------------
    # OCR 해상도에 따라 "00163" / "0163" / "163" 등 다양하게 읽힐 수 있으므로
    # 기본 패턴 실패 시 폴백 패턴을 순서대로 시도
    fmt_cfg   = None
    fmt_key   = None
    row_order = []
    row_cy    = {}

    L("\n=== 포맷 감지 ===")
    for key, cfg in FORMAT_CONFIGS.items():
        row_range = cfg.get("row_range")
        cands = []

        for pat_str in [cfg["row_pat"]] + _ROW_FALLBACK_PATS:
            pat   = re.compile(pat_str)
            trial = []
            for b in boxes:
                t = b["text"].strip()
                if not pat.match(t):
                    continue
                if b["lx"] >= w * 0.12:
                    continue
                if not _in_range(t, row_range):
                    continue
                trial.append(b)
            if len(trial) >= 3:
                cands = sorted(trial, key=lambda b: b["cy"])
                break

        if len(cands) < 3:
            L(f"  {key}: 행번호 {len(cands)}개 (3개 미만 → 스킵)")
            continue

        # di_check: 같은 row_range를 공유하는 포맷 구분 (예: short vs short_1ea)
        di_check = cfg.get("di_check")
        if di_check and di_values_ordered:
            idx = di_check.get("index", 0)
            lo, hi = di_check.get("range", (0, float("inf")))
            if idx < len(di_values_ordered):
                val = di_values_ordered[idx]["value"]
                if not (lo <= val <= hi):
                    L(f"  {key}: 행번호 {len(cands)}개 → di_check 실패 (DI[{idx}]={val}, 범위 {lo}~{hi})")
                    continue
            else:
                L(f"  {key}: 행번호 {len(cands)}개 → di_check 인덱스 부족 ({idx} >= {len(di_values_ordered)})")
                continue
        fmt_cfg   = cfg
        fmt_key   = key
        # 정수 키로 저장해 "00163" / "0163" / "163" 모두 동일하게 매칭
        row_order = []
        row_cy    = {}
        for r in cands:
            try:
                k = int(r["text"].strip())
                row_order.append(k)
                row_cy[k] = r["cy"]
            except ValueError:
                pass
        L(f"  {key}: ✅ 감지됨  행번호 {len(row_order)}개  {row_order[:3]}{'...' if len(row_order)>3 else ''}")
        break

    # -- 4.5 포맷 미감지 폴백: DI= 앵커만으로 각 포맷 시도 --------
    # 행번호 OCR이 완전히 실패해도 DI= 값이 있으면 cy_fallback 기반으로 추출
    if fmt_cfg is None:
        L("\n포맷 미감지 → DI= cy_fallback 폴백 시도")
        if not di_values_ordered:
            L("DI= 값도 없음 → None 반환")
            return None
        best_result = None
        best_score  = -1
        for key, cfg in FORMAT_CONFIGS.items():
            candidate = _do_extract(cfg, key, boxes, num_boxes,
                                    di_values_ordered, [], {})
            if candidate is not None:
                score = sum(1 for item in candidate["items"]
                            if item["value"] is not None)
                L(f"  폴백 {key}: {score}개 추출")
                if score > best_score:
                    best_score  = score
                    best_result = candidate
        if best_result:
            L(f"  폴백 선택: {best_result.get('format_key')}  {best_score}개")
        return best_result

    # -- 5. 추출 실행 ----------------------------------------------
    result = _do_extract(fmt_cfg, fmt_key, boxes, num_boxes,
                         di_values_ordered, row_order, row_cy)
    if result and _log is not None:
        L("\n=== 추출 결과 ===")
        for it in result["items"]:
            flag = "✅" if it["value"] is not None else "❌"
            L(f"  {flag} {it['label']}: {it['value']}  (raw={repr(it['raw'])})")
    return result
