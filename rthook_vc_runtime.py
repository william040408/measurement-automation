import sys
import os
import ctypes

# DLL 로드 실패 시 Windows 기본 오류 팝업 억제
ctypes.windll.kernel32.SetErrorMode(0x8001)

_diag = []

def _d(msg):
    _diag.append(msg)

if hasattr(sys, '_MEIPASS'):
    _meipass = sys._MEIPASS
    _d(f"_MEIPASS: {_meipass}")

    # 1. VC++ 런타임 먼저 로드 (msvcp140: PyQt5 번들 v14.26 — Windows 8 호환)
    for _dll in ['vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll']:
        _path = os.path.join(_meipass, _dll)
        _exists = os.path.exists(_path)
        _d(f"  {_dll}: {'있음' if _exists else '없음'}")
        if _exists:
            try:
                ctypes.CDLL(_path)
                _d(f"    → 로드 성공")
            except OSError as e:
                _d(f"    → 로드 실패: {e}")

    # 2. onnxruntime/capi 의 DLL 먼저 로드
    _ort_capi = os.path.join(_meipass, 'onnxruntime', 'capi')
    _d(f"onnxruntime/capi 존재: {os.path.isdir(_ort_capi)}")
    if os.path.isdir(_ort_capi):
        _d(f"  내용: {os.listdir(_ort_capi)}")
        for _dll_name in ['onnxruntime_providers_shared.dll']:
            _path = os.path.join(_ort_capi, _dll_name)
            _exists = os.path.exists(_path)
            _d(f"  {_dll_name}: {'있음' if _exists else '없음'}")
            if _exists:
                try:
                    ctypes.CDLL(_path)
                    _d(f"    → 로드 성공")
                except OSError as e:
                    _d(f"    → 로드 실패: {e}")

    # 3. Python 3.8+ DLL 검색 경로에 추가
    if hasattr(os, 'add_dll_directory'):
        try:
            os.add_dll_directory(_meipass)
            _d(f"add_dll_directory(_meipass): 성공")
        except Exception as e:
            _d(f"add_dll_directory(_meipass): 실패 {e}")
        if os.path.isdir(_ort_capi):
            try:
                os.add_dll_directory(_ort_capi)
                _d(f"add_dll_directory(ort_capi): 성공")
            except Exception as e:
                _d(f"add_dll_directory(ort_capi): 실패 {e}")
    else:
        _d("add_dll_directory 없음 (Python < 3.8?)")

    # 4. 진단 로그 저장 (config/{PC이름}/ 에 쓰기)
    try:
        import socket as _sock
        _machine = _sock.gethostname()
        _bd = os.path.dirname(sys.executable)
        _log_dir = os.path.join(_bd, 'config', _machine)
        os.makedirs(_log_dir, exist_ok=True)
        _log_path = os.path.join(_log_dir, 'rthook_diag.txt')
        with open(_log_path, 'w', encoding='utf-8') as _f:
            _f.write('\n'.join(_diag))
    except Exception:
        pass
else:
    pass  # 개발 환경 (frozen 아닌 경우)
