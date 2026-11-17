import json
import os
import sys
import socket

# =========================================================
# 1. 경로 기준점 설정 (PyInstaller 배포 대응)
# =========================================================

if getattr(sys, 'frozen', False):
    # .exe 실행 시: exe 위치 = 쓰기 가능한 사용자 데이터 기준
    BASE_DIR = os.path.dirname(sys.executable)
    # 번들 리소스는 _MEIPASS 안에만 존재 (읽기 전용)
    _RESOURCE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _RESOURCE_DIR = BASE_DIR

# =========================================================
# 2. 고정 디렉토리 경로
# =========================================================

# 이 PC의 컴퓨터 이름 (서버 공유 시 PC별 설정 분리에 사용)
MACHINE_NAME = socket.gethostname()

# 감시 폴더 — 항상 이 PC의 로컬 경로 (서버에 생성하지 않음, 사용자가 직접 지정)
WATCH_INPUT_DIR   = os.path.join(os.path.expanduser("~"), "AZtech", "watch_input")

# 서버(exe 위치) 기반 공용 폴더
PROCESSED_DIR     = os.path.join(BASE_DIR, "processed_output")
SHARED_CONFIG_DIR = os.path.join(BASE_DIR, "config")               # 모든 PC 공용
CONFIG_DIR        = os.path.join(BASE_DIR, "config", MACHINE_NAME) # 이 PC 전용
SETTINGS_FILE     = os.path.join(CONFIG_DIR, "app_settings.json")

# 읽기 전용 리소스 — exe 내부(_MEIPASS) 또는 소스 루트
REGISTRY_PATH = os.path.join(_RESOURCE_DIR, "assets", "data", "parts_registry_v2.json")
# 공개 저장소에는 실제 부품 레지스트리가 없다 → 예시 파일로 대체
if not os.path.exists(REGISTRY_PATH):
    REGISTRY_PATH = os.path.join(_RESOURCE_DIR, "assets", "data", "parts_registry.example.json")

# =========================================================
# 3. 사용자 설정값(JSON) 관리
# =========================================================

# 3. 사용자 설정값 기본값 (권한 문제가 없는 폴더 기준)
DEFAULT_SETTINGS = {
    "watch_dir": WATCH_INPUT_DIR,
    "master_save_path": PROCESSED_DIR, # 기본은 내 폴더 안으로!
    "kakao_report_enabled": True,
    "auto_move_processed": True
}

def init_directories():
    """쓰기 가능한 작업 폴더를 생성합니다. (읽기 전용 assets는 exe 내부에 번들됨)"""
    # WATCH_INPUT_DIR는 사용자가 로컬에서 직접 만들어 쓰므로 여기서 생성하지 않음
    for d in [PROCESSED_DIR, SHARED_CONFIG_DIR, CONFIG_DIR]:
        os.makedirs(d, exist_ok=True)

    # 번들된 공용 설정 파일을 외부 config 폴더로 복사 (없을 때만)
    import shutil
    for _fname in ("special_checks.json", "ocr_formats.py"):
        _dst = os.path.join(SHARED_CONFIG_DIR, _fname)
        if not os.path.exists(_dst):
            _src = os.path.join(_RESOURCE_DIR, "config", _fname)
            if not os.path.exists(_src) and _fname == "special_checks.json":
                # 공개 저장소에는 실제 검사 규칙 대신 예시 파일만 있다
                _src = os.path.join(_RESOURCE_DIR, "config", "special_checks.example.json")
            if os.path.exists(_src):
                shutil.copy2(_src, _dst)

def load_settings():
    """설정 파일을 읽어오거나 없으면 기본값을 반환합니다."""
    init_directories() # 폴더 생성 보장
    
    if not os.path.exists(SETTINGS_FILE):
        save_settings(DEFAULT_SETTINGS) # 없으면 기본값으로 파일 생성
        return DEFAULT_SETTINGS
    
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ 설정 로드 실패 (기본값 사용): {e}")
        return DEFAULT_SETTINGS

def save_settings(new_settings):
    """설정값을 JSON 파일로 저장합니다."""
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(new_settings, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"❌ 설정 저장 실패: {e}")

# 앱 구동 시 폴더 구조를 먼저 확보합니다.
init_directories()