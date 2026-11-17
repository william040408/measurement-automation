"""
새 부품 추가 / 기존 부품 수정 마법사

페이지 0  부품명 설정 + 기존 부품 불러오기 + PDF 파싱
페이지 1  파트 타입 + Data Range 설정 (멀티파트 지원)
페이지 2  영문 부품 ID + 서브폴더 + Excel 매핑 → 저장
"""

import json
import os
import sys as _sys

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QStackedWidget, QLineEdit,
    QSpinBox, QDoubleSpinBox, QComboBox, QMessageBox, QFileDialog,
    QGroupBox, QFrame, QCheckBox, QTextEdit, QApplication, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal, QMimeData
from PyQt5.QtGui import QDrag

from config.settings import REGISTRY_PATH

# special_checks.json 경로 (config 폴더 — exe 옆 또는 소스 루트)
if getattr(_sys, 'frozen', False):
    _CHECKS_BASE = os.path.dirname(_sys.executable)
else:
    _CHECKS_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPECIAL_CHECKS_PATH = os.path.join(_CHECKS_BASE, "config", "special_checks.json")


# ─────────────────────────────────────────────
# 전역 유틸
# ─────────────────────────────────────────────

def _compress_indices(indices: list) -> list:
    """[0,1,2,4,5,8] → ["0-2","4-5","8"]"""
    if not indices:
        return []
    indices = sorted(set(indices))
    result, start, prev = [], indices[0], indices[0]
    for i in indices[1:]:
        if i == prev + 1:
            prev = i
        else:
            result.append(f"{start}-{prev}" if start != prev else str(start))
            start = prev = i
    result.append(f"{start}-{prev}" if start != prev else str(start))
    return result


def _expand_ranges(range_list: list) -> list:
    """["0-2","4","8"] → [0,1,2,4,8]"""
    from modules.messenger import parse_custom_indices
    if not isinstance(range_list, list):
        range_list = [range_list]
    return parse_custom_indices(range_list)


def _parse_pdf_items(pdf_path: str) -> list:
    """PDF 파싱 → 이름 목록 반환 (SectionMarker 제외)"""
    from PyPDF2 import PdfReader
    from core.parser import parse_measurements
    from core.models import SectionMarker
    reader = PdfReader(pdf_path)
    full_text = "".join(p.extract_text() + "\n" for p in reader.pages)
    raw = parse_measurements(full_text, debug=False)
    return [getattr(m, 'name', str(m)) for m in raw if not isinstance(m, SectionMarker)]


# ─────────────────────────────────────────────
# 드래그 지원 위젯
# ─────────────────────────────────────────────

class _DragHandle(QLabel):
    """⠿ 핸들 — 누른 채 이동하면 행 드래그 시작"""
    def __init__(self, row_ref, parent=None):
        super().__init__("⠿", parent)
        self._row_ref = row_ref
        self._drag_start = None
        self.setStyleSheet(
            "color:#74b9ff; font-size:15pt; font-weight:bold;"
            " padding:0 4px; background:transparent;"
        )
        self.setFixedWidth(28)
        self.setCursor(Qt.SizeVerCursor)
        self.setToolTip("드래그하여 순서 변경")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.pos()

    def mouseMoveEvent(self, event):
        if self._drag_start is None:
            return
        if (event.pos() - self._drag_start).manhattanLength() < 4:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(str(id(self._row_ref)))
        drag.setMimeData(mime)
        self._drag_start = None
        drag.exec_(Qt.MoveAction)


