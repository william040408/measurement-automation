import io
import time
import numpy as np
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QWidget, QFrame, QMessageBox, QScrollArea,
    QApplication, QTextEdit, QShortcut
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread, QTimer
from PyQt5.QtGui import QPixmap, QImage, QKeySequence, QDragEnterEvent, QDropEvent


def _display_width(s: str) -> int:
    """CJK 문자를 2, ASCII를 1로 계산한 표시 폭."""
    return sum(2 if ord(c) > 0x7F else 1 for c in s)


def _ljust_display(s: str, width: int) -> str:
    return s + " " * max(0, width - _display_width(s))


# 파일명(stem) → GT 값 매핑 (개발용)
_GT_BY_FILE = {
    "ex1":   [42.327, 28.030, -0.031, -0.025,  0.074,
              28.362, 55.948,  2.140,  2.121,  2.129,
               2.143,  2.133,  0.075,  1.040,  1.094, 89.775],
    "ex2":   [42.327, 28.030, -0.031, -0.025,  0.074,
              28.362, 55.948,  2.140,  2.121,  2.129,
               2.143,  2.133,  0.075,  1.040,  1.094, 89.775],
    "ex3":   [42.327, 28.030, -0.031, -0.025,  0.074,
              28.362, 55.948,  2.140,  2.121,  2.129,
               2.143,  2.133,  0.075,  1.040,  1.094, 89.775],
    "ex4":   [42.327, 28.030, -0.031, -0.025,  0.074,
              28.362, 55.948,  2.140,  2.121,  2.129,
               2.143,  2.133,  0.075,  1.040,  1.094, 89.775],
    "ex5":   [42.327, 28.030, -0.031, -0.025,  0.074,
              28.362, 55.948,  2.140,  2.121,  2.129,
               2.143,  2.133,  0.075,  1.040,  1.094, 89.775],
    "short": [42.311, 28.023,  0.038, -0.028,  0.060,
              28.328, 55.898,  2.118,  2.118,  2.124,
               2.131,  2.123,  0.041,  1.082,  1.043, 87.915],
    # 1개짜리: OCR items 순서는 CMM 화면 순 (상단/하단거리가 슬롯보다 먼저),
    # GT는 그 순서 그대로 기록됨 (Excel 출력 순서와 다름 — _build_excel_row가 label로 재정렬)
    "1개짜리":   [42.305, 28.036, -0.016, -0.012,  0.026,
                  1.096,  1.045, 28.218, 56.049,  2.138,
                  2.129,  2.143,  2.145,  2.138,  0.065, 89.411],
    "1개짜리-2": [42.208, 28.041, -0.026, -0.026,  0.057,
                  1.050,  1.091, 28.241, 56.045,  2.142,
                  2.128,  2.141,  2.146,  2.139,  0.047, 89.850],
    "tgdi":  [42.367, 27.992,  0.065, -0.002,  0.134,
               1.082,  1.045,  0.097, 28.355, 55.902,
               2.124,  2.124,  2.124,  2.130,  2.126],
}


# ──────────────────────────────────────────────────────────────────────────────
# OCR 백그라운드 워커
# ──────────────────────────────────────────────────────────────────────────────
class OcrWorker(QThread):
    finished      = pyqtSignal(object)  # result dict or None
    error_occurred = pyqtSignal(str)    # traceback 문자열

    def __init__(self, pil_img):
        super().__init__()
        self._pil = pil_img
        self.debug_log = []  # _on_ocr_done에서 파일 저장용

    def run(self):
        import traceback
        from core.ocr_extractor import extract_measurements
        try:
            result = extract_measurements(self._pil, _log=self.debug_log)
        except Exception:
            tb = traceback.format_exc()
            self.debug_log.append(f"\n[예외]\n{tb}")
            self.error_occurred.emit(tb)
            result = None
        self.finished.emit(result)


