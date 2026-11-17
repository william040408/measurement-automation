"""
관리자용 리포트 생성기 — 폴더 경로에서 날짜 추출, 파일명에서 호기·차수 추출
"""

import os
import re
from pathlib import Path
from typing import List, Dict, Callable, Optional, Tuple

import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment
from openpyxl.utils import get_column_letter

_TYPE_LABEL   = {"": "표준", "T": "공구교환", "S": "세팅품", "수": "수정품", "other": "기타"}
_TIMING_LABEL = {1: "초품", 2: "중품", 3: "종품"}


# ── 경로 파싱 ──────────────────────────────────────────────────────

def parse_path_metadata(pdf_path: str) -> dict:
    """
    폴더 경로 세그먼트에서 연도·월·일·주야를 추출합니다.

    큰 3차원: .../{YY년}/{YYYY.MM}/{DD일}/{부품}/{주간|야간}/file.pdf
    작은 3차원: .../{YYYY}/{YYYY.MM}/{D}/{주간|야간}/file.pdf
    """
    year = month = day = shift = None

    for part in Path(pdf_path).parts:
        # 연도: "26년" → 2026
        m = re.match(r'^(\d{2})년$', part)
        if m:
            year = 2000 + int(m.group(1))
            continue

        # 연도: "2025" / "2026" 등 4자리 20xx
        m = re.match(r'^(20\d{2})$', part)
        if m:
            year = int(m.group(1))
            continue

        # 월: "2026.09" → 9
        m = re.match(r'^\d{4}\.(\d{2})$', part)
        if m:
            month = int(m.group(1))
            continue

        # 일: "09일" / "9일" → 9
        m = re.match(r'^(\d{1,2})일$', part)
        if m:
            val = int(m.group(1))
            if 1 <= val <= 31:
                day = val
            continue

        # 일 (작은 3차원): 순수 1~31 숫자 폴더 ("8", "12" 등)
        m = re.match(r'^(\d{1,2})$', part)
        if m:
            val = int(m.group(1))
            if 1 <= val <= 31:
                day = val
            continue

        # 주야
        if part in ('주간', '야간'):
            shift = part

    return {'year': year, 'month': month, 'day': day, 'shift': shift}


def parse_filename_parts(filename: str) -> dict:
    """
    파일명에서 호기·차수·종류를 추출합니다.

    예:
      "11-1.pdf"               → machine=11, timing=1, type=""
      "11-1T.pdf"              → machine=11, timing=1, type="T"
      "다이아 프램 6-1 정면n.pdf" → machine=6,  timing=1, type=""
      "파싱불가.pdf"              → machine=0,  timing=0, type="other"
    """
    stem = os.path.splitext(filename)[0]
    # 숫자-숫자(타입?) 패턴, 마지막 매치 사용
    matches = re.findall(r'(\d+)-(\d+)(T|S|수)?', stem)
    if matches:
        machine_s, timing_s, type_s = matches[-1]
        return {'machine': int(machine_s), 'timing': int(timing_s), 'type': type_s}
    return {'machine': 0, 'timing': 0, 'type': 'other'}


# ── 센서바디 (PDF 1개에 부품 1~3개) ─────────────────────────────────

_SB_NAME_RE = re.compile(r'센서바디\s*(\d+)\s*바\s*(\d+)\s*개')


def _item_label(name: str) -> str:
    """'직경 (10) Ø4.6 MIN' → '직경 Ø4.6 MIN' (블록·버전마다 다른 번호 제거)"""
    return re.sub(r'\s*\(\d+\)', '', name).strip()


def _item_key(name: str) -> str:
    return _item_label(name).replace(" ", "")


def _block_indices(r) -> List[int]:
    from modules.messenger import parse_custom_indices
    return parse_custom_indices(r if isinstance(r, list) else [r])


def _variant_sigs(cfg: dict) -> List[List[str]]:
    sigs = cfg.get("signatures")
    if sigs is None:
        single = cfg.get("signature", [])
        sigs = [single] if single else []
    return sigs


