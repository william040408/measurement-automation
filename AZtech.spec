# -*- mode: python ; coding: utf-8 -*-
#
# AZtech 빌드 스펙  (버전은 config/version.py 의 APP_VERSION 에서 자동 읽음)
#
# ── 빌드 방법 ────────────────────────────────────────────────────────
#   .\venv38\Scripts\pyinstaller.exe AZtech.spec --noconfirm
#
# 버전 변경 시: config/version.py 의 APP_VERSION 만 수정 후 위 명령 실행
# ─────────────────────────────────────────────────────────────────────

import os
import sys
import importlib.util

# config/version.py 에서 APP_VERSION 읽기
_vspec = importlib.util.spec_from_file_location("version", "config/version.py")
_vmod  = importlib.util.module_from_spec(_vspec)
_vspec.loader.exec_module(_vmod)
APP_VERSION = _vmod.APP_VERSION
print(f"[spec] 빌드 버전: {APP_VERSION}")

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

# msvcp140.dll: PyQt5 번들 버전 사용 (v14.26 — Windows 8 호환)
# System32 버전(v14.50+)은 구형 Windows에서 의존성 오류로 로드 실패함
try:
    import PyQt5 as _pyqt5_mod
    _qt5_bin = os.path.join(os.path.dirname(_pyqt5_mod.__file__), 'Qt5', 'bin')
    _msvcp140_src = os.path.join(_qt5_bin, 'msvcp140.dll')
    if os.path.exists(_msvcp140_src):
        _msvcp_binaries = [(_msvcp140_src, '.')]
        print(f"[spec] msvcp140.dll: PyQt5 번들 사용 (v14.26, Windows 8 호환)")
    else:
        _msvcp_binaries = []
        print("[spec] msvcp140.dll: PyQt5 번들 없음 — 번들 생략")
except Exception as _e:
    _msvcp_binaries = []
    print(f"[spec] msvcp140.dll 탐색 실패: {_e}")

# onnxruntime 원본은 System32\vcruntime140_1.dll 이 없으면 import 를 거부함.
# exe 안에 번들했으므로 frozen 환경에서는 체크를 건너뛰도록 빌드 환경의 파일을 패치.
# (CI 는 매번 깨끗한 pip install 이라 여기서 패치하지 않으면 원본이 번들됨)
try:
    import importlib.util as _ilu
    _ort_spec = _ilu.find_spec('onnxruntime')
    if _ort_spec is not None:
        _pbs = os.path.join(os.path.dirname(_ort_spec.origin), 'capi', '_pybind_state.py')
        with open(_pbs, 'r', encoding='utf-8') as _f:
            _src = _f.read()
        if '_MEIPASS' not in _src:
            _needle = 'if not os.path.isfile('
            if _needle not in _src:
                raise SystemExit('[spec] onnxruntime _pybind_state.py 구조가 예상과 다름 — 패치 실패')
            _src = _src.replace(_needle, 'if not hasattr(__import__("sys"), "_MEIPASS") and not os.path.isfile(', 1)
            with open(_pbs, 'w', encoding='utf-8') as _f:
                _f.write(_src)
            print(f'[spec] onnxruntime VC++ 체크 패치 적용: {_pbs}')
        else:
            print('[spec] onnxruntime VC++ 체크 이미 패치됨')
except SystemExit:
    raise
except Exception as _e:
    raise SystemExit(f'[spec] onnxruntime 패치 중 오류: {_e}')

# RapidOCR 모델 번들
rapidocr_datas = []
try:
    import rapidocr_onnxruntime
    roc_dir = os.path.dirname(rapidocr_onnxruntime.__file__)
    rapidocr_datas = [(roc_dir, 'rapidocr_onnxruntime')]
    print(f"[spec] RapidOCR 번들 포함: {roc_dir}")
except ImportError:
    print("[spec] RapidOCR 없음 — OCR 기능은 런타임에서 조용히 비활성화됩니다.")

# onnxruntime DLL / 데이터 전체 수집 (누락 시 OCR 런타임 오류)
try:
    ort_datas, ort_bins, ort_hidden = collect_all('onnxruntime')
    print(f"[spec] onnxruntime 수집: {len(ort_bins)}개 바이너리")
except Exception as _e:
    ort_datas, ort_bins, ort_hidden = [], [], []
    print(f"[spec] onnxruntime 수집 실패: {_e}")

# opencv-python 수집
try:
    cv2_datas, cv2_bins, cv2_hidden = collect_all('cv2')
    print(f"[spec] cv2 수집: {len(cv2_bins)}개 바이너리")
except Exception as _e:
    cv2_datas, cv2_bins, cv2_hidden = [], [], []
    print(f"[spec] cv2 수집 실패: {_e}")

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[
        # vcruntime140 계열: System32 사용 (로드 성공 확인)
        (r'C:\Windows\System32\vcruntime140.dll',   '.'),
        (r'C:\Windows\System32\vcruntime140_1.dll', '.'),
        # msvcp140.dll: PyQt5 번들 v14.26 사용 (System32 v14.50은 구형 Windows에서 실패)
    ] + _msvcp_binaries + ort_bins + cv2_bins,
    datas=[
        ('assets', 'assets'),
        ('config', 'config'),
    ] + rapidocr_datas + ort_datas + cv2_datas,
    hiddenimports=[
        'rapidocr_onnxruntime',
        'onnxruntime',
        'PIL',
        'numpy',
    ] + ort_hidden + cv2_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['rthook_vc_runtime.py'],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AZtech',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\data\\aztech_icon_opaque.ico'],
)
