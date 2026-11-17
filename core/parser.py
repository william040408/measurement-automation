import re
from core.models import NominalMeasurement, ToleranceMeasurement, SectionMarker

NOMINAL_CATS = ["위치", "직경", "거리"]
TOLERANCE_CATS = ["동심도", "원주 흔들림", "축 흔들림", "진원도", "직각도", "평행도", "위치도", "평면도"]
REQUIRED_KEYS = ["NV", "UT", "LT", "TO", "DV", "AV", "YN", "ZN", "ZA", "XN", "XA", "YA", "ER", "RL"]

# 긴 카테고리를 먼저 검사 (위치도 > 위치, 원주 흔들림 > 위치 등)
_ALL_CATS = NOMINAL_CATS + TOLERANCE_CATS
_SORTED_CATS = sorted(_ALL_CATS, key=len, reverse=True)


def _detect_cat(line: str):
    """줄이 카테고리 키워드로 시작하면 해당 카테고리 반환, 아니면 None."""
    stripped = re.sub(r'\s+', ' ', line.strip())  # 다중 공백 정규화
    for cat in _SORTED_CATS:
        if stripped == cat or stripped.startswith(cat + ' ') or stripped.startswith(cat + '\t'):
            return cat
    return None


def _is_section_separator(line: str) -> bool:
    """
    '--- 섹션이름 ---' 형태의 구분선인지 판별.
    소수점 포함 내용은 데이터 줄로 간주하여 제외.
    """
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.count('-') < 3:
        return False
    # 대시·공백·별표를 제거한 순수 내용
    content = re.sub(r'[\-\s\*]', '', stripped)
    if not content:
        return True   # '- - -' 같은 순수 구분선
    if '.' in content:
        return False  # 소수점 있으면 데이터 줄
    if len(content) > 25:
        return False  # 섹션 이름치고 너무 길면 데이터 줄
    return True


def _extract_section_name(line: str) -> str:
    """구분선에서 한글 섹션 이름 추출."""
    match = re.search(r'[가-힣][가-힣\w]*(?:\s+[가-힣\w]+)*', line)
    return match.group().strip() if match else ""