def sensor_body_groups(registry: dict) -> Dict[str, dict]:
    """'센서바디 N바 K개' 들을 압력별 하나로 묶은 가상 부품 설정을 만든다."""
    groups: Dict[str, dict] = {}
    for key, cfg in registry.items():
        m = _SB_NAME_RE.search(cfg.get("name", ""))
        if not m:
            continue
        bar = m.group(1)
        g = groups.setdefault(f"SENSOR_BODY_{bar}", {
            "name": f"센서바디 {bar}바 (1·2·3개 통합)",
            "group_variants": {},
        })
        g["group_variants"][key] = cfg

    for g in groups.values():
        # 모든 버전의 부품 블록 항목을 이름 기준으로 합집합 (순서 유지)
        order: List[str] = []
        for cfg in g["group_variants"].values():
            sig = (_variant_sigs(cfg) or [[]])[0]
            for r in cfg.get("data_ranges", []):
                prev = -1
                for idx in _block_indices(r):
                    if idx >= len(sig):
                        continue
                    keys = [o.replace(" ", "") for o in order]
                    k = _item_key(sig[idx])
                    if k in keys:
                        prev = keys.index(k)
                    else:
                        order.insert(prev + 1, _item_label(sig[idx]))
                        prev += 1
        g["signature"] = order
    return groups


def parse_sensor_body_filename(filename: str) -> Optional[dict]:
    """
    "본관 센서바디 18.8Tn.29-2 (3).pdf"
      → site='본관', timing=2,
        pieces=[{machine:18,type:''}, {machine:8,type:'T'}, {machine:29,type:''}]
    """
    stem = re.sub(r'\s*\(\d+\)$', '', os.path.splitext(filename)[0])
    m = re.match(r'^(.*?)\s*센서바디\s+(\S+)-(\d+)$', stem)
    if not m:
        return None
    pieces = []
    for seg in m.group(2).split('.'):
        sm = re.fullmatch(r'(\d+)(T|S|수)?n?', seg)
        pieces.append({'machine': int(sm.group(1)), 'type': sm.group(2) or ''} if sm else None)
    return {'site': m.group(1).strip(), 'timing': int(m.group(3)), 'pieces': pieces}


# ── PDF 수집 ───────────────────────────────────────────────────────

def collect_pdfs(folders: List[str]) -> List[str]:
    """폴더들(하위 폴더 포함)에서 PDF 수집"""
    paths = []
    for folder in folders:
        if not os.path.isdir(folder):
            continue
        for root, _dirs, files in os.walk(folder):
            for fname in files:
                if fname.lower().endswith('.pdf'):
                    paths.append(os.path.join(root, fname))
    return paths


# ── 리포트 생성 ────────────────────────────────────────────────────

