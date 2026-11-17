import os
import json
from typing import List, Dict


def load_special_checks(config_path: str) -> Dict:
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[special_checker] 설정 로드 실패: {e}")
        return {}


def run_checks(part_key: str, measurements: list, checks_data: Dict) -> List[Dict]:
    """
    특이사항 체크 실행.
    반환: [{"part_idx": int, "message": str}, ...] — 트리거된 항목만 포함
    """
    from core.models import SectionMarker
    filtered = [m for m in measurements if not isinstance(m, SectionMarker)]

    checks = checks_data.get(part_key, [])
    results = []

    for check in checks:
        check_type = check.get("type", "")
        part_idx   = check.get("part_idx", 0)
        alert_msg  = check.get("alert_message", "⚠️ 특이사항 발생")

        if check_type == "deviation":
            idx_a     = check.get("index_a", -1)
            idx_b     = check.get("index_b", -1)
            threshold = float(check.get("threshold", 0.0))
            label_a   = check.get("label_a", f"항목{idx_a}")
            label_b   = check.get("label_b", f"항목{idx_b}")

            if idx_a < 0 or idx_b < 0:
                continue
            if idx_a >= len(filtered) or idx_b >= len(filtered):
                print(f"[special_checker] 인덱스 초과: {idx_a}, {idx_b} (총 {len(filtered)}개)")
                continue

            try:
                val_a = float(getattr(filtered[idx_a], 'actual_value', 0))
                val_b = float(getattr(filtered[idx_b], 'actual_value', 0))
                diff  = abs(val_a - val_b)
                if diff >= threshold:
                    detail = f"({label_a}: {val_a:.4f}, {label_b}: {val_b:.4f}, 편차: {diff*1000:.1f}μm)"
                    results.append({
                        "part_idx": part_idx,
                        "message":  f"{alert_msg}\n{detail}",
                    })
            except (ValueError, TypeError) as e:
                print(f"[special_checker] 값 변환 실패: {e}")

    return results