def parse_measurements(text: str, excluded_keywords=None, debug=False):
    """
    PDF 텍스트를 파싱하여 측정 항목 리스트를 반환.
    리스트에는 NominalMeasurement, ToleranceMeasurement, SectionMarker가 섞여 있을 수 있음.
    SectionMarker는 수치 연산·signature 비교에는 사용하지 말 것.
    """
    results = []
    lines = text.split('\n')

    # ── STEP 1: 헤더/푸터 제거 (내용 기반 X, 구조 기반 O) ──────────────────
    #
    # 헤더: 첫 번째 카테고리 또는 섹션 구분선이 나오기 전 줄 (항상 프로그램명+Admin 2줄)
    # 푸터: 'GEOPAK ...' 줄 → 이후 다음 페이지 헤더 2줄도 건너뜀
    #
    skip_next = 0
    found_first = False
    content_lines = []

    for line in lines:
        if skip_next > 0:
            if debug:
                print(f"[SKIP PAGE_HEADER] {line!r}")
            skip_next -= 1
            continue

        # GEOPAK 푸터 감지 → 다음 페이지 헤더 2줄 건너뜀
        if re.match(r'GEOPAK', line.strip(), re.IGNORECASE):
            if debug:
                print(f"[FOOTER] {line!r}")
            skip_next = 2
            continue

        # 첫 번째 구조 요소(카테고리 or 섹션 구분선)를 만나기 전 = 헤더
        if not found_first:
            if _is_section_separator(line) or _detect_cat(line):
                found_first = True
                content_lines.append(line)
            elif debug:
                print(f"[SKIP HEADER] {line!r}")
            continue

        content_lines.append(line)

    if debug:
        print(f"\n[STEP 1] {len(content_lines)}줄 남음 (헤더/푸터 제거 후)")

    # ── STEP 2: 줄 단위로 측정 블록 분리 ───────────────────────────────────
    blocks = []
    current_section = ""
    current_block = None

    for line in content_lines:
        if not line.strip():
            continue

        # 섹션 구분선 → SectionMarker로 결과에 추가 (같은 이름 연속 중복 방지)
        if _is_section_separator(line):
            name = _extract_section_name(line)
            if name and name != current_section:
                current_section = name
                results.append(SectionMarker(name=name))
            if debug:
                print(f"[SECTION] {current_section!r}")
            continue

        # 카테고리 줄 → 새 블록 시작
        cat = _detect_cat(line)
        if cat is not None:
            if current_block is not None:
                blocks.append(current_block)
            current_block = {
                "cat": cat,
                # 카테고리 포함 전체 줄을 첫 content로 저장 (signature 호환)
                "content_lines": [line.rstrip()],
                "section": current_section,
            }
            if debug:
                print(f"[CAT] {cat!r}")
            continue

        # 데이터 줄
        if current_block is not None:
            current_block["content_lines"].append(line.rstrip())

    if current_block is not None:
        blocks.append(current_block)

    # ── STEP 2.5: 데이터 없는 이름 조각 + 같은 카테고리 블록 머지 ────────────
    # GEOPAK v4.2 레이아웃에서 "거리  XY (1) 4.56" 과 "거리 NV= ..."가
    # 별도 블록으로 쪼개지는 경우를 합쳐서 이름이 잘리지 않도록 함
    _DATA_KW = re.compile(r'(?:NV|UT|LT|TO|DV|AV)=')
    merged = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        raw_joined = ' '.join(b['content_lines'])
        has_data = bool(_DATA_KW.search(raw_joined))
        if (not has_data
                and i + 1 < len(blocks)
                and blocks[i + 1]['cat'] == b['cat']):
            # 이름 조각을 다음 블록 앞에 붙임
            nxt = dict(blocks[i + 1])
            nxt['content_lines'] = b['content_lines'] + nxt['content_lines']
            merged.append(nxt)
            if debug:
                print(f"[MERGE] 이름조각 블록({b['cat']!r}) + 다음블록 병합")
            i += 2
        else:
            merged.append(b)
            i += 1
    blocks = merged

    if debug:
        print(f"\n[STEP 2] {len(blocks)}개 블록 발견")

    # ── STEP 3: 각 블록을 Measurement 객체로 변환 ───────────────────────────
    for idx, block in enumerate(blocks):
        cat = block["cat"]
        section = block["section"]

        raw = " ".join(block["content_lines"])

        # '- 0.050' → '-0.050' (PDF에서 음수를 띄어 쓰는 경우 처리)
        raw = re.sub(r'-\s+(\d)', r'-\1', raw)

        # 키워드와 숫자 사이 공백 강제 삽입 (예: '4.603DV=' → '4.603 DV=')
        for key in REQUIRED_KEYS:
            raw = re.sub(rf'([\d\.\-])({key}=)', r'\1 \2', raw)
            raw = re.sub(rf'({key}=)([\d\.\-])', r'\1 \2', raw)

        raw = raw.replace('|', ' ')

        # 게이지바 (-----**----) 제거 — 수치 파싱에 불필요
        raw = re.sub(r'[\-\* ]{3,}$', lambda m: m.group() if re.search(r'[^-\* ]', m.group()) else '', raw.rstrip())

        # ER= 게이지바 지시선 제거 — 시각 전용이며 DV에 이미 포함됨
        # 'ER=<<---+----- -0.008' 처럼 ER= 뒤에 비수치 문자가 오면 키워드로 인식 안 돼
        # 역방향 파싱 시 여분 숫자로 남아 NV/UT/LT/AV 전체가 밀리는 버그 원인
        raw = re.sub(r'\s*ER=.*', '', raw)

        if debug:
            print(f"\n[Block {idx}] cat={cat!r} section={section!r}")
            print(f"  raw  = {raw!r}")

        # 첫 번째 데이터 키워드 위치로 이름/데이터 분리
        data_start = re.search(r'(?:NV|UT|LT|TO|DV|AV|XN|YN|ZN|XA|YA|ZA|RL)=', raw)
        name_part = raw[:data_start.start()].strip() if data_start else raw
        data_part = raw[data_start.start():].strip() if data_start else ""

        # 이름 정제
        name_part = re.sub(r'(\D)\s*-\s*(\d)', r'\1-\2', name_part)
        final_name = re.sub(r'\s+', ' ', name_part).strip()
        final_name = re.sub(r'^[\*\-\.\s]+|[\*\-\.\s]+$', '', final_name)

        if not final_name:
            if debug:
                print(f"  → 건너뜀 (이름 없음)")
            continue

        # 키-값 역방향 파싱
        words = data_part.split()
        mapping, temp_nums = {}, []

        for i in range(len(words) - 1, -1, -1):
            word = words[i]
            if not word:
                continue
            pure_kw = word.rstrip('=')
            if pure_kw in REQUIRED_KEYS:
                if temp_nums:
                    try:
                        mapping[pure_kw] = float(temp_nums.pop(0))
                    except ValueError:
                        pass
                continue
            num_match = re.search(r'-?\d+\.\d+', word)
            if num_match:
                temp_nums.append(num_match.group())

        if debug:
            print(f"  name={final_name!r} mapping={mapping}")

        # Measurement 객체 생성
        if cat in NOMINAL_CATS:
            if "NV" not in mapping and "DV" not in mapping:
                if debug:
                    print(f"  → 건너뜀 (NV/DV 없음)")
                continue
            results.append(NominalMeasurement(
                name=final_name, cat=cat,
                nv=mapping.get("NV", 0.0),
                ut=mapping.get("UT", 0.0),
                lt=mapping.get("LT", 0.0),
                dv=mapping.get("DV", 0.0),
            ))
        else:
            if "TO" not in mapping and "DV" not in mapping and "RL" not in mapping:
                if debug:
                    print(f"  → 건너뜀 (TO/DV/RL 없음)")
                continue
            dv_val = mapping.get("DV", mapping.get("ZA", mapping.get("YA", mapping.get("AV", 0.0))))
            # 직각도처럼 RL=이 공차 기준값인 경우 TO 대신 사용
            to_val = mapping.get("TO", mapping.get("RL", 0.0))
            results.append(ToleranceMeasurement(
                name=final_name, cat=cat,
                to=to_val, dv=dv_val,
            ))

    return results