class _DragRowWidget(QWidget):
    """드롭을 받아 행 순서를 바꾸는 컨테이너"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._drop_cb = None
        self.setAcceptDrops(True)

    def set_drop_cb(self, cb):
        self._drop_cb = cb

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            self.setStyleSheet("border:2px dashed #74b9ff; border-radius:3px;")
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setStyleSheet("")

    def dragMoveEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.setStyleSheet("")
        if event.mimeData().hasText() and self._drop_cb:
            try:
                self._drop_cb(int(event.mimeData().text()))
            except (ValueError, TypeError):
                pass
            event.acceptProposedAction()


# ─────────────────────────────────────────────
# Excel 매핑 행 위젯
# ─────────────────────────────────────────────

class _MappingRow:
    """Excel 매핑 한 행 — 단일 값 / MAX / MIN / 고정값(Fixed) 지원"""

    def __init__(self, row_num: int, part_items: list, del_cb):
        """
        part_items: list[(pdf_idx, item_name)]
        """
        self.part_items = part_items

        self.container = _DragRowWidget()
        root_lay = QVBoxLayout(self.container)
        root_lay.setContentsMargins(2, 4, 2, 0)
        root_lay.setSpacing(2)

        # ── 상단 제어줄 ──────────────────────────
        top = QHBoxLayout()

        self._drag_handle = _DragHandle(self)

        self._num_lbl = QLabel(f"  {row_num}행")
        self._num_lbl.setFixedWidth(40)
        self._num_lbl.setStyleSheet("color:#7f8c8d; font-family:Consolas; font-weight:bold;")

        self._type_combo = QComboBox()
        self._type_combo.addItems(["단일 값", "MAX (최대)", "MIN (최소)", "고정값 (Fixed)"])
        self._type_combo.setFixedWidth(155)
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)

        btn_del = QPushButton("✕")
        btn_del.setFixedSize(26, 26)
        btn_del.setStyleSheet("background-color:#e74c3c; color:white; border-radius:4px;")
        btn_del.clicked.connect(del_cb)

        self._btn_up = QPushButton("▲")
        self._btn_up.setFixedSize(24, 22)
        self._btn_up.setStyleSheet(
            "background:#74b9ff; color:white; border-radius:3px;"
            " font-size:8pt; font-weight:bold;"
        )
        self._btn_up.setToolTip("위로 이동")

        self._btn_down = QPushButton("▼")
        self._btn_down.setFixedSize(24, 22)
        self._btn_down.setStyleSheet(
            "background:#74b9ff; color:white; border-radius:3px;"
            " font-size:8pt; font-weight:bold;"
        )
        self._btn_down.setToolTip("아래로 이동")

        top.addWidget(self._drag_handle)
        top.addWidget(self._num_lbl)
        top.addWidget(self._btn_up)
        top.addWidget(self._btn_down)
        top.addSpacing(4)
        top.addWidget(self._type_combo)
        top.addStretch()
        top.addWidget(btn_del)
        root_lay.addLayout(top)

        # ── 항목 선택 영역 ────────────────────────
        item_area = QWidget()
        item_lay = QHBoxLayout(item_area)
        item_lay.setContentsMargins(45, 0, 0, 4)
        item_lay.setSpacing(6)

        # 단일 값: 드롭다운
        self._single_combo = QComboBox()
        self._single_combo.setMinimumWidth(400)
        for pdf_idx, name in part_items:
            self._single_combo.addItem(f"No.{pdf_idx:02d}  {name}", userData=pdf_idx)
        item_lay.addWidget(self._single_combo)

        # MAX/MIN: 체크박스 묶음
        self._check_frame = QFrame()
        self._check_frame.setStyleSheet("QFrame { background-color:#f0f4f8; border-radius:4px; }")
        check_lay = QHBoxLayout(self._check_frame)
        check_lay.setContentsMargins(6, 2, 6, 2)
        check_lay.setSpacing(8)
        self._checkboxes: list = []  # list[(pdf_idx, QCheckBox)]
        for pdf_idx, name in part_items:
            cb = QCheckBox(f"No.{pdf_idx:02d}")
            cb.setToolTip(name)
            self._checkboxes.append((pdf_idx, cb))
            check_lay.addWidget(cb)
        check_lay.addStretch()
        self._check_frame.setVisible(False)
        item_lay.addWidget(self._check_frame, 1)

        # 고정값 (Fixed): 텍스트 입력
        self._fixed_edit = QLineEdit()
        self._fixed_edit.setPlaceholderText("고정 상수값 입력  (예: 0, 1, OK, 완료)")
        self._fixed_edit.setMinimumWidth(300)
        self._fixed_edit.setVisible(False)
        item_lay.addWidget(self._fixed_edit)

        item_lay.addStretch()
        root_lay.addWidget(item_area)

        # 구분선 — 가시적인 1px 선
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: #b2bec3;")
        root_lay.addWidget(sep)

    # ── 내부 이벤트 ───────────────────────────────
    def _on_type_changed(self, idx):
        self._single_combo.setVisible(idx == 0)
        self._check_frame.setVisible(idx in (1, 2))
        self._fixed_edit.setVisible(idx == 3)

    # ── 공개 인터페이스 ───────────────────────────
    def update_num(self, n: int):
        self._num_lbl.setText(f"  {n}행")

    def get_data(self) -> dict:
        """{"row_idx":n, "source_type":str, "value_source":int|list|str}"""
        t = self._type_combo.currentIndex()
        if t == 0:
            return {"source_type": "pdf_idx", "value_source": self._single_combo.currentData()}
        elif t in (1, 2):
            sel = [pid for pid, cb in self._checkboxes if cb.isChecked()]
            return {"source_type": "max" if t == 1 else "min", "value_source": sel}
        else:
            return {"source_type": "fixed", "value_source": self._fixed_edit.text()}

    def set_data(self, mapping_dict: dict):
        """기존 JSON 매핑 데이터로 초기화"""
        st = mapping_dict.get("source_type", "pdf_idx")
        vs = mapping_dict.get("value_source")
        if st == "pdf_idx":
            self._type_combo.setCurrentIndex(0)
            for i in range(self._single_combo.count()):
                if self._single_combo.itemData(i) == vs:
                    self._single_combo.setCurrentIndex(i)
                    break
        elif st in ("max", "min"):
            self._type_combo.setCurrentIndex(1 if st == "max" else 2)
            indices = vs if isinstance(vs, list) else ([vs] if vs is not None else [])
            for pid, cb in self._checkboxes:
                cb.setChecked(pid in indices)
        elif st == "fixed":
            self._type_combo.setCurrentIndex(3)
            self._fixed_edit.setText(str(vs) if vs is not None else "")


# ─────────────────────────────────────────────
# 특이사항 체크 행 위젯
# ─────────────────────────────────────────────

class _CheckRow:
    """특이사항 체크 한 건 — 현재 지원 타입: deviation (편차)"""

    _TYPE_NAMES = ["편차 체크 (두 항목의 차이)"]

    def __init__(self, all_items: list, del_cb, dirty_cb):
        """
        all_items: list of (pdf_idx, name) — 파싱된 전체 항목
        """
        self._all_items = all_items
        self._dirty_cb  = dirty_cb

        self.container = QFrame()
        self.container.setStyleSheet(
            "QFrame { background-color:#fafbfc; border:1px solid #dfe6e9; border-radius:7px; }"
        )
        root = QVBoxLayout(self.container)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(7)

        # ── 행 1: 레이블 + 삭제 버튼 ──────────────────
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("레이블:"))
        self._label_edit = QLineEdit()
        self._label_edit.setPlaceholderText("예) 기준원 편차 확인")
        self._label_edit.setMinimumWidth(260)
        self._label_edit.textChanged.connect(dirty_cb)
        r1.addWidget(self._label_edit, 1)

        btn_del = QPushButton("✕ 삭제")
        btn_del.setFixedSize(64, 28)
        btn_del.setStyleSheet("background-color:#e74c3c; color:white; border-radius:4px; font-weight:bold;")
        btn_del.clicked.connect(del_cb)
        r1.addWidget(btn_del)
        root.addLayout(r1)

        # ── 행 2: 유형 + 파트카드 번호 ────────────────
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("유형:"))
        self._type_combo = QComboBox()
        self._type_combo.addItems(self._TYPE_NAMES)
        self._type_combo.setFixedWidth(220)
        self._type_combo.currentIndexChanged.connect(dirty_cb)
        r2.addWidget(self._type_combo)

        r2.addSpacing(20)
        r2.addWidget(QLabel("알림 표시할 호기 카드 번호 (0부터):"))
        self._part_idx_spin = QSpinBox()
        self._part_idx_spin.setRange(0, 9)
        self._part_idx_spin.setFixedWidth(55)
        self._part_idx_spin.setToolTip("0 = 첫 번째 호기 카드")
        self._part_idx_spin.valueChanged.connect(dirty_cb)
        r2.addWidget(self._part_idx_spin)
        r2.addStretch()
        root.addLayout(r2)

        # ── 행 3: 항목 A / B 선택 ─────────────────────
        r3 = QHBoxLayout()
        r3.addWidget(QLabel("항목 A:"))
        self._idx_a_combo = QComboBox()
        self._idx_a_combo.setMinimumWidth(340)
        r3.addWidget(self._idx_a_combo)

        r3.addSpacing(12)
        r3.addWidget(QLabel("항목 B:"))
        self._idx_b_combo = QComboBox()
        self._idx_b_combo.setMinimumWidth(340)
        r3.addWidget(self._idx_b_combo)
        r3.addStretch()

        for pdf_idx, name in all_items:
            label = f"No.{pdf_idx:02d}  {name}"
            self._idx_a_combo.addItem(label, userData=pdf_idx)
            self._idx_b_combo.addItem(label, userData=pdf_idx)

        self._idx_a_combo.currentIndexChanged.connect(dirty_cb)
        self._idx_b_combo.currentIndexChanged.connect(dirty_cb)
        root.addLayout(r3)

        # ── 행 4: 임계값 ──────────────────────────────
        r4 = QHBoxLayout()
        r4.addWidget(QLabel("편차 임계값:"))
        self._threshold_spin = QDoubleSpinBox()
        self._threshold_spin.setRange(0.1, 9999.0)
        self._threshold_spin.setDecimals(1)
        self._threshold_spin.setSingleStep(0.5)
        self._threshold_spin.setValue(4.0)
        self._threshold_spin.setFixedWidth(90)
        self._threshold_spin.valueChanged.connect(dirty_cb)
        r4.addWidget(self._threshold_spin)
        r4.addWidget(QLabel("μm  이상이면 알림 표시"))
        r4.addStretch()
        root.addLayout(r4)

        # ── 행 5: 알림 메시지 ──────────────────────────
        r5 = QHBoxLayout()
        r5.addWidget(QLabel("알림 메시지:"))
        self._msg_edit = QLineEdit()
        self._msg_edit.setPlaceholderText("작업자에게 표시할 메시지 (\\n으로 줄바꿈)")
        self._msg_edit.textChanged.connect(dirty_cb)
        r5.addWidget(self._msg_edit, 1)
        root.addLayout(r5)

    # ── 공개 인터페이스 ────────────────────────────
    def get_data(self) -> dict:
        return {
            "id": self._label_edit.text().strip().replace(" ", "_") or "check",
            "type": "deviation",
            "label": self._label_edit.text().strip(),
            "part_idx": self._part_idx_spin.value(),
            "index_a": self._idx_a_combo.currentData(),
            "index_b": self._idx_b_combo.currentData(),
            "label_a": self._idx_a_combo.currentText().split("  ", 1)[-1],
            "label_b": self._idx_b_combo.currentText().split("  ", 1)[-1],
            "threshold": round(self._threshold_spin.value() / 1000.0, 6),
            "alert_message": self._msg_edit.text().replace("\\n", "\n"),
        }

    def set_data(self, d: dict):
        self._label_edit.setText(d.get("label", ""))
        self._part_idx_spin.setValue(d.get("part_idx", 0))

        idx_a = d.get("index_a", -1)
        idx_b = d.get("index_b", -1)
        for combo, target in ((self._idx_a_combo, idx_a), (self._idx_b_combo, idx_b)):
            for i in range(combo.count()):
                if combo.itemData(i) == target:
                    combo.setCurrentIndex(i)
                    break

        thr_mm = d.get("threshold", 0.004)
        self._threshold_spin.setValue(round(float(thr_mm) * 1000.0, 1))
        self._msg_edit.setText(d.get("alert_message", "").replace("\n", "\\n"))


# ─────────────────────────────────────────────
# 마법사 다이얼로그
# ─────────────────────────────────────────────

class PartWizardDialog(QDialog):
    part_saved = pyqtSignal(str, str)   # (registry_key, display_name)

    _GS = """
        QGroupBox { font-weight:bold; font-size:10pt; border:2px solid #dcdde1;
                    border-radius:8px; margin-top:18px; padding-top:12px; }
        QGroupBox::title { subcontrol-origin:margin; subcontrol-position:top left;
                           left:12px; padding:0 4px; color:#2980b9; }
    """

    def __init__(self, parent=None, edit_key: str = ""):
        super().__init__(parent)
        self.setWindowTitle("➕ 부품 추가 / 수정 마법사")
        self.setMinimumSize(900, 720)
        self.setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.WindowSystemMenuHint
                            | Qt.WindowMinMaxButtonsHint)
        self._pending_edit_key = edit_key or ""
        self._init_state()
        self._load_registry()
        self._init_ui()

        if self._pending_edit_key:
            self._load_for_edit(self._pending_edit_key)
        else:
            self._go_to(0)

    # ── 상태 초기화 ───────────────────────────────
    def _init_state(self):
        self.parsed_items: list = []
        self.num_parts: int = 1
        self.item_combos: list = []          # 항목당 QComboBox (파트 배정)
        self._item_checkboxes: list = []     # 항목당 QCheckBox (일괄 배정용)
        self._existing_entry: dict = {}
        self._existing_excel: list = []
        self._edit_key: str = ""             # 수정 중인 키 (빈 문자열 = 새 부품)
        self._dirty: bool = False            # 실제 변경 여부 추적
        self._excel_block_names: list = []   # list[QLineEdit]
        self._mapping_rows: list = []        # list[list[_MappingRow]]
        self._mapping_scrolls: list = []     # list[QScrollArea] — 파트별 매핑 행 스크롤
        self._part_item_lists: list = []     # list[list[(pdf_idx,name)]]
        self._check_rows: list = []          # list[_CheckRow]
        self._check_rows_layout = None       # QVBoxLayout for check rows

    def _set_dirty(self, *_):
        self._dirty = True

    def _load_registry(self):
        try:
            with open(REGISTRY_PATH, 'r', encoding='utf-8') as f:
                self._registry = json.load(f)
        except Exception:
            self._registry = {}

    def _load_for_edit(self, key: str):
        """수정 모드: 기존 부품 데이터를 바탕으로 1단계(Data Range)부터 시작."""
        entry = self._registry.get(key, {})
        if not entry:
            QMessageBox.warning(self, "오류", f"부품 키 '{key}'를 찾을 수 없습니다.")
            self._go_to(0)
            return

        # 상태 세팅
        self._edit_key = key
        self._existing_entry = entry
        self._existing_excel = entry.get("excel_mapping", [])
        self.parsed_items = list(entry.get("signature", []))

        # 페이지 0 위젯에 기존값 채우기 (페이지 건너뛰어도 저장 시 사용)
        self._name_edit.setText(entry.get("name", ""))

        # 기존 부품 콤보에도 표시 (신호 차단하여 재진입 방지)
        for i in range(self._existing_combo.count()):
            if self._existing_combo.itemData(i) == key:
                self._existing_combo.blockSignals(True)
                self._existing_combo.setCurrentIndex(i)
                self._existing_combo.blockSignals(False)
                break

        # 타이틀 업데이트
        self._step_lbl.setText(
            f"수정 모드  |  {entry.get('name', key)}  —  2단계: 파트 타입 및 Data Range 확인"
        )

        # 페이지 1 재구성 후 바로 이동 (PDF 파싱 단계 건너뜀)
        self._rebuild_page1_items()
        self._dirty = False   # 로드 과정에서 발생한 signal로 dirty가 오설정되는 것 방지
        self.stack.setCurrentIndex(1)

    # ── UI 틀 ─────────────────────────────────────
    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._step_lbl = QLabel()
        self._step_lbl.setAlignment(Qt.AlignCenter)
        self._step_lbl.setStyleSheet(
            "background-color:#2980b9; color:white; font-size:12pt; font-weight:bold; padding:10px;"
        )
        root.addWidget(self._step_lbl)

        self.stack = QStackedWidget()
        root.addWidget(self.stack)

        self._build_page0()
        self._build_page1()
        self._build_page2()

    def _go_to(self, idx: int):
        mode_prefix = f"[수정] {self._existing_entry.get('name', '')}  —  " if self._edit_key else ""
        titles = [
            "1단계  —  부품명 설정 및 PDF 파싱",
            "2단계  —  파트 타입 및 Data Range 설정",
            "3단계  —  Excel 매핑 및 저장",
        ]
        self._step_lbl.setText(f"{mode_prefix}Step {idx+1}/3  |  {titles[idx]}")
        self.stack.setCurrentIndex(idx)

    def _nav(self, quit_fn=None, prev_fn=None, next_fn=None, next_label="다음 ▶"):
        """하단 내비게이션 행 반환"""
        row = QHBoxLayout()

        btn_q = QPushButton("❌ 종료")
        btn_q.setFixedHeight(38)
        btn_q.setStyleSheet("background-color:#636e72; color:white; font-weight:bold; border-radius:6px;")
        btn_q.clicked.connect(quit_fn or self.reject)
        row.addWidget(btn_q)
        row.addStretch()

        if prev_fn:
            btn_p = QPushButton("◀ 이전")
            btn_p.setFixedHeight(38)
            btn_p.clicked.connect(prev_fn)
            row.addWidget(btn_p)

        if next_fn:
            btn_n = QPushButton(next_label)
            btn_n.setFixedHeight(38)
            btn_n.setStyleSheet("background-color:#2ecc71; color:white; font-weight:bold; border-radius:6px;")
            btn_n.clicked.connect(next_fn)
            row.addWidget(btn_n)

        return row

    # ═══════════════════════════════════════════════
    # 페이지 0 — 부품명 + 기존 선택 + PDF 파싱
    # ═══════════════════════════════════════════════

    def _build_page0(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(10)

        # ── 기존 부품 선택 ─────────────────────────
        ex_grp = QGroupBox("✏️  기존 부품 수정  (새 부품 추가라면 '— 새 부품 추가 —' 유지)")
        ex_grp.setStyleSheet(self._GS)
        eg = QHBoxLayout(ex_grp)
        self._existing_combo = QComboBox()
        self._existing_combo.addItem("— 새 부품 추가 —", userData="")
        for key, conf in sorted(self._registry.items(), key=lambda x: x[1]['name']):
            self._existing_combo.addItem(f"{conf['name']}  [{key}]", userData=key)
        self._existing_combo.currentIndexChanged.connect(self._on_existing_selected)
        eg.addWidget(self._existing_combo)
        lay.addWidget(ex_grp)

        # ── 부품명 (1순위 입력) ────────────────────
        name_grp = QGroupBox("📌 부품명  (카카오 멘트 및 UI에 표시되는 이름)")
        name_grp.setStyleSheet(self._GS)
        ng = QVBoxLayout(name_grp)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("예) 센서바디 450바 1개   /   신형 전용기   /   다이아프램")
        self._name_edit.setFixedHeight(36)
        self._name_edit.textChanged.connect(self._set_dirty)
        ng.addWidget(self._name_edit)
        lay.addWidget(name_grp)

        # ── PDF 파일 선택 + 파싱 ───────────────────
        pdf_grp = QGroupBox("📄 샘플 PDF 선택 및 파싱")
        pdf_grp.setStyleSheet(self._GS)
        pg = QVBoxLayout(pdf_grp)
        file_row = QHBoxLayout()
        self._pdf_path_edit = QLineEdit()
        self._pdf_path_edit.setPlaceholderText("PDF 파일 경로…")
        self._pdf_path_edit.setReadOnly(True)
        btn_browse = QPushButton("파일 선택")
        btn_browse.setFixedWidth(90)
        btn_browse.clicked.connect(self._browse_pdf)
        file_row.addWidget(self._pdf_path_edit)
        file_row.addWidget(btn_browse)
        pg.addLayout(file_row)

        btn_parse = QPushButton("🔍 파싱 실행")
        btn_parse.setFixedHeight(40)
        btn_parse.setStyleSheet("background-color:#3498db; color:white; font-weight:bold; font-size:11pt; border-radius:6px;")
        btn_parse.clicked.connect(self._do_parse)
        pg.addWidget(btn_parse)
        lay.addWidget(pdf_grp)

        # ── 파싱 결과 ──────────────────────────────
        res_grp = QGroupBox("파싱 결과 (signature 전체 — 이 목록이 자동으로 사용됩니다)")
        res_grp.setStyleSheet(self._GS)
        rg = QVBoxLayout(res_grp)

        warn = QLabel("⚠️  PDF 화면의 측정 항목과 파싱 결과가 동일한지 직접 확인하세요.\n"
                      "    만약 항목이 빠지거나 다르다면 파서 업데이트가 필요합니다.")
        warn.setStyleSheet("color:#e67e22; font-size:9pt; padding:4px 0;")
        warn.setWordWrap(True)
        rg.addWidget(warn)

        self._parse_result = QTextEdit()
        self._parse_result.setReadOnly(True)
        self._parse_result.setFixedHeight(200)
        self._parse_result.setStyleSheet(
            "background-color:#1e1e1e; color:#abb2bf; font-family:Consolas; font-size:9pt; padding:8px;"
        )
        rg.addWidget(self._parse_result)
        lay.addWidget(res_grp)

        lay.addStretch()
        lay.addLayout(self._nav(next_fn=self._page0_next))
        self.stack.addWidget(page)

    def _browse_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "샘플 PDF 선택", "", "PDF 파일 (*.pdf)")
        if path:
            self._pdf_path_edit.setText(path)

    def _do_parse(self):
        path = self._pdf_path_edit.text().strip()
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "오류", "PDF 파일을 먼저 선택하세요.")
            return
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            items = _parse_pdf_items(path)
            QApplication.restoreOverrideCursor()
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "파싱 오류", str(e))
            return

        self.parsed_items = items
        lines = [f"No.{i:02d}  {n}" for i, n in enumerate(items)]
        self._parse_result.setPlainText("\n".join(lines))
        self._parse_result.append(f"\n── 총 {len(items)}개 항목 인식됨 ──")

        # 기존 부품 로드 중이라면 signature 비교
        if self._existing_entry:
            existing_sig = self._existing_entry.get("signature", [])
            if existing_sig == items:
                self._parse_result.append("\n✅ 기존 signature와 완전히 일치합니다. 기존 설정을 자동으로 불러옵니다.")
            else:
                self._parse_result.append(
                    f"\n⚠️ 기존 signature({len(existing_sig)}개)와 현재 파싱({len(items)}개)이 다릅니다.\n"
                    "   Data Range를 수동으로 재설정하세요."
                )

    def _on_existing_selected(self, idx):
        key = self._existing_combo.currentData()
        if not key:
            self._edit_key = ""
            self._existing_entry = {}
            self._existing_excel = []
            return
        self._edit_key = key
        entry = self._registry.get(key, {})
        self._existing_entry = entry
        self._existing_excel = entry.get("excel_mapping", [])
        # 부품명 자동 입력
        self._name_edit.setText(entry.get("name", ""))
        # 파싱 결과가 이미 있으면 다시 비교 안내
        if self.parsed_items:
            self._do_parse()

    def _page0_next(self):
        if not self._name_edit.text().strip():
            QMessageBox.warning(self, "오류", "부품명을 입력하세요.")
            return

        # 기존 부품이 선택된 경우 PDF 파싱 없이 기존 signature 사용
        if self._existing_entry and not self.parsed_items:
            self.parsed_items = list(self._existing_entry.get("signature", []))

        if not self.parsed_items:
            QMessageBox.warning(self, "오류", "먼저 PDF를 파싱하세요.")
            return

        # signature 중복 검사
        sig = self.parsed_items
        for key, conf in self._registry.items():
            if key == self._edit_key:
                continue  # 수정 대상은 제외
            if conf.get("signature") == sig:
                QMessageBox.critical(self, "Signature 중복",
                    f"이미 존재하는 부품 [{conf['name']}] 과 signature가 완전히 동일합니다.\n\n"
                    "같은 PDF 구조로는 새 부품을 추가할 수 없습니다.\n"
                    "다른 PDF를 사용하거나, 기존 부품을 수정하세요.")
                return

        self._dirty = True
        self._rebuild_page1_items()
        self._go_to(1)

    # ═══════════════════════════════════════════════
    # 페이지 1 — 파트 타입 + Data Range
    # ═══════════════════════════════════════════════

    def _build_page1(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(10)

        # ── 파트 타입 ──────────────────────────────
        type_grp = QGroupBox("🏷️  파트 타입  (📁 파일명 저장 방식 + 💬 카카오 멘트 형식 동시 결정)")
        type_grp.setStyleSheet(self._GS)
        tg = QVBoxLayout(type_grp)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("타입:"))
        self._type_combo = QComboBox()
        self._type_combo.addItems([
            "일반형  —  신관/본관 + 호기 + 차수  |  멘트: {지역}-{호기} [OK/NG...]",
            "호기형 (ACV형)  —  호기 + 차수  |  멘트: {부품명} {호기}호기 {초/중/종품} 데이터입니다",
            "시간대형 (APC형)  —  차수만  |  멘트: {부품명} {초/중/종품} 데이터입니다",
        ])
        self._type_combo.setMinimumWidth(580)
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        type_row.addWidget(self._type_combo)
        type_row.addStretch()
        tg.addLayout(type_row)

        # 파일명 접두어 (호기형/시간대형일 때만)
        prefix_row = QHBoxLayout()
        self._prefix_lbl = QLabel("파일명 접두어:")
        self._prefix_edit = QLineEdit()
        self._prefix_edit.setPlaceholderText("예) APC  (비워두면 부품명 사용)")
        self._prefix_edit.setMinimumWidth(320)
        prefix_row.addWidget(self._prefix_lbl)
        prefix_row.addWidget(self._prefix_edit)
        prefix_row.addStretch()
        tg.addLayout(prefix_row)
        self._prefix_lbl.setVisible(False)
        self._prefix_edit.setVisible(False)

        # 파일명 형식 미리보기
        self._format_lbl = QLabel()
        self._format_lbl.setStyleSheet(
            "color:#2c3e50; font-family:Consolas; font-size:8.5pt;"
            " background-color:#f0f4f8; border-radius:4px; padding:6px 10px;"
        )
        self._format_lbl.setWordWrap(True)
        tg.addWidget(self._format_lbl)

        self._type_combo.currentIndexChanged.connect(self._update_format_lbl)
        self._type_combo.currentIndexChanged.connect(self._set_dirty)
        self._prefix_edit.textChanged.connect(self._update_format_lbl)
        self._prefix_edit.textChanged.connect(self._set_dirty)
        self._update_format_lbl()
        lay.addWidget(type_grp)

        # ── 파트 수 조정 ───────────────────────────
        parts_row = QHBoxLayout()
        parts_row.addWidget(QLabel("<b>파트 수:</b>"))
        self._part_count_lbl = QLabel("1")
        self._part_count_lbl.setStyleSheet("font-weight:bold; font-size:12pt; color:#2980b9;")
        parts_row.addWidget(self._part_count_lbl)
        btn_add = QPushButton("+ 파트 추가")
        btn_add.setFixedHeight(30)
        btn_add.clicked.connect(self._add_part)
        btn_rem = QPushButton("- 파트 삭제")
        btn_rem.setFixedHeight(30)
        btn_rem.clicked.connect(self._remove_part)
        parts_row.addWidget(btn_add)
        parts_row.addWidget(btn_rem)
        parts_row.addStretch()
        lay.addLayout(parts_row)

        # ── 항목 배정 테이블 ───────────────────────
        items_grp = QGroupBox("📋 항목별 파트 배정")
        items_grp.setStyleSheet(self._GS)
        ig = QVBoxLayout(items_grp)

        # 일괄 배정 바
        bulk_bar = QHBoxLayout()
        self._chk_all_items = QCheckBox("전체 선택")
        self._chk_all_items.stateChanged.connect(self._toggle_all_items)
        bulk_bar.addWidget(self._chk_all_items)
        bulk_bar.addStretch()
        bulk_bar.addWidget(QLabel("선택 항목 →"))
        self._bulk_part_combo = QComboBox()
        self._bulk_part_combo.setMinimumWidth(130)
        self._bulk_part_combo.addItems(["제외"] + [f"파트 {i+1}" for i in range(self.num_parts)])
        bulk_bar.addWidget(self._bulk_part_combo)
        btn_bulk = QPushButton("일괄 적용")
        btn_bulk.setFixedHeight(26)
        btn_bulk.setStyleSheet("background:#74b9ff; border-radius:4px;")
        btn_bulk.clicked.connect(self._bulk_assign_parts)
        bulk_bar.addWidget(btn_bulk)
        ig.addLayout(bulk_bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border:none; }")
        self._items_content = QWidget()
        self._items_layout = QVBoxLayout(self._items_content)
        self._items_layout.setSpacing(1)
        self._items_layout.setContentsMargins(4, 4, 4, 4)
        scroll.setWidget(self._items_content)
        ig.addWidget(scroll)
        lay.addWidget(items_grp)

        lay.addLayout(self._nav(prev_fn=lambda: self._go_to(0), next_fn=self._page1_next))
        self.stack.addWidget(page)

    def _on_type_changed(self, idx):
        show_prefix = idx in (1, 2)
        self._prefix_lbl.setVisible(show_prefix)
        self._prefix_edit.setVisible(show_prefix)
        self._update_format_lbl()

    def _update_format_lbl(self, _=None):
        idx = self._type_combo.currentIndex()
        p = self._prefix_edit.text().strip() or "(부품명/접두어)"
        if idx == 0:
            lines = [
                "📄 저장 파일명 형식 (일반형):",
                "  공구교환 없음:    {지역} {호기}-{차수}.pdf",
                "  공구교환 있음:    {지역} {호기}T-{차수}.pdf",
                "  NG 있음:          {지역} {호기}-{차수}n.pdf",
                "  예시:  본관 1-2.pdf  /  신관 3T-1n.pdf",
            ]
        elif idx == 1:
            lines = [
                f"📄 저장 파일명 형식 (호기형 / ACV형):",
                f"  공구교환 없음:    {p} 초품.pdf",
                f"  공구교환 있음:    {p} 초품 T.pdf",
                f"  예시:  {p} 중품.pdf  /  {p} 종품 T.pdf",
            ]
        else:
            lines = [
                f"📄 저장 파일명 형식 (시간대형 / APC형):",
                f"  접두어 없음:      초품.pdf  /  초품 T.pdf",
                f"  접두어 있음:      {p} 초품.pdf  /  {p} 초품 T.pdf",
            ]
        self._format_lbl.setText('\n'.join(lines))

    def _rebuild_page1_items(self):
        """파싱 후 또는 파트 수 변경 시 항목 목록 재구성"""
        while self._items_layout.count():
            item = self._items_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.item_combos.clear()
        self._item_checkboxes.clear()
        if hasattr(self, '_chk_all_items'):
            self._chk_all_items.blockSignals(True)
            self._chk_all_items.setChecked(False)
            self._chk_all_items.blockSignals(False)

        # 일괄 배정 콤보 갱신
        if hasattr(self, '_bulk_part_combo'):
            self._bulk_part_combo.clear()
            self._bulk_part_combo.addItems(["제외"] + [f"파트 {i+1}" for i in range(self.num_parts)])

        # 헤더
        hdr = QHBoxLayout()
        hdr.addSpacing(26)  # checkbox 열 공간
        hdr.addWidget(_lbl("No.", 50, bold=True))
        hdr.addWidget(_lbl("항목명", 420, bold=True))
        hdr.addWidget(_lbl("파트 배정", 120, bold=True))
        self._items_layout.addLayout(hdr)

        line = QFrame(); line.setFrameShape(QFrame.HLine); line.setStyleSheet("color:#bdc3c7;")
        self._items_layout.addWidget(line)

        part_opts = ["제외"] + [f"파트 {i+1}" for i in range(self.num_parts)]
        self._part_count_lbl.setText(str(self.num_parts))

        for idx, name in enumerate(self.parsed_items):
            row_w = QWidget()
            row_w.setStyleSheet("background-color:%s;" % ("#f8f9fa" if idx % 2 == 0 else "#ffffff"))
            rh = QHBoxLayout(row_w)
            rh.setContentsMargins(4, 1, 4, 1)

            chk = QCheckBox()
            chk.setFixedWidth(24)
            self._item_checkboxes.append(chk)

            no_lbl = QLabel(f"No.{idx:02d}")
            no_lbl.setFixedWidth(50)
            no_lbl.setStyleSheet("color:#7f8c8d; font-family:Consolas;")

            nm_lbl = QLabel(name)
            nm_lbl.setMinimumWidth(380)

            combo = QComboBox()
            combo.addItems(part_opts)
            combo.setCurrentIndex(1)
            combo.setFixedWidth(110)
            combo.currentIndexChanged.connect(self._set_dirty)
            self.item_combos.append(combo)

            rh.addWidget(chk)
            rh.addWidget(no_lbl)
            rh.addWidget(nm_lbl, 1)
            rh.addWidget(combo)
            self._items_layout.addWidget(row_w)

        self._items_layout.addStretch()

        # 기존 부품이라면 data_ranges 자동 채우기
        if self._existing_entry and self._existing_entry.get("signature") == self.parsed_items:
            self._auto_fill_data_ranges()

        # 기존 part_type, file_prefix 적용
        if self._existing_entry:
            pt = self._existing_entry.get("part_type", "")
            if not pt:
                name = self._existing_entry.get("name", "")
                if "ACV" in name.upper():
                    pt = "acv"
                elif "APC" in name.upper():
                    pt = "apc"
                else:
                    pt = "standard"
            pt_map = {"standard": 0, "acv": 1, "apc": 2,
                      "acv_legacy": 1, "apc_legacy": 2}
            self._type_combo.setCurrentIndex(pt_map.get(pt, 0))
            self._prefix_edit.setText(self._existing_entry.get("file_prefix", ""))

    def _toggle_all_items(self, state):
        for chk in self._item_checkboxes:
            chk.setChecked(state == Qt.Checked)

    def _bulk_assign_parts(self):
        target_idx = self._bulk_part_combo.currentIndex()
        for chk, combo in zip(self._item_checkboxes, self.item_combos):
            if chk.isChecked():
                combo.setCurrentIndex(target_idx)

    def _auto_fill_data_ranges(self):
        ranges = self._existing_entry.get("data_ranges", [])
        for combo in self.item_combos:
            combo.setCurrentIndex(0)  # 먼저 전부 '제외'

        for part_idx, range_list in enumerate(ranges):
            if part_idx + 1 > self.num_parts:
                # 파트 수 늘리기
                self.num_parts = part_idx + 1
                new_opt = f"파트 {self.num_parts}"
                for combo in self.item_combos:
                    combo.addItem(new_opt)
                self._part_count_lbl.setText(str(self.num_parts))

            indices = _expand_ranges(range_list)
            for idx in indices:
                if idx < len(self.item_combos):
                    self.item_combos[idx].setCurrentIndex(part_idx + 1)

    def _add_part(self):
        if self.num_parts >= 10:
            return
        self._dirty = True
        self.num_parts += 1
        new_opt = f"파트 {self.num_parts}"
        for combo in self.item_combos:
            combo.addItem(new_opt)
        self._part_count_lbl.setText(str(self.num_parts))
        if hasattr(self, '_bulk_part_combo'):
            self._bulk_part_combo.addItem(new_opt)

    def _remove_part(self):
        if self.num_parts <= 1:
            return
        self._dirty = True
        for combo in self.item_combos:
            combo.removeItem(combo.count() - 1)
            if combo.currentIndex() >= combo.count():
                combo.setCurrentIndex(combo.count() - 1)
        self.num_parts -= 1
        self._part_count_lbl.setText(str(self.num_parts))
        if hasattr(self, '_bulk_part_combo'):
            self._bulk_part_combo.removeItem(self._bulk_part_combo.count() - 1)

    def _page1_next(self):
        # 파트별 배정 항목 수 집계
        part_counts = [0] * self.num_parts
        for c in self.item_combos:
            idx = c.currentIndex()
            if idx > 0:
                part_counts[idx - 1] += 1

        empty_parts = [i + 1 for i, cnt in enumerate(part_counts) if cnt == 0]
        if empty_parts:
            parts_str = ", ".join(f"파트 {p}" for p in empty_parts)
            QMessageBox.warning(self, "항목 미배정",
                f"{parts_str}에 배정된 항목이 없습니다.\n"
                "모든 파트에 최소 1개 이상의 항목을 배정하거나,\n"
                "불필요한 파트를 '- 파트 삭제' 버튼으로 제거하세요.")
            return

        self._rebuild_page2()
        self._go_to(2)

    # ═══════════════════════════════════════════════
    # 페이지 2 — 영문 ID + 서브폴더 + Excel 매핑 + 저장
    # ═══════════════════════════════════════════════

    def _build_page2(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(10)

        # ── 기본 정보 ──────────────────────────────
        info_grp = QGroupBox("📝 기본 정보")
        info_grp.setStyleSheet(self._GS)
        ig = QVBoxLayout(info_grp)

        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("영문 부품명 (ID):"))
        self._key_edit = QLineEdit()
        self._key_edit.setPlaceholderText("예) SENSOR_BODY_450_1EA   /   APC_JEON   (영문·숫자·언더스코어)")
        key_row.addWidget(self._key_edit)
        ig.addLayout(key_row)

        sub_row = QHBoxLayout()
        sub_row.addWidget(QLabel("저장 서브폴더:"))
        self._sub_edit = QLineEdit()
        self._sub_edit.setPlaceholderText("비워두면 저장 경로 루트에 직접 저장")
        sub_row.addWidget(self._sub_edit)
        ig.addLayout(sub_row)
        lay.addWidget(info_grp)

        # ── Excel 매핑 스크롤 영역 ─────────────────
        lay.addWidget(QLabel("<b>📊 Excel 매핑  (Data Range 항목들 중에서 선택 / 비워두면 매핑 없음)</b>"))
        lay.addWidget(QLabel(
            "ℹ  행 번호는 자동(1행부터)으로 붙습니다. 항목과 방식(단일/MAX/MIN)만 설정하세요.",
            objectName="hint"
        ))

        self._excel_outer_scroll = QScrollArea()
        self._excel_outer_scroll.setWidgetResizable(True)
        self._excel_outer_scroll.setStyleSheet("QScrollArea { border:none; }")
        self._excel_outer_content = QWidget()
        self._excel_outer_layout = QVBoxLayout(self._excel_outer_content)
        self._excel_outer_layout.setSpacing(16)
        self._excel_outer_layout.setContentsMargins(0, 0, 0, 0)
        self._excel_outer_scroll.setWidget(self._excel_outer_content)
        lay.addWidget(self._excel_outer_scroll)

        # ── 특이사항 자동 체크 설정 ───────────────────
        chk_grp = QGroupBox("🔔 특이사항 자동 체크  (선택 사항 — 저장 시 config/special_checks.json 반영)")
        chk_grp.setStyleSheet(self._GS)
        cg = QVBoxLayout(chk_grp)

        hint = QLabel(
            "ℹ  두 항목의 실측값 편차가 기준 이상이면 작업창에 경고 메시지를 표시합니다.\n"
            "    예) 기준원1과 기준원2의 직경 편차 ≥ 4μm → 직접 측정 후 보고 요청"
        )
        hint.setStyleSheet("color:#636e72; font-size:9pt;")
        hint.setWordWrap(True)
        cg.addWidget(hint)

        # 체크 행 담을 영역
        chk_scroll = QScrollArea()
        chk_scroll.setWidgetResizable(True)
        chk_scroll.setMaximumHeight(340)
        chk_scroll.setStyleSheet("QScrollArea { border:none; }")
        chk_content = QWidget()
        self._check_rows_layout = QVBoxLayout(chk_content)
        self._check_rows_layout.setSpacing(8)
        self._check_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._check_rows_layout.addStretch()
        chk_scroll.setWidget(chk_content)
        cg.addWidget(chk_scroll)

        btn_add_chk = QPushButton("+ 체크 규칙 추가")
        btn_add_chk.setFixedHeight(30)
        btn_add_chk.setStyleSheet("background-color:#dfe6e9; border-radius:4px;")
        btn_add_chk.clicked.connect(self._add_check_row)
        cg.addWidget(btn_add_chk)
        lay.addWidget(chk_grp)

        lay.addLayout(self._nav(
            prev_fn=lambda: self._go_to(1),
            next_fn=self._do_save,
            next_label="💾 저장",
        ))
        self.stack.addWidget(page)

    def _rebuild_page2(self):
        """페이지 1 확정 후 페이지 2 Excel 섹션 재구성"""
        # 기존 위젯 비우기
        while self._excel_outer_layout.count():
            itm = self._excel_outer_layout.takeAt(0)
            if itm.widget():
                itm.widget().deleteLater()

        self._excel_block_names.clear()
        self._mapping_rows.clear()
        self._mapping_scrolls.clear()
        self._part_item_lists.clear()

        # 파트별 항목 목록 수집
        for p in range(self.num_parts):
            items = [
                (idx, name)
                for idx, (name, combo) in enumerate(zip(self.parsed_items, self.item_combos))
                if combo.currentIndex() == p + 1
            ]
            self._part_item_lists.append(items)

        for p, part_items in enumerate(self._part_item_lists):
            grp = QGroupBox(f"파트 {p+1}  Excel 매핑")
            grp.setStyleSheet(self._GS)
            grp_lay = QVBoxLayout(grp)

            # 블록명
            bname_row = QHBoxLayout()
            bname_row.addWidget(QLabel("블록명:"))
            bname_edit = QLineEdit(f"파트 {p+1} 엑셀 블록")
            bname_edit.setFixedWidth(280)
            bname_row.addWidget(bname_edit)
            bname_row.addStretch()
            grp_lay.addLayout(bname_row)
            self._excel_block_names.append(bname_edit)

            # 매핑 행들을 담을 스크롤
            row_scroll = QScrollArea()
            row_scroll.setWidgetResizable(True)
            row_scroll.setMinimumHeight(220)
            row_scroll.setMaximumHeight(520)
            row_scroll.setStyleSheet("QScrollArea { border:1px solid #dcdde1; }")
            row_content = QWidget()
            rows_lay = QVBoxLayout(row_content)
            rows_lay.setSpacing(0)
            rows_lay.setContentsMargins(4, 4, 4, 4)
            row_scroll.setWidget(row_content)
            grp_lay.addWidget(row_scroll)
            self._mapping_scrolls.append(row_scroll)

            row_list: list = []
            self._mapping_rows.append(row_list)

            # 기존 매핑 데이터 또는 기본값으로 행 생성
            existing_mappings = []
            if p < len(self._existing_excel):
                existing_mappings = self._existing_excel[p].get("mappings", [])
                bname_edit.setText(self._existing_excel[p].get("block_name", f"파트 {p+1} 엑셀 블록"))

            for m_dict in existing_mappings:
                self._add_mapping_row(p, rows_lay, row_list, part_items, m_dict)

            # + 행 추가 버튼
            btn_add = QPushButton("+ 매핑 행 추가")
            btn_add.setFixedHeight(28)
            btn_add.setStyleSheet("background-color:#dfe6e9;")
            btn_add.clicked.connect(
                lambda _, pi=p, rl=rows_lay, lst=row_list, pit=part_items, sc=row_scroll:
                    self._add_mapping_row(pi, rl, lst, pit, scroll=sc, is_user_add=True)
            )
            grp_lay.addWidget(btn_add)
            self._excel_outer_layout.addWidget(grp)

        self._excel_outer_layout.addStretch()

        # 기존 부품 수정이면 key/subfolder 자동 입력
        if self._existing_entry:
            self._key_edit.setText(self._edit_key)
            self._sub_edit.setText(self._existing_entry.get("sub_folder", ""))

        # ── 기존 특이사항 체크 로드 ──────────────────
        self._check_rows.clear()
        if self._check_rows_layout:
            # 기존 위젯 제거 (마지막 stretch 제외)
            while self._check_rows_layout.count() > 1:
                itm = self._check_rows_layout.takeAt(0)
                if itm.widget():
                    itm.widget().deleteLater()

        if self._edit_key:
            try:
                with open(SPECIAL_CHECKS_PATH, 'r', encoding='utf-8') as f:
                    existing_chks = json.load(f).get(self._edit_key, [])
            except Exception:
                existing_chks = []
            for chk_d in existing_chks:
                self._add_check_row(preset=chk_d)

    def _add_mapping_row(self, part_idx, rows_lay, row_list, part_items,
                         preset=None, scroll=None, is_user_add=False):
        from PyQt5.QtCore import QTimer

        row_num = len(row_list) + 1

        def del_cb():
            self._dirty = True
            row.container.setParent(None)
            row.container.deleteLater()
            if row in row_list:
                row_list.remove(row)
            for i, r in enumerate(row_list):
                r.update_num(i + 1)

        def move_cb(direction):
            if row not in row_list:
                return
            idx = row_list.index(row)
            new_idx = idx + direction
            if new_idx < 0 or new_idx >= len(row_list):
                return
            self._dirty = True
            row_list[idx], row_list[new_idx] = row_list[new_idx], row_list[idx]
            for r in row_list:
                rows_lay.removeWidget(r.container)
            for r in row_list:
                rows_lay.addWidget(r.container)
            for i, r in enumerate(row_list):
                r.update_num(i + 1)

        row = _MappingRow(row_num, part_items, del_cb)
        row._btn_up.clicked.connect(lambda: move_cb(-1))
        row._btn_down.clicked.connect(lambda: move_cb(1))

        def drop_cb(source_id):
            source_row = next((r for r in row_list if id(r) == source_id), None)
            if source_row is None or source_row is row:
                return
            self._dirty = True
            src_idx = row_list.index(source_row)
            tgt_idx = row_list.index(row)
            row_list.pop(src_idx)
            row_list.insert(tgt_idx, source_row)
            for r in row_list:
                rows_lay.removeWidget(r.container)
            for r in row_list:
                rows_lay.addWidget(r.container)
            for i, r in enumerate(row_list):
                r.update_num(i + 1)

        row.container.set_drop_cb(drop_cb)

        # 매핑 행 내용 변경도 dirty로 추적
        row._type_combo.currentIndexChanged.connect(self._set_dirty)
        row._single_combo.currentIndexChanged.connect(self._set_dirty)
        row._fixed_edit.textChanged.connect(self._set_dirty)
        for _, cb in row._checkboxes:
            cb.stateChanged.connect(self._set_dirty)

        if preset:
            row.set_data(preset)
        elif is_user_add:
            # 사용자가 직접 추가 → 고정값 "비가동" 기본값
            self._dirty = True
            row._type_combo.setCurrentIndex(3)
            row._on_type_changed(3)
            row._fixed_edit.setText("비가동")
        elif part_items:
            default_idx = min(row_num - 1, len(part_items) - 1)
            row._single_combo.setCurrentIndex(default_idx)

        row_list.append(row)
        rows_lay.addWidget(row.container)

        if scroll and (is_user_add or (not preset and len(row_list) > 3)):
            QTimer.singleShot(60, lambda: scroll.verticalScrollBar().setValue(
                scroll.verticalScrollBar().maximum()
            ))

    # ── 특이사항 체크 행 추가 ────────────────────────
    def _add_check_row(self, preset: dict = None):
        if self._check_rows_layout is None:
            return

        # 전체 파싱 항목을 (pdf_idx, name) 쌍으로 구성
        all_items = [(i, name) for i, name in enumerate(self.parsed_items)]

        def del_cb():
            self._dirty = True
            row.container.setParent(None)
            row.container.deleteLater()
            if row in self._check_rows:
                self._check_rows.remove(row)

        row = _CheckRow(all_items, del_cb, self._set_dirty)

        if preset:
            row.set_data(preset)
        else:
            # 기본값: 첫 번째 항목 → A, 두 번째 항목 → B, 4μm, 기본 메시지
            self._dirty = True
            row._label_edit.setText("편차 확인")
            row._threshold_spin.setValue(4.0)
            row._msg_edit.setText("⚠️ 두 항목의 편차가 기준 이상입니다.\\n→ 직접 측정 후 보고하기")

        # stretch 바로 앞에 삽입
        stretch_idx = self._check_rows_layout.count() - 1
        self._check_rows_layout.insertWidget(stretch_idx, row.container)
        self._check_rows.append(row)

    # ── 종료 가로채기 — 미저장 경고 ─────────────────
    def reject(self):
        if self._dirty:
            res = QMessageBox.question(
                self, "종료 확인",
                "변경사항이 저장되지 않았습니다.\n그래도 종료하시겠습니까?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if res != QMessageBox.Yes:
                return
        super().reject()

    # ── 저장 ─────────────────────────────────────
    def _do_save(self):
        key = self._key_edit.text().strip().upper().replace(' ', '_')
        name = self._name_edit.text().strip()
        sub_folder = self._sub_edit.text().strip()

        if not key:
            QMessageBox.warning(self, "입력 오류", "영문 부품명(ID)을 입력하세요.")
            return
        if not name:
            QMessageBox.warning(self, "입력 오류", "부품명을 입력하세요.")
            return

        # 파트 타입 결정
        type_idx = self._type_combo.currentIndex()
        part_type = ["standard", "acv", "apc"][type_idx]
        file_prefix = self._prefix_edit.text().strip() if type_idx in (1, 2) else ""

        # 중복 키 확인 (수정 대상 제외)
        if key in self._registry and key != self._edit_key:
            if QMessageBox.question(self, "키 중복",
                f"'{key}'가 이미 존재합니다. 덮어쓰시겠습니까?",
                QMessageBox.Yes | QMessageBox.No) == QMessageBox.No:
                return

        # signature
        signature = list(self.parsed_items)

        # data_ranges
        data_ranges = []
        for p in range(self.num_parts):
            indices = [idx for idx, c in enumerate(self.item_combos) if c.currentIndex() == p + 1]
            data_ranges.append(_compress_indices(indices))

        # excel_mapping
        excel_mapping = []
        for p in range(self.num_parts):
            block_name = (self._excel_block_names[p].text().strip()
                          if p < len(self._excel_block_names) else f"파트 {p+1}")
            mappings = []
            for row_num, row in enumerate(self._mapping_rows[p] if p < len(self._mapping_rows) else [], 1):
                d = row.get_data()
                vs = d.get("value_source")
                # 유효하지 않은 항목 건너뜀
                if d["source_type"] in ("max", "min") and not vs:
                    continue
                if d["source_type"] == "pdf_idx" and vs is None:
                    continue
                if d["source_type"] == "fixed" and (vs is None or str(vs).strip() == ""):
                    continue
                mappings.append({
                    "row_idx": row_num,
                    "source_type": d["source_type"],
                    "value_source": vs,
                    "label": "",
                })
            if mappings:
                excel_mapping.append({"block_name": block_name, "mappings": mappings})

        new_entry = {
            "name": name,
            "sub_folder": sub_folder,
            "part_type": part_type,
        }
        if file_prefix:
            new_entry["file_prefix"] = file_prefix
        new_entry["signature"] = signature
        new_entry["data_ranges"] = data_ranges
        new_entry["excel_mapping"] = excel_mapping

        # JSON 저장
        try:
            with open(REGISTRY_PATH, 'r', encoding='utf-8') as f:
                registry = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "로드 오류", f"parts_registry_v2.json 읽기 실패:\n{e}")
            return

        registry[key] = new_entry

        try:
            with open(REGISTRY_PATH, 'w', encoding='utf-8') as f:
                json.dump(registry, f, ensure_ascii=False, indent=2)
        except Exception as e:
            import pyperclip
            snippet = json.dumps({key: new_entry}, ensure_ascii=False, indent=2)
            try:
                pyperclip.copy(snippet)
                QMessageBox.information(self, "저장 실패 — 클립보드 복사",
                    f"파일 쓰기 실패 ({e}).\n"
                    "parts_registry_v2.json에 수동으로 추가하세요.\n"
                    "아래 JSON이 클립보드에 복사되었습니다.")
            except Exception:
                QMessageBox.critical(self, "저장 실패", str(e))
            return

        # ── special_checks.json 저장 ─────────────────
        checks_list = []
        for row in self._check_rows:
            d = row.get_data()
            if d.get("index_a") is None or d.get("index_b") is None:
                continue
            if d["index_a"] == d["index_b"]:
                QMessageBox.warning(self, "체크 설정 오류",
                    f"특이사항 체크 '{d['label']}' : 항목 A와 B가 같습니다.\n저장하려면 다른 항목을 선택하세요.")
                return
            if d["threshold"] <= 0:
                QMessageBox.warning(self, "체크 설정 오류",
                    f"특이사항 체크 '{d['label']}' : 임계값은 0보다 커야 합니다.")
                return
            checks_list.append(d)

        try:
            if os.path.exists(SPECIAL_CHECKS_PATH):
                with open(SPECIAL_CHECKS_PATH, 'r', encoding='utf-8') as f:
                    all_checks = json.load(f)
            else:
                all_checks = {}

            if checks_list:
                all_checks[key] = checks_list
            elif key in all_checks:
                del all_checks[key]   # 체크 없으면 항목 제거

            os.makedirs(os.path.dirname(SPECIAL_CHECKS_PATH), exist_ok=True)
            with open(SPECIAL_CHECKS_PATH, 'w', encoding='utf-8') as f:
                json.dump(all_checks, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(self, "특이사항 저장 실패",
                f"special_checks.json 쓰기 실패:\n{e}\n\n부품 레지스트리는 정상 저장됩니다.")

        self.part_saved.emit(key, name)
        chk_msg = f"  |  특이사항 체크: {len(checks_list)}건" if checks_list else ""
        QMessageBox.information(self, "저장 완료",
            f"✅ '{name}'이 레지스트리에 {'수정' if self._edit_key else '추가'}되었습니다.\n\n"
            f"키: {key}  |  파트 수: {self.num_parts}  |  항목 수: {len(signature)}{chk_msg}")
        self.accept()


# ─────────────────────────────────────────────
# 소형 유틸
# ─────────────────────────────────────────────

def _lbl(text, width=None, bold=False):
    lbl = QLabel(f"<b>{text}</b>" if bold else text)
    lbl.setStyleSheet("color:#2c3e50;")
    if width:
        lbl.setFixedWidth(width)
    return lbl