# ──────────────────────────────────────────────────────────────────────────────
# 드래그 앤 드롭 + Ctrl+V 수신 전용 프레임
# ──────────────────────────────────────────────────────────────────────────────
class PasteFrame(QFrame):
    # (pixmap, source_name): 파일 드롭이면 파일명 stem, 클립보드면 ""
    image_received = pyqtSignal(QPixmap, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasImage() or event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet(
                "border: 3px solid #3498db; border-radius: 12px; background-color: #eaf4fb;"
            )
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._reset_style()

    def dropEvent(self, event: QDropEvent):
        self._reset_style()
        mime = event.mimeData()

        if mime.hasImage():
            image = mime.imageData()
            if not image.isNull():
                self.image_received.emit(QPixmap.fromImage(image), "")
                return

        if mime.hasUrls():
            for url in mime.urls():
                path = url.toLocalFile()
                if path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif')):
                    pixmap = QPixmap(path)
                    if not pixmap.isNull():
                        import os
                        stem = os.path.splitext(os.path.basename(path))[0].lower()
                        self.image_received.emit(pixmap, stem)
                        return

        QMessageBox.warning(self.parent(), "드롭 실패", "이미지 파일을 인식할 수 없습니다.")

    def _reset_style(self):
        self.setStyleSheet(
            "border: 3px dashed #bbbbbb; border-radius: 12px; background-color: #f8f9fa;"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 메인 다이얼로그
# ──────────────────────────────────────────────────────────────────────────────
class JeonnyonggiDialog(QDialog):
    log_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(None)   # parent=None → 완전히 독립된 창 (작업표시줄 별도 항목)
        self.setWindowTitle("전용기 결과 파싱")
        self.setMinimumSize(940, 700)
        self.setWindowFlags(Qt.Window)
        self.pasted_pixmap   = None
        self._pil_img        = None
        self._source_name    = ""     # 파일명 stem ("ex1", "tgdi" 등) 또는 "" (클립보드)
        self._ocr_worker     = None
        self._t0             = 0.0
        self._tick_step      = 0
        self._cached_pil_id  = None   # 캐시된 이미지 id()
        self._cached_result  = None   # 캐시된 추출 결과
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(400)   # 0.4s 마다 → 점 3단계 1.2s 주기
        self._elapsed_timer.timeout.connect(self._tick_elapsed)
        self._init_ui()
        self._setup_shortcuts()

    # ── 경과 시간 + 점 애니메이션 tick ────────────────────────────
    def _tick_elapsed(self):
        self._tick_step += 1
        secs = int(time.time() - self._t0)
        dots = "·" * ((self._tick_step % 3) + 1)   # ·  ··  ···  반복
        self._progress_label.setText(
            f"🔍 추출 중{dots}  ({secs}초 경과)  |  약 3~5초 소요 예상"
        )
        # 텍스트 편집창도 동기화
        self.ocr_text_edit.setPlainText(
            f"OCR 추출 중입니다{dots}\n잠시만 기다려 주세요."
        )

    # ── UI 초기화 ──────────────────────────────────────────────────
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)
        self._setup_page1()
        self._setup_page2()
        self.stack.setCurrentIndex(0)

    def _setup_shortcuts(self):
        sc = QShortcut(QKeySequence("Ctrl+V"), self)
        sc.setContext(Qt.WindowShortcut)
        sc.activated.connect(self._handle_paste)

    # ──────────────────────────────────────────────────────────────
    # 페이지 1 : 이미지 붙여넣기
    # ──────────────────────────────────────────────────────────────
    def _setup_page1(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(25, 25, 25, 20)
        layout.setSpacing(12)

        title = QLabel("📋 전용기 측정 결과 파싱")
        title.setStyleSheet("font-size: 17pt; font-weight: bold; color: #2c3e50;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        guide = QLabel(
            "① 미츠토요 프로그램에서 측정 결과 화면을 캡처합니다.\n"
            "② 위·아래 ─────── 구분선이 포함되되, 구분선 바깥 여백은 최소화하세요.\n"
            "③ 좌우는 구분선 전체가 들어오도록 충분히 넓게 캡처하세요.\n"
            "④ Ctrl+V 로 붙여넣거나, 이미지 파일을 아래 영역으로 드래그하세요."
        )
        guide.setStyleSheet(
            "background-color: #eaf4fb; padding: 14px; border-radius: 8px;"
            "font-size: 11pt; border: 1px solid #aed6f1;"
        )
        guide.setWordWrap(True)
        layout.addWidget(guide)

        self.paste_frame = PasteFrame()
        self.paste_frame.setStyleSheet(
            "border: 3px dashed #bbbbbb; border-radius: 12px; background-color: #f8f9fa;"
        )
        self.paste_frame.image_received.connect(
            lambda px, name: self._set_image(px, name)
        )
        self.paste_frame.setMinimumHeight(340)

        frame_inner = QVBoxLayout(self.paste_frame)
        frame_inner.setAlignment(Qt.AlignCenter)

        self.paste_hint = QLabel("🖼️  Ctrl+V  또는  이미지 파일을 여기에 드래그")
        self.paste_hint.setAlignment(Qt.AlignCenter)
        self.paste_hint.setStyleSheet(
            "color: #aaaaaa; font-size: 13pt; border: none; background: transparent;"
        )
        frame_inner.addWidget(self.paste_hint)

        self.paste_image_label = QLabel()
        self.paste_image_label.setAlignment(Qt.AlignCenter)
        self.paste_image_label.setStyleSheet("border: none; background: transparent;")
        self.paste_image_label.hide()
        frame_inner.addWidget(self.paste_image_label)

        layout.addWidget(self.paste_frame)

        self.paste_status = QLabel("")
        self.paste_status.setAlignment(Qt.AlignCenter)
        self.paste_status.setStyleSheet("color: #27ae60; font-weight: bold; font-size: 11pt;")
        layout.addWidget(self.paste_status)

        btn_row = QHBoxLayout()

        btn_paste_click = QPushButton("📋 붙여넣기 (Ctrl+V)")
        btn_paste_click.setFixedHeight(42)
        btn_paste_click.setStyleSheet("font-size: 10pt; padding: 0 12px;")
        btn_paste_click.clicked.connect(self._handle_paste)

        btn_load_file = QPushButton("📁 파일에서 불러오기")
        btn_load_file.setFixedHeight(42)
        btn_load_file.setStyleSheet("font-size: 10pt; padding: 0 12px;")
        btn_load_file.clicked.connect(self._load_from_file)

        btn_close = QPushButton("닫기")
        btn_close.setFixedHeight(42)
        btn_close.setFixedWidth(80)
        btn_close.clicked.connect(self.reject)

        self.btn_next = QPushButton("다음 단계로 →")
        self.btn_next.setFixedHeight(42)
        self.btn_next.setFixedWidth(160)
        self.btn_next.setEnabled(False)
        self.btn_next.setStyleSheet(
            "background-color: #bdc3c7; color: white; font-weight: bold;"
            "font-size: 11pt; border-radius: 6px;"
        )
        self.btn_next.clicked.connect(self._go_to_page2)

        btn_row.addWidget(btn_paste_click)
        btn_row.addWidget(btn_load_file)
        btn_row.addStretch()
        btn_row.addWidget(btn_close)
        btn_row.addSpacing(8)
        btn_row.addWidget(self.btn_next)
        layout.addLayout(btn_row)

        self.stack.addWidget(page)

    # ──────────────────────────────────────────────────────────────
    # 페이지 2 : 결과 확인 및 엑셀 입력
    # ──────────────────────────────────────────────────────────────
    def _setup_page2(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(25, 25, 25, 20)
        layout.setSpacing(8)

        title = QLabel("📊 결과 확인 및 엑셀 입력")
        title.setStyleSheet("font-size: 17pt; font-weight: bold; color: #2c3e50;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # 추출 진행 상태 표시 (OCR 완료 후 결과로 교체)
        self._progress_label = QLabel("🔍 추출 중... (0초 경과)  |  약 3~5초 소요 예상")
        self._progress_label.setAlignment(Qt.AlignCenter)
        self._progress_label.setStyleSheet(
            "background-color: #fff3cd; padding: 7px; border-radius: 6px;"
            "font-size: 10pt; font-weight: bold; color: #856404; border: 1px solid #ffc107;"
        )
        self._progress_label.setVisible(False)
        layout.addWidget(self._progress_label)

        content_row = QHBoxLayout()
        content_row.setSpacing(14)

        # ── 왼쪽: 이미지 스크롤 미리보기 ──────────────────────────
        img_outer = QFrame()
        img_outer.setStyleSheet(
            "QFrame { border: 1px solid #dcdde1; border-radius: 8px; background: #f8f9fa; }"
        )
        img_layout = QVBoxLayout(img_outer)
        img_layout.setContentsMargins(8, 8, 8, 8)

        lbl_img = QLabel("캡처 이미지")
        lbl_img.setStyleSheet(
            "font-weight: bold; color: #7f8c8d; border: none; background: transparent;"
        )
        img_layout.addWidget(lbl_img)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none;")
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.preview_label.setStyleSheet("border: none; background: transparent;")
        scroll.setWidget(self.preview_label)
        img_layout.addWidget(scroll)

        content_row.addWidget(img_outer, 5)

        # ── 오른쪽: OCR 결과 + 엑셀 버튼 ────────────────────────
        result_outer = QFrame()
        result_outer.setStyleSheet(
            "QFrame { border: 1px solid #dcdde1; border-radius: 8px; background: #f8f9fa; }"
        )
        result_layout = QVBoxLayout(result_outer)
        result_layout.setContentsMargins(10, 10, 10, 10)
        result_layout.setSpacing(10)

        lbl_result = QLabel("OCR 추출 결과")
        lbl_result.setStyleSheet(
            "font-weight: bold; color: #7f8c8d; border: none; background: transparent;"
        )
        result_layout.addWidget(lbl_result)

        self.ocr_text_edit = QTextEdit()
        self.ocr_text_edit.setReadOnly(True)
        self.ocr_text_edit.setPlaceholderText("이미지를 붙여넣으면 OCR 결과가 여기 표시됩니다.")
        self.ocr_text_edit.setStyleSheet(
            "background-color: #ffffff; font-family: Consolas; font-size: 9pt;"
            "border: 1px solid #dcdde1; border-radius: 4px;"
        )
        result_layout.addWidget(self.ocr_text_edit, 1)

        self.btn_excel = QPushButton("📊 엑셀에 붙여넣기")
        self.btn_excel.setFixedHeight(46)
        self.btn_excel.setStyleSheet(
            "background-color: #27ae60; color: white; font-weight: bold;"
            "font-size: 12pt; border-radius: 6px; border: none;"
        )
        self.btn_excel.clicked.connect(self._on_excel_click)
        result_layout.addWidget(self.btn_excel)

        content_row.addWidget(result_outer, 4)
        layout.addLayout(content_row)

        btn_row = QHBoxLayout()
        btn_back = QPushButton("← 이전으로")
        btn_back.setFixedHeight(40)
        btn_back.setFixedWidth(120)
        btn_back.clicked.connect(self._go_back)

        btn_new = QPushButton("🔄 다음 사진 추출하기")
        btn_new.setFixedHeight(40)
        btn_new.setStyleSheet("font-size: 10pt; padding: 0 12px;")
        btn_new.clicked.connect(self._reset_for_new_image)

        self.btn_save = QPushButton("💾 오류 보고 저장")
        self.btn_save.setFixedHeight(40)
        self.btn_save.setEnabled(False)
        self.btn_save.setStyleSheet("font-size: 10pt; padding: 0 12px;")
        self.btn_save.clicked.connect(self._on_save_report)

        btn_close = QPushButton("닫기")
        btn_close.setFixedHeight(40)
        btn_close.setFixedWidth(80)
        btn_close.clicked.connect(self.reject)

        btn_row.addWidget(btn_back)
        btn_row.addSpacing(8)
        btn_row.addWidget(btn_new)
        btn_row.addSpacing(8)
        btn_row.addWidget(self.btn_save)
        btn_row.addStretch()
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        self.stack.addWidget(page)

    # ──────────────────────────────────────────────────────────────
    # 이전으로 — 워커는 백그라운드에서 계속 실행, 완료 시 캐시에 저장
    # ──────────────────────────────────────────────────────────────
    def _go_back(self):
        self._elapsed_timer.stop()
        self._progress_label.setVisible(False)
        self.stack.setCurrentIndex(0)

    # ──────────────────────────────────────────────────────────────
    # 다음 사진 추출하기 — 페이지1 초기 상태로 완전 리셋
    # ──────────────────────────────────────────────────────────────
    def _reset_for_new_image(self):
        self._elapsed_timer.stop()
        self._pil_img       = None
        self._source_name   = ""
        self._cached_pil_id = None
        self._cached_result = None
        self.pasted_pixmap  = None
        # 페이지1 UI 초기화
        self.paste_hint.show()
        self.paste_image_label.hide()
        self.paste_image_label.clear()
        self.paste_frame.setStyleSheet(
            "border: 3px dashed #bbbbbb; border-radius: 12px; background-color: #f8f9fa;"
        )
        self.paste_status.setText("")
        self.btn_next.setEnabled(False)
        self.btn_next.setStyleSheet(
            "background-color: #bdc3c7; color: white; font-weight: bold;"
            "font-size: 11pt; border-radius: 6px;"
        )
        # 페이지2 초기화
        self._progress_label.setVisible(False)
        self.ocr_text_edit.clear()
        self.preview_label.clear()
        self.btn_save.setEnabled(False)
        self.stack.setCurrentIndex(0)

    # ──────────────────────────────────────────────────────────────
    # 클립보드 / 파일 로드
    # ──────────────────────────────────────────────────────────────
    def _handle_paste(self):
        self.log_message.emit("📋 [전용기] 클립보드 읽기 시도...")

        clipboard = QApplication.clipboard()

        mime = clipboard.mimeData()
        if mime.hasImage():
            image = mime.imageData()
            if not image.isNull():
                self.log_message.emit("✅ [전용기] Qt mimeData로 이미지 읽기 성공")
                self._set_image(QPixmap.fromImage(image), "")
                return

        image = clipboard.image()
        if not image.isNull():
            self.log_message.emit("✅ [전용기] Qt image()로 이미지 읽기 성공")
            self._set_image(QPixmap.fromImage(image), "")
            return

        try:
            from PIL import ImageGrab, Image as PilImage
            pil_img = ImageGrab.grabclipboard()
            if isinstance(pil_img, list):
                for item in pil_img:
                    if isinstance(item, str) and item.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp')):
                        try:
                            pil_img = PilImage.open(item)
                            break
                        except Exception:
                            pass
                else:
                    pil_img = None
            if pil_img is not None:
                buf = io.BytesIO()
                pil_img.convert("RGBA").save(buf, format="PNG")
                qimage = QImage()
                qimage.loadFromData(buf.getvalue())
                if not qimage.isNull():
                    self.log_message.emit("✅ [전용기] Pillow ImageGrab으로 이미지 읽기 성공")
                    self._set_image(QPixmap.fromImage(qimage), "")
                    return
                else:
                    self.log_message.emit("⚠️ [전용기] Pillow로 읽었지만 QImage 변환 실패")
            else:
                self.log_message.emit("⚠️ [전용기] Pillow: 클립보드에 이미지 없음 (None)")
        except Exception as e:
            self.log_message.emit(f"❌ [전용기] Pillow 오류: {e}")

        self.log_message.emit("❌ [전용기] 클립보드에서 이미지를 가져오지 못했습니다.")
        QMessageBox.warning(
            self, "붙여넣기 실패",
            "클립보드에서 이미지를 읽지 못했습니다.\n\n"
            "• 캡처 도구로 스크린샷을 찍은 직후 시도해 주세요.\n"
            "• 또는 '파일에서 불러오기'로 저장된 이미지를 선택하세요."
        )

    def _load_from_file(self):
        try:
            from PyQt5.QtWidgets import QFileDialog
            path, _ = QFileDialog.getOpenFileName(
                self, "이미지 파일 선택", "",
                "이미지 파일 (*.png *.jpg *.jpeg *.bmp)"
            )
            if path:
                pixmap = QPixmap(path)
                if pixmap.isNull():
                    QMessageBox.warning(self, "오류", "이미지를 불러올 수 없습니다.")
                    return
                import os
                stem = os.path.splitext(os.path.basename(path))[0].lower()
                self.log_message.emit(f"📁 [전용기] 파일 로드: {path}")
                self._set_image(pixmap, stem)
        except Exception as e:
            self.log_message.emit(f"❌ [전용기] 파일 로드 오류: {e}")

    # ──────────────────────────────────────────────────────────────
    # 이미지 반영 (페이지1 미리보기만, OCR 미실행)
    # ──────────────────────────────────────────────────────────────
    def _set_image(self, pixmap: QPixmap, source_name: str = ""):
        # 새 이미지가 들어오면 캐시 무효화
        self._cached_pil_id = None
        self._cached_result = None
        self.pasted_pixmap  = pixmap
        self._source_name   = source_name
        w, h = pixmap.width(), pixmap.height()
        self.log_message.emit(
            f"🖼️ [전용기] 이미지 수신: {w}×{h}px"
            + (f"  [{source_name}]" if source_name else "  [클립보드]")
        )

        # QPixmap → PIL (bytesPerLine 사용 — Qt RGB888 행 패딩 대응)
        qimage = pixmap.toImage().convertToFormat(QImage.Format_RGB888)
        w_px, h_px = qimage.width(), qimage.height()
        bpl = qimage.bytesPerLine()
        ptr = qimage.bits()
        ptr.setsize(bpl * h_px)
        arr = (np.frombuffer(ptr, dtype=np.uint8)
               .reshape((h_px, bpl))[:, :w_px * 3]
               .reshape((h_px, w_px, 3))
               .copy())
        from PIL import Image
        self._pil_img = Image.fromarray(arr)

        # 페이지1 미리보기 업데이트
        self.paste_hint.hide()
        max_w = self.paste_frame.width() - 24
        scaled = pixmap.scaledToWidth(max_w, Qt.SmoothTransformation)
        if scaled.height() > 300:
            scaled = pixmap.scaledToHeight(300, Qt.SmoothTransformation)
        self.paste_image_label.setPixmap(scaled)
        self.paste_image_label.show()
        self.paste_frame.setStyleSheet(
            "border: 3px solid #27ae60; border-radius: 12px; background-color: #f0fff4;"
        )
        self.paste_status.setText("✅ 이미지 준비 완료. '다음 단계로 →' 를 눌러 추출을 시작하세요.")
        self.paste_status.setStyleSheet("color: #27ae60; font-weight: bold; font-size: 11pt;")

        # 다음 버튼 활성화
        self.btn_next.setEnabled(True)
        self.btn_next.setStyleSheet(
            "background-color: #2980b9; color: white; font-weight: bold;"
            "font-size: 11pt; border-radius: 6px;"
        )

        # 페이지2 미리보기 갱신
        self.preview_label.setPixmap(
            pixmap.scaledToWidth(430, Qt.SmoothTransformation)
        )

    # ──────────────────────────────────────────────────────────────
    # 페이지2 전환 → OCR 시작
    # ──────────────────────────────────────────────────────────────
    def _go_to_page2(self):
        if self._pil_img is None:
            return
        self.stack.setCurrentIndex(1)

        # 동일 이미지 캐시 히트 — 재추출 없이 즉시 표시
        if (self._cached_pil_id == id(self._pil_img)
                and self._cached_result is not None):
            self._progress_label.setText("✅ 이전 추출 결과")
            self._progress_label.setStyleSheet(
                "background-color: #d4edda; padding: 7px; border-radius: 6px;"
                "font-size: 10pt; font-weight: bold; color: #155724; border: 1px solid #c3e6cb;"
            )
            self._progress_label.setVisible(True)
            self._display_result(self._cached_result)
            self.log_message.emit("✅ [전용기] 캐시된 결과 표시")
            return

        # 이전에 시작한 워커가 아직 실행 중 — 타이머만 재개하고 기다림
        if self._ocr_worker and self._ocr_worker.isRunning():
            self._elapsed_timer.start()
            self.log_message.emit("➡️ [전용기] 추출 중 (재개 대기)")
            return

        self.log_message.emit("➡️ [전용기] 결과 확인 페이지로 이동, OCR 시작")
        self._start_ocr()

    def _start_ocr(self):
        self._t0         = time.time()
        self._tick_step  = 0
        self._progress_label.setText("🔍 추출 중·  (0초 경과)  |  약 3~5초 소요 예상")
        self._progress_label.setStyleSheet(
            "background-color: #fff3cd; padding: 7px; border-radius: 6px;"
            "font-size: 10pt; font-weight: bold; color: #856404; border: 1px solid #ffc107;"
        )
        self._progress_label.setVisible(True)
        self.ocr_text_edit.setPlainText("OCR 추출 중입니다·\n잠시만 기다려 주세요.")

        self._elapsed_timer.start()

        self._ocr_worker = OcrWorker(self._pil_img)
        self._ocr_worker.finished.connect(self._on_ocr_done)
        self._ocr_worker.error_occurred.connect(self._on_ocr_error)
        self._ocr_worker.start()

    # ──────────────────────────────────────────────────────────────
    # OCR 예외 로그 (메인 창 로그창으로 전달)
    # ──────────────────────────────────────────────────────────────
    def _on_ocr_error(self, tb: str):
        for line in tb.strip().splitlines():
            self.log_message.emit(f"❌ [OCR 오류] {line}")

    # ──────────────────────────────────────────────────────────────
    # OCR 완료 콜백
    # ──────────────────────────────────────────────────────────────
    def _on_ocr_done(self, result):
        elapsed = time.time() - self._t0
        self._elapsed_timer.stop()

        # 항상 캐시에 저장 (페이지1에 있어도 다음에 바로 쓸 수 있도록)
        self._cached_pil_id = id(self._pil_img)
        self._cached_result = result
        self.btn_save.setEnabled(True)

        # OCR 진단 로그 자동 저장 (결과 성공·실패 무관)
        self._save_ocr_diag_log(result, elapsed)

        self.log_message.emit(
            f"✅ [전용기] OCR 완료 ({elapsed:.1f}s) — "
            + (f"{result['format_name']}" if result else "포맷 인식 실패")
        )

        # 페이지2에 있을 때만 UI 업데이트
        if self.stack.currentIndex() != 1:
            return

        self._progress_label.setText(f"✅ 추출 완료  ({elapsed:.1f}초 소요)")
        self._progress_label.setStyleSheet(
            "background-color: #d4edda; padding: 7px; border-radius: 6px;"
            "font-size: 10pt; font-weight: bold; color: #155724; border: 1px solid #c3e6cb;"
        )
        self._display_result(result)

    def _save_ocr_diag_log(self, result, elapsed):
        """OCR 진단 로그를 ocr_reports 폴더에 .txt 파일로 저장."""
        try:
            import sys, os
            from datetime import datetime
            # 이미 존재하는 config/{PC이름}/ 재사용 — 새 최상위 폴더 미생성
            from config.settings import CONFIG_DIR
            save_dir = CONFIG_DIR
            os.makedirs(save_dir, exist_ok=True)
            ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(save_dir, f"ocr_diag_{ts}.txt")

            lines = []
            if self._ocr_worker and self._ocr_worker.debug_log:
                lines.extend(self._ocr_worker.debug_log)
            lines.append(f"\n=== 총 소요 시간: {elapsed:.2f}초 ===")
            if result:
                lines.append(f"format_key: {result.get('format_key')}")
                found = sum(1 for it in result.get('items', []) if it['value'] is not None)
                lines.append(f"추출: {found}/{len(result.get('items', []))}")
            else:
                lines.append("format_key: null  ← 포맷 감지 실패")

            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            self.log_message.emit(f"📋 [전용기] OCR 진단 로그 저장: {os.path.basename(path)}")
        except Exception as e:
            self.log_message.emit(f"⚠️ [전용기] 로그 저장 실패: {e}")

    # ──────────────────────────────────────────────────────────────
    # 결과 표시
    # ──────────────────────────────────────────────────────────────
    def _display_result(self, result):
        if result is None:
            self.ocr_text_edit.setPlainText(
                "포맷을 인식할 수 없습니다.\n\n"
                "• Short 포맷: 행번호 00163~00178 이 이미지에 포함됐는지 확인하세요.\n"
                "• TGDI 포맷: 행번호 00093~00107 이 이미지에 포함됐는지 확인하세요.\n"
                "• 위·아래 ─── 구분선이 포함되되, 구분선 바깥 여백은 최소화하세요."
            )
            return

        items     = result["items"]
        found_cnt = sum(1 for e in items if e["value"] is not None)
        total     = len(items)
        fmt_name  = result["format_name"]

        # ── 헤더 ──────────────────────────────────────────────────
        lines = [
            f"부품 이름:  {fmt_name}",
            f"추출 결과:  {found_cnt}/{total}개"
            + (f"   (파일: {self._source_name})" if self._source_name else ""),
            "",
        ]

        # ── 항목/값 표 ────────────────────────────────────────────
        col_w = max(_display_width(it["label"]) for it in items)
        SEP = "─" * (col_w + 14)
        lines += [
            f"  {_ljust_display('항목', col_w)}│{'값':>12}",
            f"  {SEP}",
        ]
        for item in items:
            vs = f"{item['value']:>12.3f}" if item["value"] is not None else f"{'?':>12}"
            lines.append(f"  {_ljust_display(item['label'], col_w)}│{vs}")
        lines.append(f"  {SEP}")

        # ── GT 비교 (개발용) ──────────────────────────────────────
        gt_vals = _GT_BY_FILE.get(self._source_name)
        vals    = [it["value"] for it in items]
        if gt_vals:
            ok_list = [
                i < len(vals)
                and vals[i] is not None
                and round(vals[i], 3) == round(gt, 3)
                for i, gt in enumerate(gt_vals)
            ]
            ok  = sum(ok_list)
            tot = len(gt_vals)
            SEP2 = "─" * (col_w + 26)
            lines += [
                "",
                f"[개발용 GT 비교]  {self._source_name}  →  {ok}/{tot} 정확 일치",
                f"  {_ljust_display('항목', col_w)}│{'추출값':>10}│{'GT':>10}│결과",
                f"  {SEP2}",
            ]
            for i, (item, gt) in enumerate(zip(items, gt_vals)):
                vs   = f"{item['value']:>10.3f}" if item["value"] is not None else f"{'?':>10}"
                gts  = f"{gt:>10.3f}"
                flag = "OK" if ok_list[i] else ("NG" if item["value"] is not None else "──")
                lines.append(f"  {_ljust_display(item['label'], col_w)}│{vs}│{gts}│{flag}")
            lines.append(f"  {SEP2}")
        elif self._source_name:
            lines += ["", f"[개발용 GT 비교]  '{self._source_name}' 에 해당하는 GT 없음"]

        self.extracted_data = items
        self.ocr_text_edit.setPlainText("\n".join(lines))

    def _build_excel_row(self, result) -> str:
        """엑셀 붙여넣기용 탭 구분 행 생성.
        공통 14열: 위치X, 홀거리, 좌측홀Y, 우측홀Y, 위치도,
                   슬롯거리, 슬롯간격, 슬롯폭min, 슬롯폭max, 슬롯폭평균,
                   대칭도, 상단거리, 하단거리, 각도(TGDI 제외)
        """
        fmt_key = result.get("format_key", "")
        items   = result["items"]
        v = {it["label"]: it["value"] for it in items}

        slots = [v.get("1번슬롯"), v.get("2번슬롯"), v.get("3번슬롯"), v.get("4번슬롯")]
        slots_valid = [s for s in slots if s is not None]
        slot_min = min(slots_valid) if slots_valid else None
        slot_max = max(slots_valid) if slots_valid else None

        cols = [
            v.get("위치X"),
            v.get("홀거리"),
            v.get("좌측홀Y"),
            v.get("우측홀Y"),
            v.get("위치도"),
            v.get("슬롯거리"),
            v.get("슬롯간격"),
            slot_min,
            slot_max,
            v.get("평균거리"),
            v.get("대칭도"),
            v.get("상단거리"),
            v.get("하단거리"),
        ]
        if fmt_key != "tgdi":
            cols.append(v.get("YZ각도"))

        return "\t".join(f"{c:.3f}" if c is not None else "" for c in cols)

    def _on_excel_click(self):
        if self._ocr_worker and self._ocr_worker.isRunning():
            self.log_message.emit("⚠️ [전용기] 엑셀 버튼 — OCR 추출 중, 대기 필요")
            QMessageBox.information(
                self, "잠시만 기다려주세요",
                "사진에서 추출이 완료될 때까지\n잠시만 기다려주세요."
            )
            return

        result = self._cached_result
        if result is None:
            QMessageBox.warning(self, "추출 결과 없음", "먼저 OCR 추출을 완료해주세요.")
            return

        row_text = self._build_excel_row(result)
        QApplication.clipboard().setText(row_text)
        self.log_message.emit(f"✅ [전용기] 엑셀 행 복사 완료: {row_text}")

        self.btn_excel.setText("✅ 복사 완료!")
        self.btn_excel.setEnabled(False)
        self.btn_excel.setStyleSheet(
            "background-color: #2ecc71; color: white; font-weight: bold;"
            "font-size: 12pt; border-radius: 6px; border: none;"
        )
        QTimer.singleShot(800, self._reset_excel_btn)

    def _reset_excel_btn(self):
        self.btn_excel.setText("📊 엑셀에 붙여넣기")
        self.btn_excel.setEnabled(True)
        self.btn_excel.setStyleSheet(
            "background-color: #27ae60; color: white; font-weight: bold;"
            "font-size: 12pt; border-radius: 6px; border: none;"
        )

    # ──────────────────────────────────────────────────────────────
    # 오류 보고용 이미지 + JSON 저장
    # ──────────────────────────────────────────────────────────────
    def _on_save_report(self):
        """현재 이미지와 OCR 파싱 결과를 자동 저장 (오류 보고 / 나중에 재분석용)."""
        import json
        import os
        from datetime import datetime

        if self._pil_img is None:
            return

        # 이미 존재하는 config/{PC이름}/ 재사용 — 새 최상위 폴더 미생성
        from config.settings import CONFIG_DIR
        save_dir = CONFIG_DIR
        os.makedirs(save_dir, exist_ok=True)

        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = os.path.join(save_dir, f"ocr_report_{ts}")

        # 1) 원본 이미지 저장
        self._pil_img.save(base + ".png")

        # 2) 파싱 결과 JSON 저장
        result = self._cached_result
        report = {
            "timestamp":   ts,
            "source":      self._source_name if self._source_name else "(클립보드)",
            "format_key":  result.get("format_key")  if result else None,
            "format_name": result.get("format_name") if result else None,
            "row_count":   result.get("row_count")   if result else None,
            "di_count":    result.get("di_count")    if result else None,
            "items": [
                {
                    "label": it["label"],
                    "value": it["value"],
                    "raw":   it["raw"],
                    "score": round(float(it["score"]), 4),
                }
                for it in result["items"]
            ] if result else [],
        }
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        self.log_message.emit(f"💾 [전용기] 보고 저장 완료: {base}")
        QMessageBox.information(self, "저장 완료", "저장되었습니다.")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            return  # 실수 종료 방지
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if self.stack.currentIndex() == 0 and self.btn_next.isEnabled():
                self._go_to_page2()
                return
        super().keyPressEvent(event)