def generate_report(
    part_key: str,
    part_config: dict,
    selected_indices: List[int],
    item_names: List[str],
    folders: List[str],
    include_standard: bool,
    include_T: bool,
    include_S: bool,
    include_su: bool,
    include_other: bool,
    include_주간: bool,
    include_야간: bool,
    detector,
    output_path: str,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> Tuple[int, int]:
    """
    선택된 부품의 측정 항목 값을 PDF에서 추출하여 Excel로 저장합니다.
    Returns: (processed_count, skipped_count)
    """
    from core.parser import parse_measurements
    from core.models import SectionMarker
    from PyPDF2 import PdfReader

    variants = part_config.get("group_variants")
    if variants:
        # 센서바디 통합: 각 버전(3/2/1개)의 시그니처와 부품 블록
        variant_list = [
            ([[n.replace(" ", "") for n in s] for s in _variant_sigs(cfg)],
             [_block_indices(r) for r in cfg.get("data_ranges", [])])
            for cfg in variants.values()
        ]
        selected_keys = [part_config["signature"][i].replace(" ", "") for i in selected_indices]
        clean_sigs = []
    else:
        clean_sigs = [[n.replace(" ", "") for n in sig] for sig in _variant_sigs(part_config)]

    type_allowed = {"": include_standard, "T": include_T, "S": include_S,
                    "수": include_su, "other": include_other}

    all_pdfs = collect_pdfs(folders)
    total    = len(all_pdfs)

    # (공장, 호기) → list[row_dict]
    results: Dict[Tuple[str, int], List[dict]] = {}
    processed = skipped = 0

    for i, pdf_path in enumerate(all_pdfs):
        filename = os.path.basename(pdf_path)
        if progress_cb:
            progress_cb(i, total, filename)

        meta  = parse_path_metadata(pdf_path)
        shift = meta["shift"]

        # ── 주야 필터 ────────────────────────────────────────────────
        if shift == '주간' and not include_주간: skipped += 1; continue
        if shift == '야간' and not include_야간: skipped += 1; continue
        # shift=None (폴더에서 못 찾음) 은 필터링 없이 통과

        if variants:
            if "센서바디" not in filename:
                skipped += 1
                continue
        else:
            finfo = parse_filename_parts(filename)
            ftype = finfo["type"]
            # ── 종류 필터 ────────────────────────────────────────────
            if not type_allowed[ftype]:
                skipped += 1
                continue

        # ── PDF 파싱 ─────────────────────────────────────────────────
        try:
            reader    = PdfReader(pdf_path)
            full_text = "".join((p.extract_text() or "") + "\n" for p in reader.pages)
            raw       = parse_measurements(full_text, debug=False)
            filtered  = [m for m in raw if not isinstance(m, SectionMarker)]
        except Exception as e:
            print(f"[report] 파싱 실패 {filename}: {e}")
            skipped += 1
            continue

        if variants:
            n = _add_sensor_body_rows(
                results, filename, meta, filtered, variant_list,
                selected_keys, type_allowed)
            if n:
                processed += n
            else:
                skipped += 1
            continue

        # ── 부품 시그니처 대조 ────────────────────────────────────────
        if clean_sigs:
            extracted_clean = [m.name.replace(" ", "") for m in filtered]
            if not any(extracted_clean == sig for sig in clean_sigs):
                skipped += 1
                continue

        # ── 항목 값 추출 ─────────────────────────────────────────────
        values   = []
        statuses = []
        for idx in selected_indices:
            if idx < len(filtered):
                m      = filtered[idx]
                val    = round(float(m.actual_value), 6)
                status = m.classify().upper()
            else:
                val, status = None, "OK"
            values.append(val)
            statuses.append(status)

        row = {
            "year":     meta["year"],
            "month":    meta["month"],
            "day":      meta["day"],
            "shift":    shift or "-",
            "timing":   _TIMING_LABEL.get(finfo["timing"], "-"),
            "type":     _TYPE_LABEL.get(ftype, "기타"),
            "filename": filename,
            "values":   values,
            "statuses": statuses,
        }

        key = finfo["machine"] if ftype != "other" else 0
        results.setdefault(("", key), []).append(row)
        processed += 1

    if progress_cb:
        progress_cb(total, total, "Excel 작성 중…")

    _write_excel(results, item_names, output_path, sensor_body=bool(variants))
    return processed, skipped


def _add_sensor_body_rows(results, filename, meta, filtered, variant_list,
                          selected_keys, type_allowed) -> int:
    """센서바디 PDF 1개를 부품(블록)별 행으로 나눠 results 에 추가. 추가된 행 수 반환."""
    extracted = [m.name.replace(" ", "") for m in filtered]
    blocks = next((b for sigs, b in variant_list if extracted in sigs), None)
    if blocks is None:
        return 0

    finfo  = parse_sensor_body_filename(filename)
    pieces = finfo["pieces"] if finfo else []
    site   = finfo["site"] if finfo else ""
    timing = finfo["timing"] if finfo else 0

    added = 0
    for bi, idxs in enumerate(blocks):
        piece = pieces[bi] if bi < len(pieces) and len(pieces) == len(blocks) else None
        ftype = piece["type"] if piece else "other"
        if not type_allowed[ftype]:
            continue

        by_key = {_item_key(filtered[i].name): filtered[i] for i in idxs if i < len(filtered)}
        values, statuses = [], []
        for k in selected_keys:
            m = by_key.get(k)
            if m is None:
                values.append(None); statuses.append("OK")
            else:
                values.append(round(float(m.actual_value), 6)); statuses.append(m.classify().upper())

        row = {
            "year":     meta["year"],
            "month":    meta["month"],
            "day":      meta["day"],
            "shift":    meta["shift"] or "-",
            "timing":   _TIMING_LABEL.get(timing, "-"),
            "type":     _TYPE_LABEL.get(ftype, "기타"),
            "site":     site or "-",
            "position": f"{len(blocks)}개 중 {bi + 1}번째",
            "filename": filename,
            "values":   values,
            "statuses": statuses,
        }
        machine = piece["machine"] if piece else 0
        results.setdefault((site if piece else "", machine), []).append(row)
        added += 1
    return added


# ── Excel 작성 ─────────────────────────────────────────────────────

_HDR_FILL = PatternFill("solid", fgColor="2980B9")
_HDR_FONT = Font(color="FFFFFF", bold=True)
_NG_FILL  = PatternFill("solid", fgColor="FFCCCC")
_UN_FILL  = PatternFill("solid", fgColor="FFF3CD")
_UP_FILL  = PatternFill("solid", fgColor="FFE0CC")
_CTR      = Alignment(horizontal="center", vertical="center")


def _write_excel(results: Dict[Tuple[str, int], List[dict]], item_names: List[str],
                 path: str, sensor_body: bool = False):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    fixed = [("연도", "year", 8), ("월", "month", 5), ("일", "day", 5),
             ("주야", "shift", 8), ("차수", "timing", 8), ("구분", "type", 10)]
    if sensor_body:
        fixed += [("공장", "site", 8), ("PDF 내 위치", "position", 14)]
    fixed += [("파일명", "filename", 40)]
    headers    = [h for h, _, _ in fixed] + item_names
    col_widths = [w for _, _, w in fixed] + [max(14, len(n) + 2) for n in item_names]
    n_fixed    = len(fixed)

    # 시트 순서: 공장 → 호기 번호 오름차순, 기타(0) 맨 뒤
    sorted_keys = sorted((k for k in results if k[1] != 0), key=lambda k: (k[0], k[1]))
    sorted_keys += sorted(k for k in results if k[1] == 0)

    if not sorted_keys:
        ws = wb.create_sheet("결과없음")
        ws.cell(1, 1, "일치하는 PDF가 없거나 모두 필터링되었습니다.")
        wb.save(path)
        return

    for site, machine_no in sorted_keys:
        sheet_name = f"{machine_no}호기" if machine_no != 0 else "기타"
        if site:
            sheet_name = f"{site} {sheet_name}"
        ws = wb.create_sheet(sheet_name[:31])

        # 헤더 행
        for c, h in enumerate(headers, 1):
            cell = ws.cell(1, c, h)
            cell.fill = _HDR_FILL
            cell.font = _HDR_FONT
            cell.alignment = _CTR

        ws.freeze_panes = "A2"
        ws.row_dimensions[1].height = 20

        # 날짜 순 정렬 (연→월→일 순)
        rows = sorted(
            results[(site, machine_no)],
            key=lambda r: (r["year"] or 0, r["month"] or 0, r["day"] or 0)
        )

        # 데이터 행
        for r, row in enumerate(rows, 2):
            for c, (_, field, _) in enumerate(fixed, 1):
                cell = ws.cell(r, c, row[field])
                if field != "filename":
                    cell.alignment = _CTR
            for c, (val, status) in enumerate(zip(row["values"], row["statuses"]), n_fixed + 1):
                cell = ws.cell(r, c, val)
                cell.alignment = _CTR
                if   status == "NG": cell.fill = _NG_FILL
                elif status == "UN": cell.fill = _UN_FILL
                elif status == "UP": cell.fill = _UP_FILL

        # 컬럼 너비
        for c, w in enumerate(col_widths, 1):
            ws.column_dimensions[get_column_letter(c)].width = w

    wb.save(path)
