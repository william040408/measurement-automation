import os
import sys
import time
import json
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication
)
from PyQt5.QtGui import QIcon
from modules.messenger import parse_custom_indices
from config.version import APP_VERSION


# ── 타이밍 로그 헬퍼 ──────────────────────────────────────────────────────
def _tlog(msg: str, _log_dir=[None]):
    """config/{MACHINE_NAME}/ 안에 aztech_YYYYMMDD.log 기록 (새 최상위 폴더 미생성)."""
    try:
        if _log_dir[0] is None:
            from config.settings import CONFIG_DIR
            _log_dir[0] = CONFIG_DIR          # 이미 존재하는 config/{PC이름}/ 재사용
            os.makedirs(_log_dir[0], exist_ok=True)
        ts   = time.strftime("%Y-%m-%d %H:%M:%S")
        date = time.strftime("%Y%m%d")
        line = f"[{ts}] {msg}\n"
        with open(os.path.join(_log_dir[0], f"aztech_{date}.log"), "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass

# [.exe] 빌드 환경과 [.py] 실행 환경 모두를 지원하는 경로 설정
if getattr(sys, 'frozen', False):
    # .exe 실행 시: exe 파일이 있는 폴더
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # .py 실행 시: 현재 소스코드 폴더
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 시스템 경로 추가 (나머지 import들이 정상 작동하게 함)
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from core.watcher import AZtechWatcher
from core.detector import PartDetector
from core.parser import parse_measurements
from modules.file_manager import FileManager
from config.settings import WATCH_INPUT_DIR, PROCESSED_DIR, REGISTRY_PATH, SETTINGS_FILE, SHARED_CONFIG_DIR, MACHINE_NAME
from ui.main_window import MainWindow
from ui.input_dialog import InputDialog

from ui.settings_dialog import SettingsDialog # 새로 만든 설정창 import
from PyPDF2 import PdfReader

# exe 옆에 VERSION.txt 기록 (탐색기에서 버전 확인용)
try:
    with open(os.path.join(BASE_DIR, "VERSION.txt"), "w", encoding="utf-8") as _vf:
        _vf.write(f"AZtech v{APP_VERSION}\n")
except Exception:
    pass

class WatcherThread(QThread):
    file_detected = pyqtSignal(str)
    log_received = pyqtSignal(str)  # ✨ 새로운 시그널 추가

    def __init__(self, watch_dir):
        super().__init__()
        self.watch_dir = watch_dir
        self.watcher = AZtechWatcher(self.on_detected, watch_dir=self.watch_dir)
        
        # ✨ Watcher의 시그널을 이 쓰레드의 시그널로 연결 (릴레이)
        self.watcher.signals.log_signal.connect(self.log_received.emit)

    def on_detected(self, file_path):
        time.sleep(0.7)
        self.file_detected.emit(file_path)

    def run(self):
        self.watcher.start()
        # QThread의 이벤트 루프를 유지하기 위해 exec() 호출 또는 적절한 대기
        self.exec() 

    def stop(self):
        # 1. 먼저 내부 watcher를 중단시킵니다.
        if hasattr(self, 'watcher'):
            self.watcher.stop()
            
        # 2. QThread의 이벤트 루프를 종료합니다.
        self.quit()
        
        # 3. 쓰레드가 완전히 종료될 때까지 최대 1초 기다립니다.
        if not self.wait(1000): 
            self.terminate() # 1초 뒤에도 안 꺼지면 강제 종료

class AZtechApp(MainWindow):
    def __init__(self):
        _t0_init = time.perf_counter()
        _tlog("=== 앱 시작 ===")

        _t1 = time.perf_counter()
        super().__init__()
        _tlog(f"  MainWindow.__init__: {(time.perf_counter()-_t1)*1000:.0f}ms")

        self.CONFIG_FILE = SETTINGS_FILE   # config/<컴퓨터이름>/app_settings.json

        _t1 = time.perf_counter()
        self.detector = PartDetector(REGISTRY_PATH)
        _tlog(f"  PartDetector 로드: {(time.perf_counter()-_t1)*1000:.0f}ms")

        self.file_mgr = FileManager()
        self.work_windows = []

        from modules.special_checker import load_special_checks
        _checks_path = os.path.join(SHARED_CONFIG_DIR, "special_checks.json")
        _t1 = time.perf_counter()
        self.special_checks_data = load_special_checks(_checks_path)
        _tlog(f"  special_checks 로드: {(time.perf_counter()-_t1)*1000:.0f}ms")

        # 💡 [수정] 파일에서 설정을 로드하거나 기본값을 사용
        _t1 = time.perf_counter()
        self.app_settings = self.load_settings()
        _tlog(f"  load_settings 완료: {(time.perf_counter()-_t1)*1000:.0f}ms")

        self.parser = self
        self.is_processing = False
        
        self.watcher_thread = None
        self.current_watch_dir = self.app_settings.get('watch_dir', WATCH_INPUT_DIR)
        self.btn_toggle_watch.clicked.disconnect()
        self.btn_toggle_watch.clicked.connect(self.toggle_engine)
        self.btn_settings.clicked.connect(self.open_settings)
        self.btn_process_watch.clicked.connect(self.open_watch_input_pdfs)
        self.btn_open_watch_dir.clicked.connect(self.open_watch_input_folder)
        
        # 💡 [핵심: 여기에 추가!] 일괄 복사 버튼의 옛날 연결을 끊고 새 함수로 연결합니다.
        try:
            self.btn_batch_process.clicked.disconnect()
        except TypeError:
            pass # 만약 끊을 연결이 없으면 그냥 넘어감
        self.btn_batch_process.clicked.connect(self.open_batch_mode)

        # 부품 추가 마법사 연결
        self.btn_add_part.clicked.connect(self.open_part_wizard)
        # 관리자 리포트 연결
        self.btn_admin_report.clicked.connect(self.open_admin_report)
        # ------------------------------------------------------------------

        _tlog(f"  앱 초기화 완료: {(time.perf_counter()-_t0_init)*1000:.0f}ms 총")
        self.add_log(f"🚀 AZtech 시스템이 준비되었습니다.  |  PC: {MACHINE_NAME}")
        self.add_log(f"📁 설정 경로: config\\{MACHINE_NAME}\\")

    def parse(self, pdf_path):
        """BatchDialog에서 호출할 파싱 브릿지 함수"""
        from PyPDF2 import PdfReader
        from core.parser import parse_measurements
        
        reader = PdfReader(pdf_path)
        full_text = ""
        for page in reader.pages:
            full_text += page.extract_text() + "\n"
        
        # 기존에 쓰시던 파싱 함수를 호출하여 결과를 반환합니다.
        return parse_measurements(full_text, debug=False)    

    @staticmethod
    def _safe_isdir(path: str, timeout: float = 3.0) -> bool:
        """네트워크 경로 행(hang) 방지 — timeout초 안에 응답 없으면 True(경로 유효) 반환"""
        import concurrent.futures
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                return ex.submit(os.path.isdir, path).result(timeout=timeout)
        except Exception:
            return True  # 타임아웃 시 경로를 건드리지 않음

    def load_settings(self):
        """JSON 파일에서 설정 불러오기"""
        try:
            with open(REGISTRY_PATH, 'r', encoding='utf-8') as f:
                _reg = json.load(f)
            _default_paths = {conf['name']: "" for conf in _reg.values()}
        except Exception:
            _default_paths = {}

        default_settings = {
            'watch_dir': WATCH_INPUT_DIR,
            'save_paths': _default_paths,
        }

        if os.path.exists(self.CONFIG_FILE):
            try:
                with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    default_settings.update(loaded)
            except Exception as e:
                print(f"설정 로드 에러: {e}")

        # 경로가 존재하지 않으면 기본값으로 복구 (네트워크 타임아웃 3초 제한)
        _t_isdir = time.perf_counter()
        if not self._safe_isdir(default_settings.get('watch_dir', '')):
            print(f"⚠️ 감시 폴더 없음 → 기본 폴더로 복구: {WATCH_INPUT_DIR}")
            default_settings['watch_dir'] = WATCH_INPUT_DIR
        _tlog(f"    isdir(watch_dir): {(time.perf_counter()-_t_isdir)*1000:.0f}ms — {default_settings.get('watch_dir','')}")

        for prog, path in default_settings.get('save_paths', {}).items():
            if path:
                _t_isdir = time.perf_counter()
                _exists = self._safe_isdir(path)
                _tlog(f"    isdir({prog}): {(time.perf_counter()-_t_isdir)*1000:.0f}ms — {path}")
                if not _exists:
                    print(f"⚠️ 저장 경로 없음 [{prog}] → 기본 폴더로 복구")
                    default_settings['save_paths'][prog] = ""

        # classify_settings 전역 모듈에 즉시 반영
        classify_cfg = default_settings.get('classify', {})
        import config.classify_settings as cs
        cs.update(
            margin_limit=classify_cfg.get('margin_limit', 0.003),
            ratio_limit=classify_cfg.get('ratio_limit', 0.85),
            mode=classify_cfg.get('mode', 'OR'),
        )

        return default_settings

    def save_settings(self):
        """현재 설정을 JSON 파일로 저장"""
        try:
            # ✅ 절대 경로로 저장되는지 다시 확인
            save_dir = os.path.dirname(self.CONFIG_FILE)
            if not os.path.exists(save_dir):
                os.makedirs(save_dir, exist_ok=True)
                
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.app_settings, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            self.add_log(f"❌ 설정 저장 실패: {e}")
            return False

    # 💡 [수정됨] 1. 설정 창을 독립된 창으로 띄우기
    def open_settings(self):
        """설정 창 열기 (독립된 별개의 창으로 띄우기)"""
        from ui.settings_dialog import SettingsDialog
        
        # 이미 창이 열려있다면 새로 띄우지 않고 앞으로 가져오기만 함
        if hasattr(self, 'settings_dialog') and self.settings_dialog.isVisible():
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()
            return

        # 팝업창 객체를 self에 저장 (창이 바로 꺼지는 현상 방지)
        self.settings_dialog = SettingsDialog(self.app_settings)
        
        # 창이 닫히며(accept) 저장 버튼이 눌렸을 때 _on_settings_saved 실행
        self.settings_dialog.accepted.connect(self._on_settings_saved)
        
        # exec() 대신 show()를 사용해 메인 창과 분리!
        self.settings_dialog.show()

    # 💡 [새로 추가] 설정이 저장될 때 비동기적으로 실행되는 함수
    def _on_settings_saved(self):
        """설정 창이 닫힐 때 실행되는 저장 로직"""
        self.app_settings = self.settings_dialog.get_final_settings()
        if self.save_settings():
            self.add_log("⚙️ 설정이 파일에 반영구적으로 저장되었습니다.")

        # classify_settings 즉시 반영 (재시작 불필요)
        classify_cfg = self.app_settings.get('classify', {})
        import config.classify_settings as cs
        cs.update(
            margin_limit=classify_cfg.get('margin_limit'),
            ratio_limit=classify_cfg.get('ratio_limit'),
            mode=classify_cfg.get('mode'),
        )
        self.add_log(f"📐 UP/UN 기준 적용: {cs.MODE} | 절대값 {cs.MARGIN_LIMIT}mm | 비율 {cs.RATIO_LIMIT*100:.1f}%")

        if self.watcher_thread and self.watcher_thread.isRunning():
            self.add_log("⚠️ 감시 폴더 변경을 적용하려면 감시를 중지했다가 다시 시작하세요.")

    def open_part_wizard(self):
        """새 부품 추가 마법사 열기"""
        from ui.part_wizard_dialog import PartWizardDialog
        if hasattr(self, '_part_wizard') and self._part_wizard.isVisible():
            self._part_wizard.raise_()
            self._part_wizard.activateWindow()
            return
        self._part_wizard = PartWizardDialog(parent=self)
        self._part_wizard.part_saved.connect(lambda key, name: self.add_log(f"✅ 새 부품 저장: [{key}] {name}"))
        self._part_wizard.show()

    def open_admin_report(self):
        """관리자 데이터 리포트 창 열기"""
        from ui.admin_report_dialog import AdminReportDialog
        if hasattr(self, '_admin_report_dlg') and self._admin_report_dlg.isVisible():
            self._admin_report_dlg.raise_()
            self._admin_report_dlg.activateWindow()
            return
        try:
            with open(REGISTRY_PATH, 'r', encoding='utf-8') as f:
                registry = json.load(f)
        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.critical(self, "오류", f"부품 레지스트리 로드 실패:\n{e}")
            return
        self._admin_report_dlg = AdminReportDialog(self.detector, registry, parent=self)
        self._admin_report_dlg.show()

    # 💡 [새로 추가] 2. 일괄 복사(Batch) 창을 독립된 창으로 띄우기
    def open_batch_mode(self):
        """일괄 엑셀 복사 창 열기 (독립된 별개의 창으로 띄우기)"""
        # 파일명과 클래스명은 사원님의 실제 파일에 맞게 수정하세요 (예: batch_dialog.py)
        from ui.batch_dialog import BatchDialog 
        
        # 이미 열려있으면 앞으로 가져오기
        if hasattr(self, 'batch_dialog') and self.batch_dialog.isVisible():
            self.batch_dialog.raise_()
            self.batch_dialog.activateWindow()
            return

        # self 변수에 담아서 생명 유지
        self.batch_dialog = BatchDialog(main_app=self) 
        
        # 메인 창과 독립적으로 띄우기
        self.batch_dialog.show()

    def execute_save_logic(self, pdf_path, config, measurements, user_data, part_key, dialog):
        """실제 파일을 이동하고 저장하는 로직 (네트워크 vs 파일점유 에러 분리)"""
        _t0_save = time.perf_counter()
        _tlog(f"저장 시작: {os.path.basename(pdf_path)}")
        try:
            # 재저장 시: 원본 경로가 이미 이동된 경우 이전 저장 경로를 소스로 사용
            actual_pdf_path = pdf_path
            if not os.path.exists(actual_pdf_path):
                saved_path = getattr(dialog, '_saved_final_path', "") if dialog else ""
                if saved_path and os.path.exists(saved_path):
                    actual_pdf_path = saved_path
                    self.add_log(f"🔄 재저장: 이동된 파일 사용 → {os.path.basename(saved_path)}")
                else:
                    raise FileNotFoundError(f"원본 PDF를 찾을 수 없습니다: {pdf_path}")

            part_display_name = config.get('name', part_key)

            # 측정의뢰품 전용 저장 로직
            if user_data.get('is_sample'):
                import shutil
                _sp = self.app_settings.get('save_paths', {})
                _save_dir = _sp.get(part_display_name) or _sp.get(part_key, "")
                if not _save_dir or not os.path.isdir(_save_dir.strip()):
                    _save_dir = PROCESSED_DIR
                _base = f"{part_display_name} 측정의뢰품"
                _dest = os.path.join(_save_dir, f"{_base}.pdf")
                if os.path.exists(_dest):
                    _n = 2
                    while os.path.exists(os.path.join(_save_dir, f"{_base}{_n}.pdf")):
                        _n += 1
                    _dest = os.path.join(_save_dir, f"{_base}{_n}.pdf")
                shutil.move(actual_pdf_path, _dest)
                from ui.input_dialog import InputDialog
                InputDialog.save_history()
                _tlog(f"  저장 완료(의뢰품): {(time.perf_counter()-_t0_save)*1000:.0f}ms  → {os.path.basename(_dest)}")
                self.add_log(f"✅ 측정의뢰품 저장 완료: {_dest}")
                if dialog:
                    dialog._saved_final_path = _dest
                    dialog.mark_as_saved()
                return

            save_paths = self.app_settings.get('save_paths', {})
            custom_save_path = save_paths.get(part_display_name) or save_paths.get(part_key, "")

            if not custom_save_path or not custom_save_path.strip():
                custom_save_path = PROCESSED_DIR
            elif not os.path.isdir(custom_save_path.strip()):
                self.add_log(f"⚠️ 저장 경로 없음 → 기본 폴더로 저장: {PROCESSED_DIR}")
                custom_save_path = PROCESSED_DIR

            self.file_mgr.set_base_path(custom_save_path.strip())

            # 🚀 파일 이동 시도
            from modules.file_manager import FileExistsConflict
            try:
                final_path = self.file_mgr.move_and_save(
                    actual_pdf_path, config, measurements,
                    user_data['site'], user_data['machines'],
                    user_data['timing'], user_data['tool_changes'], mode='move'
                )
            except FileExistsConflict as conflict:
                intended_name = os.path.basename(conflict.intended_path)
                unique_name   = os.path.basename(conflict.unique_path)
                from PyQt5.QtWidgets import QMessageBox
                reply = QMessageBox.warning(
                    dialog, "⚠️ 파일명 중복",
                    f"'{intended_name}' 파일이 이미 존재합니다.\n\n"
                    f"'{unique_name}'로 자동 저장하시겠습니까?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                if reply != QMessageBox.Yes:
                    self._restore_save_button(dialog)
                    return
                final_path = self.file_mgr.force_move(actual_pdf_path, conflict.unique_path, mode='move')

            # [✅ 성공 로직]
            from ui.input_dialog import InputDialog
            InputDialog.save_history()
            _tlog(f"  저장 완료: {(time.perf_counter()-_t0_save)*1000:.0f}ms  → {os.path.basename(final_path)}")
            self.add_log(f"✅ 분류 저장 완료: {final_path}")
            if dialog:
                dialog._saved_final_path = final_path  # 재저장 시 소스 경로 갱신
                dialog.mark_as_saved()

        except PermissionError as e:
            # 📄 1순위: PDF가 열려있는 경우 (파일 접근 거부)
            self.add_log(f"⚠️ 저장 실패: 파일 사용 중 ({e})")
            self._show_custom_alert(
                "📄 파일 사용 중", 
                "해당 PDF가 다른 프로그램에서 열려 있습니다.\n뷰어를 완전히 종료한 후 다시 시도해 주세요.", 
                parent=dialog
            )
            self._restore_save_button(dialog)

        except (OSError, ConnectionError) as e:
            # 🌐 2순위: 랜선/네트워크 드라이브 문제 (경로 없음)
            self.add_log(f"🌐 저장 실패: 경로 접근 불가 ({e})")
            self._show_custom_alert(
                "⚠️ 저장 경로 접근 불가", 
                "서버 연결이 끊겼거나 대상 폴더를 찾을 수 없습니다.\n네트워크 상태를 확인한 후 다시 시도해 주세요.", 
                parent=dialog
            )
            self._restore_save_button(dialog)

        except Exception as e:
            # ❌ 기타 예외
            self.add_log(f"❌ 기타 저장 에러: {e}")
            self._show_custom_alert("❌ 저장 실패", f"예상치 못한 오류가 발생했습니다:\n{str(e)}", parent=dialog)
            self._restore_save_button(dialog)

        finally:
            self.file_mgr.set_base_path(PROCESSED_DIR)

    # ==========================================
    # 🛠️ 에러 처리를 돕는 헬퍼 함수 2개 추가
    # ==========================================
    def _show_custom_alert(self, title, msg, parent=None):
        """커스텀 알림창 띄우기"""
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.critical(parent if parent else self, title, msg)

    def _scan_existing_pdfs(self, watch_dir):
        """감시 시작 시 watch_input에 이미 있는 PDF를 확인해 처리 제안."""
        if not os.path.isdir(watch_dir):
            return
        existing = [
            os.path.join(watch_dir, f)
            for f in os.listdir(watch_dir)
            if f.lower().endswith('.pdf') and os.path.isfile(os.path.join(watch_dir, f))
        ]
        if not existing:
            return
        from PyQt5.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self,
            "미처리 파일 발견",
            f"watch_input에 처리되지 않은 PDF {len(existing)}개가 있습니다.\n\n지금 처리하시겠습니까?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply == QMessageBox.Yes:
            for pdf in sorted(existing):
                self.process_new_file(pdf)

    def open_watch_input_pdfs(self):
        """버튼으로 watch_input 미처리 PDF를 직접 열기 (다이얼로그 없이 바로 처리)"""
        watch_dir = self.app_settings.get('watch_dir', WATCH_INPUT_DIR)
        if not os.path.isdir(watch_dir):
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "폴더 없음", f"watch_input 폴더를 찾을 수 없습니다:\n{watch_dir}")
            return

        all_pdfs = [
            os.path.abspath(os.path.join(watch_dir, f))
            for f in os.listdir(watch_dir)
            if f.lower().endswith('.pdf') and os.path.isfile(os.path.join(watch_dir, f))
        ]
        _in_dialogs = {
            os.path.abspath(d.full_pdf_path)
            for d in self.work_windows
            if getattr(d, 'full_pdf_path', '')
        }
        unprocessed = [p for p in all_pdfs if p not in _in_dialogs]

        if not unprocessed:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(self, "처리할 파일 없음", "watch_input에 처리되지 않은 PDF가 없습니다.")
            return

        for pdf in sorted(unprocessed):
            self.process_new_file(pdf)

    def open_watch_input_folder(self):
        """watch_input 폴더를 파일 탐색기로 열기"""
        import subprocess
        watch_dir = self.app_settings.get('watch_dir', WATCH_INPUT_DIR)
        if not watch_dir or not os.path.isdir(watch_dir):
            from PyQt5.QtWidgets import QMessageBox
            if watch_dir:
                try:
                    os.makedirs(watch_dir, exist_ok=True)
                except Exception:
                    QMessageBox.warning(self, "폴더 없음",
                        f"watch_input 폴더를 열 수 없습니다:\n{watch_dir}\n\n설정에서 경로를 확인해 주세요.")
                    return
            else:
                QMessageBox.warning(self, "경로 미설정", "설정에서 watch_input 경로를 먼저 지정해 주세요.")
                return
        subprocess.Popen(f'explorer "{os.path.normpath(watch_dir)}"')

    def _handle_discard(self, pdf_path):
        """파기 버튼 — watch_input의 PDF를 삭제하고 history에 남기지 않음."""
        try:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
                self.add_log(f"🗑️ 파기 완료: {os.path.basename(pdf_path)}")
            else:
                self.add_log(f"⚠️ 파기 대상 없음 (이미 이동됨?): {os.path.basename(pdf_path)}")
        except Exception as e:
            self.add_log(f"❌ 파기 실패: {e}")

    def _restore_save_button(self, dialog):
        """에러 발생 시 다이얼로그의 버튼을 다시 살려줌"""
        if dialog and hasattr(dialog, 'btn_save'):
            dialog.btn_save.setEnabled(True)
            dialog.btn_save.setText("💾 데이터 분류 저장")
            dialog.btn_save.setStyleSheet("""
                background-color: #e67e22; color: white; 
                font-weight: bold; font-size: 13pt; border-radius: 8px;
            """)
            dialog.btn_save.repaint()

    def toggle_engine(self):
        if self.watcher_thread and self.watcher_thread.isRunning():
            self.watcher_thread.stop()
            
            # UI 변경: 다시 시작할 수 있도록 초록색으로
            self.btn_toggle_watch.setText("감시 시작")
            self.btn_toggle_watch.setStyleSheet("""
                background-color: #2ecc71; color: white; 
                border-radius: 10px; border: none; font-weight: bold;
            """)
            self.lbl_status.setText("대기 중")
            self.lbl_status.setStyleSheet("color: #7f8c8d; border: none;")
            
            # 로그는 이제 watcher.signals에서 자동으로 날아오지만, 
            # 버튼 클릭 직관성을 위해 직접 남겨줍니다.
            self.statusBar().showMessage("준비 완료")
        else:
            watch_target = self.app_settings.get('watch_dir', WATCH_INPUT_DIR)
            self.current_watch_dir = watch_target
            self.watcher_thread = WatcherThread(watch_target)

            # 시그널 연결
            self.watcher_thread.file_detected.connect(self.process_new_file)
            self.watcher_thread.log_received.connect(self.add_log)

            self.watcher_thread.start()

            # UI 변경: 중지할 수 있도록 빨간색으로
            self.btn_toggle_watch.setText("감시 중지")
            self.btn_toggle_watch.setStyleSheet("""
                background-color: #e74c3c; color: white;
                border-radius: 10px; border: none; font-weight: bold;
            """)
            self.lbl_status.setText("🔍 실시간 감시 중...")
            self.lbl_status.setStyleSheet("color: #e74c3c; border: none;")

            self.statusBar().showMessage("감시 엔진 작동 중...")

            # 감시 꺼둔 사이 쌓인 파일 감지
            self._scan_existing_pdfs(watch_target)

    def process_new_file(self, pdf_path):
        # 1. 파일이 실제로 존재하는지 광속 체크
        if not os.path.exists(pdf_path):
            return
            
        # 💡 [핵심: 초 쿨타임 방어막 생성]
        if not hasattr(self, 'recent_files'):
            self.recent_files = {} # 최근 파일 기록장 생성
            
        current_time = time.time()
        
        # 만약 방금(2초 이내) 감지했던 파일이 또 울리면? -> 무시하고 돌아감!
        if pdf_path in self.recent_files:
            if current_time - self.recent_files[pdf_path] < 10.0:
                return 
                
        # 무사히 통과했다면 현재 시간을 기록장에 작성
        self.recent_files[pdf_path] = current_time

        file_name = os.path.basename(pdf_path)

        # watch_input에 다이얼로그 없는 미처리 PDF가 있으면 경고 (차단하지 않고 계속 진행)
        _watch_dir = os.path.dirname(pdf_path)
        if os.path.isdir(_watch_dir):
            _other_paths = [
                os.path.abspath(os.path.join(_watch_dir, f))
                for f in os.listdir(_watch_dir)
                if f.lower().endswith('.pdf')
                and os.path.abspath(os.path.join(_watch_dir, f)) != os.path.abspath(pdf_path)
                and os.path.isfile(os.path.join(_watch_dir, f))
            ]
            if _other_paths:
                _in_dialogs = {
                    os.path.abspath(d.full_pdf_path)
                    for d in self.work_windows
                    if getattr(d, 'full_pdf_path', '')
                }
                _orphaned = [p for p in _other_paths if p not in _in_dialogs]
                if _orphaned:
                    _names = "\n".join(f"  • {os.path.basename(p)}" for p in _orphaned[:5])
                    _extra = f"\n  ... 외 {len(_orphaned)-5}개" if len(_orphaned) > 5 else ""
                    self.add_log(
                        f"⚠️ 미처리 PDF {len(_orphaned)}개 있음: {_names.strip()}{_extra} — "
                        f"처리 후 'watch_input 미처리 PDF 열기' 버튼으로 처리하세요."
                    )

        _t0_proc = time.perf_counter()
        _tlog(f"PDF 감지: {file_name}")
        self.add_log(f"📂 파일 감지: {file_name}")

        try:
            from io import BytesIO
            import pyperclip

            # 파일 읽기
            _t1 = time.perf_counter()
            with open(pdf_path, 'rb') as f:
                pdf_data = BytesIO(f.read())
            _tlog(f"  파일 읽기: {(time.perf_counter()-_t1)*1000:.0f}ms")

            # 제품 인식
            _t1 = time.perf_counter()
            res = self.detector.detect_config(pdf_path)
            _tlog(f"  부품 인식: {(time.perf_counter()-_t1)*1000:.0f}ms")
            if not res or not res[0]:
                self.add_log(f"⚠️ [인식 실패] {file_name}")
                self.is_processing = False
                return

            part_key, config = res
            self.add_log(f"✅ 인식 성공: {part_key}")

            # PDF 데이터 추출 및 파싱
            _t1 = time.perf_counter()
            reader = PdfReader(pdf_data)
            full_text = "".join([page.extract_text() + "\n" for page in reader.pages])
            measurements = parse_measurements(full_text, debug=False)
            _tlog(f"  PDF 파싱: {(time.perf_counter()-_t1)*1000:.0f}ms  ({len(measurements)}항목)")
            self.add_log(f"📊 파싱 완료: {len(measurements)}개 항목 감지")

            # 다이얼로그 생성
            _t1 = time.perf_counter()
            from PyQt5.QtCore import Qt
            dialog = InputDialog(file_name, config, None)
            dialog.full_pdf_path = os.path.abspath(pdf_path)
            dialog.get_work_windows = lambda: self.work_windows
            
            # [수정] 창이 닫힐 때 리스트에서 제거하는 연결
            dialog.finished.connect(lambda: self.work_windows.remove(dialog) if dialog in self.work_windows else None)
            _tlog(f"  다이얼로그 생성: {(time.perf_counter()-_t1)*1000:.0f}ms")

            # --- [핵심: handle_action 로직 완성] ---
            def handle_action(action_type, data, info=None):
                from modules.excel_copy import ExcelCopier
                from modules.messenger import get_part_report
                
                def to_f3(val):
                    try: return f"{float(val):.3f}"
                    except: return str(val)

                if action_type == "excel":
                    p_idx, b_idx = info
                    m_no = data['machines'][p_idx]
                    ExcelCopier(config).copy_part(measurements, p_idx, block_idx=b_idx)
                    b_name = config['excel_mapping'][b_idx]['block_name']
                    self.add_log(f"📊 [{m_no}호기] '{b_name}' 복사 완료!")
                
                elif action_type == "kakao":
                    p_idx    = info
                    m_no     = data['machines'][p_idx]
                    type_suf = data['tool_changes'][p_idx] if p_idx < len(data['tool_changes']) else ""
                    _is_smp  = data.get('is_sample', False)
                    report, _ = get_part_report(data['site'], m_no, data['timing'], measurements, config, p_idx, type_suffix=type_suf, is_sample=_is_smp)
                    pyperclip.copy(report)
                    _label = "측정의뢰품" if _is_smp else f"{m_no}호기"
                    self.add_log(f"💬 [{_label}] 카톡 보고서 복사 완료!")
                
                elif action_type == "preview":
                    if getattr(self, '_is_previewing', False): return
                    self._is_previewing = True
                    
                    # 💡 1. 실행될 함수 정의 (모든 로직이 이 안에 있어야 함)
                    def run_preview_update():
                        _t_preview = time.perf_counter()
                        try:
                            machines = data.get('machines', [])
                            print(f"\n[DEBUG] 타이머 실행 - 대상 호기: {machines}")

                            # SectionMarker 제외 — JSON 인덱스는 순수 측정값 기준
                            from core.models import SectionMarker
                            filtered_meas = [m for m in measurements if not isinstance(m, SectionMarker)]
                            
                            full_debug_text = ""
                            ranges = config.get("data_ranges", [])
                            from PyQt5.QtWidgets import QTextEdit

                            for p_idx, m_no in enumerate(machines):
                                # (1) 리포트 생성
                                try:
                                    _type_suf = data['tool_changes'][p_idx] if p_idx < len(data['tool_changes']) else ""
                                    _is_smp   = data.get('is_sample', False)
                                    report, _ = get_part_report(data['site'], m_no, data['timing'], filtered_meas, config, p_idx, type_suffix=_type_suf, is_sample=_is_smp)
                                except Exception as e:
                                    report = f"리포트 생성 실패 ({m_no}호기)"
                                    print(f"[ERROR] {m_no}호기 리포트 생성 에러: {e}")

                                # (2) UI 위젯 찾기
                                target_name = f"report_edit_{p_idx}"
                                p_edit = dialog.findChild(QTextEdit, target_name)
                                
                                if p_edit:
                                    p_edit.setPlainText(report)

                                    # part_type 필드 우선, 없으면 이름으로 추론 (하위호환)
                                    part_name = config.get("name", "")
                                    _pt = config.get("part_type", "")
                                    if not _pt:
                                        if "ACV" in part_name: _pt = "acv"
                                        elif "APC" in part_name: _pt = "apc"
                                    is_kakao_required = _pt in ("acv", "apc")
                                    
                                    # 💡 [색상 분기 로직]
                                    if "ng" in report:
                                        # 🔴 1순위: NG가 1개라도 있는 경우 (빨간색 - 즉시 전송 요망)
                                        p_edit.setStyleSheet("""
                                            background-color: #ffffff; 
                                            color: #c0392b; 
                                            font-weight: bold; 
                                            border: 2px solid #e74c3c; 
                                            border-radius: 5px;
                                            padding: 5px;
                                        """)
                                    elif "un" in report or "up" in report or is_kakao_required:
                                        # 🟠 2순위: NG는 없지만 UN이나 UP이 있는 경우 (주황색 - 카톡 전송 요망)
                                        p_edit.setStyleSheet("""
                                            background-color: #ffffff; 
                                            color: #d35400; 
                                            font-weight: bold; 
                                            border: 2px solid #e67e22; 
                                            border-radius: 5px;
                                            padding: 5px;
                                        """)
                                    else:
                                        # 🟢 3순위: ALL OK 또는 불량이 전혀 없는 상태 (초록색 - 패스 가능)
                                        p_edit.setStyleSheet("""
                                            background-color: #eafaf1; 
                                            color: #27ae60; 
                                            font-weight: bold; 
                                            border: 2px solid #2ecc71; 
                                            border-radius: 5px;
                                            padding: 5px;
                                        """)
                                        
                                    print(f"   ㄴ [SUCCESS] {target_name} 주입 및 3단계 색상 변경 완료")
                                else:
                                    print(f"   ㄴ [FAIL] {target_name} 위젯을 여전히 찾을 수 없음")


                                # (3) 하단 상세 로그 누적
                                full_debug_text += f"=========== [{m_no}호기] 상세 이상 항목 ===========\n"
                                if p_idx < len(ranges):
                                    # 💡 이 부분이 핵심입니다: messenger와 동일한 인덱스 추출 로직 사용
                                    target_pattern = ranges[p_idx]
                                    if not isinstance(target_pattern, list): target_pattern = [target_pattern]
                                    target_indices = parse_custom_indices(target_pattern)

                                    any_issue = False
                                    for abs_idx in target_indices:
                                        if abs_idx >= len(filtered_meas): continue

                                        m = filtered_meas[abs_idx]
                                        status = m.classify().upper() if hasattr(m, 'classify') else "UNKNOWN"
                                        
                                        if status in ["NG", "UN", "UP"]:
                                            any_issue = True
                                            icon = {"NG": "🔴 [NG]", "UN": "🟡 [UN]", "UP": "🟠 [UP]"}.get(status, "⚪")
                                            av = to_f3(getattr(m, 'actual_value', 0.0))
                                            # standard_value가 함수인지 값인지 체크하는 기존 로직 유지
                                            sv_val = getattr(m, 'standard_value', 0.0)
                                            nv = to_f3(sv_val() if callable(sv_val) else sv_val)
                                            
                                            full_debug_text += f"{icon} No.{abs_idx:02d} | {getattr(m, 'name', 'Unknown')}\n"
                                            full_debug_text += f"      ㄴ 측정:{av} (기준:{nv})\n"
                                    
                                    if not any_issue: full_debug_text += "✅ 이상 항목 없음\n"
                                else:
                                    full_debug_text += "⚠️ 범위 설정 없음\n"
                                full_debug_text += "-" * 45 + "\n\n"

                            # (4) 하단 통합 로그창 업데이트
                            dialog.debug_log.setPlainText(full_debug_text)

                            # (5) 제품별 특이사항 체크
                            try:
                                from modules.special_checker import run_checks, load_special_checks
                                # 항상 최신 파일에서 읽기 (앱 재시작 없이도 반영)
                                _checks_path = os.path.join(SHARED_CONFIG_DIR, "special_checks.json")
                                _t_sc = time.perf_counter()
                                _checks_data = load_special_checks(_checks_path)
                                _tlog(f"  special_checks 읽기: {(time.perf_counter()-_t_sc)*1000:.0f}ms")
                                if not _checks_data:
                                    print(f"[special_checker] 설정 없음 — {_checks_path}")
                                check_results = run_checks(part_key, measurements, _checks_data)
                                # part_idx별로 묶기
                                alerts_by_idx = {}
                                for cr in check_results:
                                    pidx = cr.get("part_idx", 0)
                                    alerts_by_idx.setdefault(pidx, []).append(cr["message"])
                                # 표시: 알림 있는 호기만 갱신, 나머지는 숨김
                                for p_idx in range(len(machines)):
                                    dialog.set_special_alerts(p_idx, alerts_by_idx.get(p_idx, []))
                            except Exception as sc_e:
                                print(f"[ERROR] 특이사항 체크 에러: {sc_e}")

                        except Exception as preview_e:
                            print(f"[ERROR] 프리뷰 내부 실행 에러: {preview_e}")
                        finally:
                            _tlog(f"  합불판정(run_preview_update): {(time.perf_counter()-_t_preview)*1000:.0f}ms")
                            # 💡 함수 종료 시 플래그 해제 (매우 중요)
                            self._is_previewing = False

                    # 💡 2. 정의한 함수를 0.15초 뒤에 실행하도록 예약
                    from PyQt5.QtCore import QTimer
                    QTimer.singleShot(150, run_preview_update)

            # [핵심 변경 1] 시그널 연결 (기존과 동일)
            dialog.action_triggered.connect(handle_action)
            dialog.save_requested.connect(lambda d: self.execute_save_logic(pdf_path, config, measurements, d, part_key, dialog))
            dialog.discard_requested.connect(lambda: self._handle_discard(pdf_path))

            # [핵심 변경 2] .exec_()가 아니라 .show()를 사용합니다!
            self.work_windows.append(dialog)
            _t1 = time.perf_counter()
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            _tlog(f"  다이얼로그 표시: {(time.perf_counter()-_t1)*1000:.0f}ms")
            _tlog(f"  PDF감지→다이얼로그표시 총: {(time.perf_counter()-_t0_proc)*1000:.0f}ms")


        except Exception as e:
            self.add_log(f"🔥 에러: {str(e)}")
            import traceback
            self.add_log(traceback.format_exc())

if __name__ == "__main__":
    app = QApplication(sys.argv)

    icon_path = os.path.join(BASE_DIR, "assets", "data", "aztech_icon_opaque.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # ── 스플래시 스크린 ───────────────────────────────────────────────
    from PyQt5.QtWidgets import QSplashScreen
    from PyQt5.QtGui import QPixmap, QPainter, QColor, QFont
    from PyQt5.QtCore import Qt

    _W, _H = 460, 260
    _pix = QPixmap(_W, _H)
    _p = QPainter(_pix)
    _p.fillRect(0, 0, _W, _H, QColor("#1e1e2e"))          # 배경
    _p.fillRect(0, 0, _W, 5, QColor("#e67e22"))            # 상단 주황 강조선
    _p.setPen(QColor("#ffffff"))
    _p.setFont(QFont("Malgun Gothic", 30, QFont.Bold))
    _p.drawText(0, 40, _W, 80, Qt.AlignCenter, "AZtech")
    _p.setPen(QColor("#aaaaaa"))
    _p.setFont(QFont("Malgun Gothic", 12))
    _p.drawText(0, 120, _W, 36, Qt.AlignCenter, "자동화 측정 시스템")
    _p.setPen(QColor("#e67e22"))
    _p.setFont(QFont("Malgun Gothic", 10))
    _p.drawText(0, 170, _W, 30, Qt.AlignCenter, "로딩 중...")
    _p.setPen(QColor("#555555"))
    _p.setFont(QFont("Malgun Gothic", 9))
    _p.drawText(0, 230, _W, 24, Qt.AlignCenter, f"v{APP_VERSION}")
    _p.end()

    _splash = QSplashScreen(_pix, Qt.WindowStaysOnTopHint)
    _splash.show()
    app.processEvents()

    def _splash_msg(msg):
        _splash.showMessage(msg, Qt.AlignBottom | Qt.AlignHCenter, QColor("#e67e22"))
        app.processEvents()

    _splash_msg("시스템 초기화 중...")
    # ─────────────────────────────────────────────────────────────────

    ex = AZtechApp()
    _splash_msg("준비 완료!")
    ex.show()
    _splash.finish(ex)
    sys.exit(app.exec())