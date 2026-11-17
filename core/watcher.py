import os
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from config.settings import WATCH_INPUT_DIR, PROCESSED_DIR
from PyQt5.QtCore import QObject, pyqtSignal # ✨ 추가

# ✨ 시그널을 정의하기 위한 클래스 추가
class WatcherSignals(QObject):
    log_signal = pyqtSignal(str) # 로그 메시지 전달용

class PDFHandler(FileSystemEventHandler):
    def __init__(self, detector_callback, signals): # ✨ signals 인자 추가
        super().__init__()
        self.detector_callback = detector_callback
        self.signals = signals # ✨ 시그널 저장

    def _handle_pdf_path(self, path):
        """공통 PDF 감지 처리 (create / move 공용)"""
        filename = os.path.basename(path)
        if filename.startswith('~') or filename.startswith('.'): return
        msg = f"📂 [감시중] 새 PDF 발견: {filename}"
        print(msg)
        self.signals.log_signal.emit(msg)
        time.sleep(1.5)
        self.detector_callback(path)

    def on_created(self, event):
        if event.is_directory: return
        if not event.src_path.lower().endswith('.pdf'): return
        self._handle_pdf_path(event.src_path)

    def on_moved(self, event):
        """임시 파일 → .pdf 이름 변경으로 저장하는 프로그램 대응"""
        if event.is_directory: return
        if not event.dest_path.lower().endswith('.pdf'): return
        self._handle_pdf_path(event.dest_path)

class AZtechWatcher:
    def __init__(self, callback_func, watch_dir=None):
        self.path = watch_dir if watch_dir else WATCH_INPUT_DIR
        self.callback = callback_func
        self.observer = None
        self.signals = WatcherSignals() # ✨ 시그널 객체 생성

        if not os.path.exists(self.path):
            os.makedirs(self.path, exist_ok=True)

    def start(self):
        # ✨ PDFHandler에 signals 전달
        event_handler = PDFHandler(self.callback, self.signals)
        self.observer = Observer()
        self.observer.schedule(event_handler, self.path, recursive=False)
        self.observer.start()
        
        msg = f"🚀 실시간 감시 시작: {self.path}"
        print(msg)
        self.signals.log_signal.emit(msg) # ✨ 시작 로그 전달

    def stop(self):
        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=1)
            msg = "🛑 실시간 감시 중단"
            print(msg)
            self.signals.log_signal.emit(msg)