import os
import shutil
from typing import List, Dict
from modules.messenger import parse_custom_indices

import time


class FileExistsConflict(Exception):
    """동일한 파일명이 이미 존재할 때 발생 — 호출자가 사용자 확인 후 재시도"""
    def __init__(self, intended_path: str, unique_path: str):
        self.intended_path = intended_path
        self.unique_path = unique_path
        super().__init__(f"파일 중복: {os.path.basename(intended_path)}")


class FileManager:
    def __init__(self):
        self.base_path = ""

    def set_base_path(self, path: str):
        # 경로가 절대 경로인지 확인하고 설정
        self.base_path = os.path.abspath(path)

    def _get_unique_path(self, target_path: str) -> str:
        """파일이 이미 존재하면 이름 뒤에 (1), (2) 등을 붙여 고유한 경로를 반환합니다."""
        if not os.path.exists(target_path):
            return target_path

        base, ext = os.path.splitext(target_path)
        counter = 1
        while True:
            new_path = f"{base} ({counter}){ext}"
            if not os.path.exists(new_path):
                return new_path
            counter += 1

    def _get_type_sequential_path(self, intended_path: str, type_suffix: str) -> str:
        """T/S/수 품종의 순차 넘버링: T → T2 → T3 ... (Tn/S2n 형식 포함)"""
        if not os.path.exists(intended_path):
            return intended_path

        dir_name = os.path.dirname(intended_path)
        stem, ext = os.path.splitext(os.path.basename(intended_path))

        idx = stem.rfind(type_suffix)
        if idx == -1:
            return self._get_unique_path(intended_path)

        prefix    = stem[:idx + len(type_suffix)]   # e.g. "본관 22-1T"
        remainder = stem[idx + len(type_suffix):]   # e.g. "" or "n"

        counter = 2
        while True:
            new_path = os.path.join(dir_name, f"{prefix}{counter}{remainder}{ext}")
            if not os.path.exists(new_path):
                return new_path
            counter += 1

    def force_move(self, pdf_path: str, target_path: str, mode: str = 'move') -> str:
        """이미 경로가 확정된 파일을 강제로 이동/복사"""
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        if mode == 'copy':
            shutil.copy2(pdf_path, target_path)
        else:
            shutil.move(pdf_path, target_path)
        return target_path

    def _generate_new_name(self, part_config: Dict, measurements: List,
                           site: str, machines: List[int], timing: int,
                           tool_changes: List[str]) -> str:

        # SectionMarker 제외 — JSON 인덱스는 순수 측정값 기준으로 작성됨
        from core.models import SectionMarker
        measurements = [m for m in measurements if not isinstance(m, SectionMarker)]

        part_name = part_config.get("name", "알수없는부품")
        ranges = part_config.get("data_ranges", [])

        # 1. 센서바디 규칙 (멀티 부품 대응)
        if "센서바디" in part_name:
            machine_parts = []

            for i, r in enumerate(ranges):
                target_pattern = r if isinstance(r, list) else [r]
                target_indices = parse_custom_indices(target_pattern)

                has_ng = False
                for abs_idx in target_indices:
                    if abs_idx >= len(measurements):
                        continue
                    m = measurements[abs_idx]
                    try:
                        if callable(m.is_ng):
                            if m.is_ng(): has_ng = True; break
                        elif getattr(m, 'is_ng', False):
                            has_ng = True; break
                    except: continue

                n_suffix  = "n" if has_ng else ""
                type_suf  = tool_changes[i] if i < len(tool_changes) else ""
                current_m_no = machines[i] if i < len(machines) else (machines[0] if machines else "?")
                machine_parts.append(f"{current_m_no}{type_suf}{n_suffix}")

            machine_str = ".".join(machine_parts)
            return f"{site} 센서바디 {machine_str}-{timing}.pdf"

        # 2. 기타 부품들 (다이아 프램, 센서하우징 등)
        else:
            m_no     = machines[0] if machines else "?"
            type_suf = tool_changes[0] if tool_changes else ""

            target_indices = []
            for r in ranges:
                target_pattern = r if isinstance(r, list) else [r]
                target_indices.extend(parse_custom_indices(target_pattern))

            has_ng = False
            for abs_idx in set(target_indices):
                if abs_idx >= len(measurements):
                    continue
                m = measurements[abs_idx]
                try:
                    if callable(m.is_ng):
                        if m.is_ng(): has_ng = True; break
                    elif getattr(m, 'is_ng', False):
                        has_ng = True; break
                except: continue

            n_suffix = "n" if has_ng else ""

            if "다이아 프램" in part_name:
                face = part_config.get("face", "정면")
                return f"다이아 프램 {m_no}-{timing}{type_suf} {face}{n_suffix}.pdf"

            combined = f"{type_suf}{n_suffix}"
            if "센서하우징" in part_name:
                size = "17.92" if "17.92" in part_name else "19.25"
                return f"센서하우징 {m_no}-{timing}{combined} {size}.pdf"

            # part_type 필드 우선, 없으면 이름으로 추론 (하위호환)
            _pt = part_config.get("part_type", "")
            if not _pt:
                if "ACV" in part_name:   _pt = "acv_legacy"
                elif "APC" in part_name: _pt = "apc_legacy"

            if _pt in ("acv", "acv_legacy"):
                time_lst   = ['초품', '중품', '종품']
                prefix     = part_config.get("file_prefix", "")
                timing_str = time_lst[timing - 1] if 1 <= timing <= 3 else "?"
                t_suf      = f" {type_suf}" if type_suf else ""
                base = f"{prefix} {timing_str}{t_suf}.pdf".lstrip() if prefix else f"{timing_str}{t_suf}.pdf"
                return base

            if _pt in ("apc", "apc_legacy"):
                time_lst   = ['초품', '중품', '종품']
                timing_str = time_lst[timing - 1] if 1 <= timing <= 3 else "?"
                prefix     = part_config.get("file_prefix", "APC" if _pt == "apc_legacy" else "")
                t_suf      = f" {type_suf}" if type_suf else ""
                base = f"{prefix} {timing_str}{t_suf}.pdf".lstrip() if prefix else f"{timing_str}{t_suf}.pdf"
                return base

            if not _pt:
                return f"{m_no}-{timing}{combined}.pdf"

    def move_and_save(self, pdf_path: str, part_config: Dict, measurements: List,
                      site: str, machines: List[int], timing: int,
                      tool_changes: List[str], mode: str = 'copy'):

        # 1. 대상 폴더(네트워크 드라이브) 존재 여부 광속 체크
        if not os.path.exists(self.base_path):
            raise OSError(f"네트워크 드라이브({self.base_path}) 연결이 끊겼습니다.")

        # 2. 파일명 생성 및 폴더 생성
        new_filename = self._generate_new_name(part_config, measurements, site, machines, timing, tool_changes)
        sub_folder   = part_config.get("sub_folder", "기타")
        target_dir   = os.path.join(self.base_path, sub_folder)
        os.makedirs(target_dir, exist_ok=True)

        intended_path = os.path.join(target_dir, new_filename)
        part_name     = part_config.get("name", "")
        type_suf      = tool_changes[0] if tool_changes else ""

        # 3. 충돌 처리 — 센서바디는 unique, 나머지는 품종 여부로 분기
        if "센서바디" in part_name:
            # 센서바디: 충돌 시 경고 발생 (standard 동일)
            if os.path.exists(intended_path):
                raise FileExistsConflict(intended_path, self._get_unique_path(intended_path))
            final_target_path = intended_path
        elif type_suf:
            # T/S/수 품종: 자동 순차 넘버링 (T → T2 → T3 ...)
            final_target_path = self._get_type_sequential_path(intended_path, type_suf)
        else:
            # 일반: 중복이면 경고 발생
            if os.path.exists(intended_path):
                raise FileExistsConflict(intended_path, self._get_unique_path(intended_path))
            final_target_path = intended_path

        # 4. 파일 이동 실행
        try:
            if mode == 'copy':
                shutil.copy2(pdf_path, final_target_path)
            else:
                shutil.move(pdf_path, final_target_path)
            return final_target_path
        except PermissionError:
            raise PermissionError(f"파일({os.path.basename(pdf_path)})이 열려있어 접근할 수 없습니다.")
        except Exception as e:
            raise OSError(f"파일 조작 중 오류 발생: {e}")