from typing import List, Dict, Tuple

def parse_custom_indices(range_list: List) -> List[int]:
    """
    ["1-10", "15", "20-25"] 형태의 패턴을 [1,2,3...10, 15, 20...25] 리스트로 변환
    """
    indices = []
    for item in range_list:
        item_str = str(item).strip()
        if "-" in item_str:
            try:
                start, end = map(int, item_str.split("-"))
                # 시작이 끝보다 클 경우를 대비해 처리
                indices.extend(range(min(start, end), max(start, end) + 1))
            except ValueError:
                continue # 숫자가 아닌 형식이 섞여있을 경우 무시
        else:
            try:
                indices.append(int(item_str))
            except ValueError:
                continue
    # 중복 제거 및 정렬 (선택 사항)
    return sorted(list(set(indices)))

_TYPE_LABELS = {"T": "공구교환품", "S": "세팅품", "수": "수정품"}

def get_part_report(site: str, machine_no: int, timing: int, measurements: List, part_config: Dict, part_idx: int, type_suffix: str = "", is_sample: bool = False) -> Tuple[str, List[str]]:
    """
    보고 멘트와 상세 로그 리스트를 패턴 기반 인덱스로 추출하여 반환합니다.
    """
    ranges_config = part_config.get("data_ranges", [])
    if part_idx >= len(ranges_config):
        return "데이터 범위 없음", []

    # --- [핵심 변경 포인트] ---
    # 현재 부품에 해당하는 패턴(예: ["1-5", "10"])을 가져와서 실제 인덱스들로 변환
    target_pattern = ranges_config[part_idx]
    
    # 만약 패턴이 리스트 형태가 아니라 단일 문자열("1-10")일 경우를 위해 리스트화
    if not isinstance(target_pattern, list):
        target_pattern = [target_pattern]
        
    indices = parse_custom_indices(target_pattern)
    # -----------------------

    # SectionMarker 제외 — JSON 인덱스는 순수 측정값 기준으로 작성됨
    from core.models import SectionMarker
    measurements = [m for m in measurements if not isinstance(m, SectionMarker)]

    part_name = part_config.get("name", "")
    
    # part_type 필드 우선, 없으면 이름으로 추론 (기존 부품 하위호환)
    _pt = part_config.get("part_type", "")
    if not _pt:
        if "ACV" in part_name:   _pt = "acv_legacy"
        elif "APC" in part_name: _pt = "apc_legacy"

    if is_sample:
        header = f"{part_name} 측정 의뢰 결과입니다"
    elif _pt in ("acv", "apc", "acv_legacy", "apc_legacy"):
        time_lst = ['초품', '중품', '종품']
        timing_str = time_lst[timing - 1] if 1 <= timing <= 3 else "알수없는품"
        if _pt == "acv":
            # 새 ACV형: 부품명을 그대로 접두어로 사용
            header = f"{part_name} {machine_no}호기 {timing_str} 데이터입니다"
        elif _pt == "apc":
            # 새 APC형: 부품명을 그대로 접두어로 사용
            header = f"{part_name} {timing_str} 데이터입니다"
        elif _pt == "acv_legacy":
            header = f"ACV {machine_no}호기 {timing_str} 데이터입니다"
        else:  # apc_legacy
            header = f"APC {timing_str} 데이터입니다"
    else:
        # 기존 일반 부품 멘트 (예: 1-2 공구교환품)
        site_code   = "1" if "본관" in site else "2"
        type_label  = _TYPE_LABELS.get(type_suffix, "")
        header = f"{site_code}-{machine_no}" + (f" {type_label}" if type_label else "")

    ng_avs, un_avs, up_avs = [], [], []
    debug_logs = [] 

    for absolute_idx in indices:
        # PDF 파싱 결과보다 큰 인덱스를 참조하지 않도록 방어
        if absolute_idx >= len(measurements):
            continue
            
        m = measurements[absolute_idx]
        # classify() 함수 존재 여부 확인 (안전장치)
        if not hasattr(m, 'classify'):
            continue
            
        status = m.classify().upper()
        # 실제 값 가져오기 (actual_value 또는 dv)
        val = getattr(m, 'actual_value', getattr(m, 'dv', 0))
        val_str = f"{float(val):.3f}"
        
        item_name = getattr(m, 'label', getattr(m, 'name', f'Item {absolute_idx}'))

        if status == "NG": 
            ng_avs.append(val_str)
            debug_logs.append(f"🔴 [No.{absolute_idx:02d}] {item_name}: {val_str} (NG)")
        elif status == "UN": 
            un_avs.append(val_str)
            debug_logs.append(f"🟡 [No.{absolute_idx:02d}] {item_name}: {val_str} (UN)")
        elif status == "UP": 
            up_avs.append(val_str)
            debug_logs.append(f"🟠 [No.{absolute_idx:02d}] {item_name}: {val_str} (UP)")


    if not is_sample and _pt in ("acv", "apc", "acv_legacy", "apc_legacy"):
        return header, debug_logs

    # 멘트 조립
    parts = [header]
    if ng_avs: parts.append(f"ng {' '.join(ng_avs)}")
    if un_avs: parts.append(f"un {' '.join(un_avs)}")
    if up_avs: parts.append(f"up {' '.join(up_avs)}")
    
    if not (ng_avs or un_avs or up_avs):
            parts.append("ALL OK")

    return " ".join(parts), debug_logs