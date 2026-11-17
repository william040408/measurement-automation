import json
import os
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QScrollArea,
    QLineEdit, QPushButton, QLabel, QFileDialog, QWidget, QCheckBox,
    QComboBox, QDoubleSpinBox, QGroupBox, QFrame, QStackedWidget, QTextEdit,
    QMessageBox, QSizePolicy
)
from PyQt5.QtCore import Qt
from config.settings import REGISTRY_PATH


# ──────────────────────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────────────────────

def _section_title(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        "font-size: 14pt; font-weight: bold; color: #2c3e50; padding-bottom: 6px;"
    )
    return lbl


_GS = """
    QGroupBox {
        font-weight: bold; font-size: 10pt;
        border: 1px solid #dcdde1; border-radius: 6px;
        margin-top: 18px; padding-top: 12px;
    }
    QGroupBox::title {
        subcontrol-origin: margin; left: 12px;
        padding: 0 4px; color: #2980b9;
    }
"""

# 사이드바 버튼 스타일
_BTN_NORMAL = """
    QPushButton {
        color: #b2bec3; background: transparent;
        text-align: left; padding: 0 12px;
        font-size: 10pt; border: none;
    }
    QPushButton:hover { background-color: #34495e; color: white; }
"""
_BTN_ACTIVE = """
    QPushButton {
        color: white; background-color: #2980b9;
        text-align: left; padding: 0 8px;
        font-size: 10pt; border: none;
        border-left: 4px solid #74b9ff;
    }
"""

# 부품 타입 배지 색상
_PT_BADGE = {
    'standard': ('일반형', '#6c5ce7'),
    'acv':      ('호기형', '#0984e3'),
    'apc':      ('시간대형', '#00b894'),
}


# ──────────────────────────────────────────────────────────────
# 부품 상세 정보 팝업
# ──────────────────────────────────────────────────────────────

class PartDetailDialog(QDialog):
    def __init__(self, key: str, entry: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"부품 상세 정보 — {entry.get('name', key)}")
        self.setMinimumSize(760, 640)
        self._build(key, entry)

    def _build(self, key: str, entry: dict):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 16)
        lay.setSpacing(10)

        # ── 기본 정보 ──────────────────────────────────
        info_grp = QGroupBox("기본 정보")
        info_grp.setStyleSheet(_GS)
        ig = QVBoxLayout(info_grp)

        _pt = entry.get('part_type', '')
        if not _pt:
            n = entry.get('name', '')
            _pt = 'acv' if 'ACV' in n else 'apc' if 'APC' in n else 'standard'
        pt_str = {'standard': '일반형', 'acv': '호기형 (ACV)', 'apc': '시간대형 (APC)'}.get(_pt, _pt)

        fields = [
            ("부품명",        entry.get('name', '')),
            ("영문 ID",       key),
            ("파트 타입",     pt_str),
            ("저장 서브폴더", entry.get('sub_folder', '') or '(루트)'),
            ("파일명 접두어", entry.get('file_prefix', '') or '(없음)'),
            ("파트 수",       str(len(entry.get('data_ranges', [])))),
        ]
        for label, val in fields:
            row = QHBoxLayout()
            lbl = QLabel(f"<b>{label}:</b>"); lbl.setMinimumWidth(130); lbl.setMaximumWidth(180)
            row.addWidget(lbl); row.addWidget(QLabel(val)); row.addStretch()
            ig.addLayout(row)
        lay.addWidget(info_grp)

        # ── Signature ──────────────────────────────────
        sig = entry.get('signature', [])
        sig_grp = QGroupBox(f"Signature  ({len(sig)}개 항목)")
        sig_grp.setStyleSheet(_GS)
        sg = QVBoxLayout(sig_grp)
        sig_te = QTextEdit()
        sig_te.setReadOnly(True); sig_te.setFixedHeight(130)
        sig_te.setStyleSheet(
            "background:#1e1e1e; color:#abb2bf; font-family:Consolas; font-size:9pt; padding:6px;"
        )
        sig_te.setPlainText('\n'.join(f"No.{i:02d}  {n}" for i, n in enumerate(sig)))
        sg.addWidget(sig_te)
        lay.addWidget(sig_grp)

        # ── Data Ranges + Excel Mapping (가로 배치) ──
        bottom = QHBoxLayout()

        dr = entry.get('data_ranges', [])
        dr_grp = QGroupBox(f"Data Ranges  ({len(dr)}개 파트)")
        dr_grp.setStyleSheet(_GS)
        dg = QVBoxLayout(dr_grp)
        dr_te = QTextEdit()
        dr_te.setReadOnly(True); dr_te.setFixedHeight(170)
        dr_te.setStyleSheet(
            "background:#1e1e1e; color:#abb2bf; font-family:Consolas; font-size:9pt; padding:6px;"
        )
        dr_te.setPlainText(
            '\n'.join(f"파트 {i+1}: {r}" for i, r in enumerate(dr)) or "(없음)"
        )
        dg.addWidget(dr_te)
        bottom.addWidget(dr_grp)

        em = entry.get('excel_mapping', [])
        em_grp = QGroupBox(f"Excel Mapping  ({len(em)}개 블록)")
        em_grp.setStyleSheet(_GS)
        eg = QVBoxLayout(em_grp)
        em_te = QTextEdit()
        em_te.setReadOnly(True); em_te.setFixedHeight(170)
        em_te.setStyleSheet(
            "background:#1e1e1e; color:#abb2bf; font-family:Consolas; font-size:9pt; padding:6px;"
        )
        em_lines = []
        for block in em:
            em_lines.append(f"[{block.get('block_name', '')}]")
            for m in block.get('mappings', []):
                em_lines.append(
                    f"  {m.get('row_idx')}행 → {m.get('source_type')}: {m.get('value_source')}"
                )
            em_lines.append("")
        em_te.setPlainText('\n'.join(em_lines).strip() or "(매핑 없음)")
        eg.addWidget(em_te)
        bottom.addWidget(em_grp)

        lay.addLayout(bottom)

        btn_close = QPushButton("닫기")
        btn_close.setFixedHeight(38)
        btn_close.setStyleSheet(
            "background-color:#636e72; color:white; font-weight:bold; border-radius:6px;"
        )
        btn_close.clicked.connect(self.accept)
        lay.addWidget(btn_close)


# ──────────────────────────────────────────────────────────────
# 메인 설정 다이얼로그
# ──────────────────────────────────────────────────────────────

class SettingsDialog(QDialog):

    def __init__(self, current_settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚙️ AZtech 설정")
        self.setMinimumSize(1000, 700)
        self.settings = current_settings
        self._load_registry()
        self._init_ui()
        self._switch_page(0)

    # ── 레지스트리 로드 ────────────────────────────────
    def _load_registry(self):
        try:
            with open(REGISTRY_PATH, 'r', encoding='utf-8') as f:
                self._registry = json.load(f)
        except Exception:
            self._registry = {}

    # ── 루트 레이아웃 ──────────────────────────────────
    def _init_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("background-color: #dcdde1;")
        sep.setFixedWidth(1)
        root.addWidget(sep)

        # 콘텐츠 영역
        content_w = QWidget()
        cl = QVBoxLayout(content_w)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_page_paths())       # 0
        self._stack.addWidget(self._build_page_thresholds())  # 1
        self._stack.addWidget(self._build_page_parts())       # 2
        cl.addWidget(self._stack)

        btn_save = QPushButton("✅  설정 저장 및 닫기")
        btn_save.setFixedHeight(44)
        btn_save.setStyleSheet(
            "background-color:#2980b9; color:white; font-weight:bold;"
            " font-size:11pt; border:none;"
        )
        btn_save.clicked.connect(self.accept)
        cl.addWidget(btn_save)

        root.addWidget(content_w, 1)

    # ── 사이드바 ───────────────────────────────────────
    def _build_sidebar(self) -> QWidget:
        sb = QWidget()
        sb.setFixedWidth(230)
        sb.setStyleSheet("background-color: #2c3e50;")

        sbl = QVBoxLayout(sb)
        sbl.setContentsMargins(0, 0, 0, 20)
        sbl.setSpacing(0)

        title = QLabel("⚙️  설정")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "color: white; font-size: 13pt; font-weight: bold; padding: 22px 10px 18px;"
        )
        sbl.addWidget(title)

        div = QFrame(); div.setFrameShape(QFrame.HLine)
        div.setStyleSheet("background-color: #34495e;"); div.setFixedHeight(1)
        sbl.addWidget(div)
        sbl.addSpacing(10)

        self._nav_btns = []
        nav = [
            ("📁 저장 경로 설정",   0),
            ("📐 상한 / 하한 기준", 1),
            ("🔧 부품 목록 관리",   2),
        ]
        for text, idx in nav:
            btn = QPushButton(text)
            btn.setFixedHeight(52)
            btn.setStyleSheet(_BTN_NORMAL)
            btn.clicked.connect(lambda _, i=idx: self._switch_page(i))
            sbl.addWidget(btn)
            self._nav_btns.append(btn)

        sbl.addStretch()
        return sb

    def _switch_page(self, idx: int):
        self._stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._nav_btns):
            btn.setStyleSheet(_BTN_ACTIVE if i == idx else _BTN_NORMAL)

    # ══════════════════════════════════════════════════
    # 패널 0 — 저장 경로 설정
    # ══════════════════════════════════════════════════

    def _build_page_paths(self) -> QWidget:
        page = QWidget(); page.setStyleSheet("background-color: #f8f9fa;")
        pl = QVBoxLayout(page)
        pl.setContentsMargins(28, 22, 28, 14)
        pl.setSpacing(14)

        pl.addWidget(_section_title("📁 저장 경로 설정"))

        # 감시 폴더
        watch_grp = QGroupBox("🔍 PDF 감시 폴더")
        watch_grp.setStyleSheet(_GS)
        wg = QHBoxLayout(watch_grp)
        self._watch_path_edit = QLineEdit(self.settings.get('watch_dir', ''))
        btn_bw = QPushButton("폴더 선택"); btn_bw.setFixedWidth(90)
        btn_bw.clicked.connect(lambda: self._browse(self._watch_path_edit))
        wg.addWidget(self._watch_path_edit); wg.addWidget(btn_bw)
        pl.addWidget(watch_grp)

        # 부품별 저장 경로
        parts_grp = QGroupBox("📂 부품별 저장 경로")
        parts_grp.setStyleSheet(_GS)
        pg = QVBoxLayout(parts_grp)

        # 일괄 툴바
        bulk = QHBoxLayout()
        self._chk_all = QCheckBox("전체 선택")
        self._chk_all.stateChanged.connect(self._toggle_all)
        btn_bulk = QPushButton("✅ 선택 항목 일괄 설정"); btn_bulk.clicked.connect(self._bulk_set_path)
        btn_clr  = QPushButton("🗑 선택 항목 초기화");   btn_clr.clicked.connect(self._bulk_clear_path)
        bulk.addWidget(self._chk_all); bulk.addStretch()
        bulk.addWidget(btn_bulk); bulk.addWidget(btn_clr)
        pg.addLayout(bulk)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")
        sc = QWidget(); scl = QVBoxLayout(sc); scl.setSpacing(3)

        self._part_rows = {}
        save_paths = self.settings.get('save_paths', {})
        for key, conf in sorted(self._registry.items(), key=lambda x: x[1]['name']):
            name = conf['name']
            row = QHBoxLayout()
            chk = QCheckBox(); chk.setFixedWidth(24)
            lbl = QLabel(f"<b>{name}</b>"); lbl.setMinimumWidth(200); lbl.setMaximumWidth(300)
            lbl.setCursor(Qt.PointingHandCursor)
            lbl.mousePressEvent = lambda _, c=chk: c.setChecked(not c.isChecked())
            cur = save_paths.get(name) or save_paths.get(key, '')
            edit = QLineEdit(cur); edit.setPlaceholderText("미지정 (기본 폴더 사용)")
            btn_br = QPushButton("폴더 선택"); btn_br.setFixedWidth(80)
            btn_br.clicked.connect(lambda _, e=edit: self._browse(e))
            row.addWidget(chk); row.addWidget(lbl)
            row.addWidget(edit); row.addWidget(btn_br)
            self._part_rows[key] = {'checkbox': chk, 'edit': edit, 'name': name}
            scl.addLayout(row)

        scl.addStretch()
        scroll.setWidget(sc)
        pg.addWidget(scroll)
        pl.addWidget(parts_grp)
        return page

    # ── 경로 패널 헬퍼 ─────────────────────────────────
    def _browse(self, edit: QLineEdit):
        path = QFileDialog.getExistingDirectory(self, "폴더 선택")
        if path:
            edit.setText(path)

    def _toggle_all(self, state):
        for row in self._part_rows.values():
            row['checkbox'].setChecked(state == Qt.Checked)

    def _bulk_set_path(self):
        sel = [r for r in self._part_rows.values() if r['checkbox'].isChecked()]
        if not sel: return
        path = QFileDialog.getExistingDirectory(self, "폴더 선택 (일괄 적용)")
        if path:
            for r in sel: r['edit'].setText(path)

    def _bulk_clear_path(self):
        for r in self._part_rows.values():
            if r['checkbox'].isChecked():
                r['edit'].clear()

    # ══════════════════════════════════════════════════
    # 패널 1 — 상한 / 하한 기준
    # ══════════════════════════════════════════════════

    def _build_page_thresholds(self) -> QWidget:
        page = QWidget(); page.setStyleSheet("background-color: #f8f9fa;")
        pl = QVBoxLayout(page)
        pl.setContentsMargins(28, 22, 28, 14)
        pl.setSpacing(14)

        pl.addWidget(_section_title("📐 UP / UN 상한 / 하한 기준"))

        cc = self.settings.get('classify', {})

        grp = QGroupBox("판정 기준 설정")
        grp.setStyleSheet(_GS)
        gl = QVBoxLayout(grp)

        desc = QLabel(
            "공칭값 기준(NominalMeasurement) 항목에만 적용됩니다.\n"
            "공차 잔여량(절대값) 또는 공차 사용률(비율) 기준으로 UP / UN 여부를 결정합니다."
        )
        desc.setStyleSheet("color:#636e72; font-size:9pt; padding:4px 0 10px;")
        desc.setWordWrap(True)
        gl.addWidget(desc)

        # 판정 모드
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("판정 모드:"))
        self._classify_mode = QComboBox()
        self._classify_mode.addItems([
            "OR  —  절대값 또는 비율 중 하나라도 해당  (기본)",
            "AND  —  절대값 AND 비율 둘 다 만족",
            "절대값만  —  잔여 공차 기준만 사용",
            "비율만  —  공차 사용률 기준만 사용",
        ])
        _mm = {"OR": 0, "AND": 1, "MARGIN_ONLY": 2, "RATIO_ONLY": 3}
        self._classify_mode.setCurrentIndex(_mm.get(cc.get('mode', 'OR'), 0))
        self._classify_mode.setMinimumWidth(400)
        mode_row.addWidget(self._classify_mode); mode_row.addStretch()
        gl.addLayout(mode_row)
        gl.addSpacing(6)

        # 절대값 기준
        margin_row = QHBoxLayout()
        ml = QLabel("절대값 기준 (mm):"); ml.setFixedWidth(155)
        self._classify_margin = QDoubleSpinBox()
        self._classify_margin.setRange(0.0001, 1.0)
        self._classify_margin.setSingleStep(0.001)
        self._classify_margin.setDecimals(4)
        self._classify_margin.setValue(cc.get('margin_limit', 0.003))
        self._classify_margin.setFixedWidth(120)
        margin_row.addWidget(ml); margin_row.addWidget(self._classify_margin)
        margin_row.addWidget(QLabel("← 잔여 공차가 이 값 이하이면 UP / UN"))
        margin_row.addStretch()
        gl.addLayout(margin_row)

        # 비율 기준
        ratio_row = QHBoxLayout()
        rl = QLabel("비율 기준 (%):"); rl.setFixedWidth(155)
        self._classify_ratio = QDoubleSpinBox()
        self._classify_ratio.setRange(1.0, 99.9)
        self._classify_ratio.setSingleStep(1.0)
        self._classify_ratio.setDecimals(1)
        self._classify_ratio.setValue(cc.get('ratio_limit', 0.85) * 100)
        self._classify_ratio.setFixedWidth(120)
        ratio_row.addWidget(rl); ratio_row.addWidget(self._classify_ratio)
        ratio_row.addWidget(QLabel("← 공차 사용률이 이 % 이상이면 UP / UN"))
        ratio_row.addStretch()
        gl.addLayout(ratio_row)

        pl.addWidget(grp)

        # 현재 적용 중 표시
        cur_grp = QGroupBox("현재 적용 중인 기준")
        cur_grp.setStyleSheet(_GS)
        cg = QVBoxLayout(cur_grp)
        import config.classify_settings as cs
        cg.addWidget(QLabel(
            f"모드: {cs.MODE}  |  절대값: {cs.MARGIN_LIMIT} mm  |  비율: {cs.RATIO_LIMIT*100:.1f}%\n"
            "(설정 저장 후 즉시 반영됩니다)"
        ))
        pl.addWidget(cur_grp)
        pl.addStretch()
        return page

    # ══════════════════════════════════════════════════
    # 패널 2 — 부품 목록 관리
    # ══════════════════════════════════════════════════

    def _build_page_parts(self) -> QWidget:
        page = QWidget(); page.setStyleSheet("background-color: #f8f9fa;")
        pl = QVBoxLayout(page)
        pl.setContentsMargins(28, 22, 28, 14)
        pl.setSpacing(12)

        pl.addWidget(_section_title("🔧 부품 목록 확인 및 수정"))

        hint_row = QHBoxLayout()
        self._parts_count_lbl = QLabel()
        self._parts_count_lbl.setStyleSheet("color:#636e72; font-size:9pt;")
        hint_row.addWidget(self._parts_count_lbl)
        hint_row.addStretch()
        btn_refresh = QPushButton("🔄 목록 새로고침")
        btn_refresh.setFixedHeight(30)
        btn_refresh.setStyleSheet("background:#dfe6e9; border-radius:4px; font-size:9pt;")
        btn_refresh.clicked.connect(self._rebuild_parts_list)
        hint_row.addWidget(btn_refresh)
        pl.addLayout(hint_row)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea { border:1px solid #dcdde1; border-radius:6px; background:white; }"
        )

        self._parts_list_widget = QWidget()
        self._parts_list_widget.setStyleSheet("background:white;")
        self._parts_list_layout = QVBoxLayout(self._parts_list_widget)
        self._parts_list_layout.setSpacing(0)
        self._parts_list_layout.setContentsMargins(0, 0, 0, 0)

        self._rebuild_parts_list()

        scroll.setWidget(self._parts_list_widget)
        pl.addWidget(scroll)
        return page

    def _rebuild_parts_list(self):
        self._load_registry()

        # 기존 위젯 제거
        while self._parts_list_layout.count():
            item = self._parts_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        parts_sorted = sorted(self._registry.items(), key=lambda x: x[1].get('name', x[0]))

        self._parts_count_lbl.setText(
            f"총 {len(parts_sorted)}개 부품 등록됨  |  수정/삭제는 레지스트리 파일에 즉시 반영됩니다."
        )

        if not parts_sorted:
            lbl = QLabel("  등록된 부품이 없습니다.")
            lbl.setStyleSheet("color:#7f8c8d; padding:16px;")
            self._parts_list_layout.addWidget(lbl)
            self._parts_list_layout.addStretch()
            return

        for i, (key, entry) in enumerate(parts_sorted):
            row_w = QFrame()
            row_w.setStyleSheet(f"""
                QFrame {{
                    background-color: {'#f8f9fa' if i % 2 == 0 else 'white'};
                    border-bottom: 1px solid #ecf0f1;
                }}
            """)
            row_h = QHBoxLayout(row_w)
            row_h.setContentsMargins(16, 10, 16, 10)

            # 이름 + ID
            info_w = QWidget()
            info_w.setStyleSheet("background:transparent; border:none;")
            ilay = QVBoxLayout(info_w); ilay.setSpacing(2); ilay.setContentsMargins(0, 0, 0, 0)
            name_lbl = QLabel(entry.get('name', key))
            name_lbl.setStyleSheet(
                "font-weight:bold; font-size:10.5pt; color:#2c3e50; background:transparent; border:none;"
            )
            ilay.addWidget(name_lbl)
            id_lbl = QLabel(f"ID: {key}")
            id_lbl.setStyleSheet(
                "color:#7f8c8d; font-size:8.5pt; font-family:Consolas; background:transparent; border:none;"
            )
            ilay.addWidget(id_lbl)
            row_h.addWidget(info_w, 1)

            # 파트 타입 배지
            _pt = entry.get('part_type', '')
            if not _pt:
                n = entry.get('name', '')
                _pt = 'acv' if 'ACV' in n else 'apc' if 'APC' in n else 'standard'
            badge_txt, badge_col = _PT_BADGE.get(_pt, ('기타', '#b2bec3'))
            badge = QLabel(badge_txt)
            badge.setMinimumWidth(62)
            badge.setAlignment(Qt.AlignCenter)
            badge.setStyleSheet(f"""
                background-color:{badge_col}; color:white;
                border-radius:10px; padding:3px 10px;
                font-size:8.5pt; font-weight:bold; border:none;
            """)
            row_h.addWidget(badge)
            row_h.addSpacing(14)

            # 버튼
            btn_detail = QPushButton("🔍 자세히")
            btn_detail.setFixedSize(82, 30)
            btn_detail.setStyleSheet("background:#dfe6e9; border-radius:4px; font-size:9pt;")
            btn_detail.clicked.connect(
                lambda _, k=key, e=dict(entry): self._show_detail(k, e)
            )

            btn_edit = QPushButton("✏️ 수정")
            btn_edit.setFixedSize(72, 30)
            btn_edit.setStyleSheet(
                "background:#74b9ff; color:#2c3e50; border-radius:4px;"
                " font-size:9pt; font-weight:bold;"
            )
            btn_edit.clicked.connect(lambda _, k=key: self._edit_part(k))

            btn_del = QPushButton("🗑️ 삭제")
            btn_del.setFixedSize(72, 30)
            btn_del.setStyleSheet(
                "background:#ff7675; color:white; border-radius:4px;"
                " font-size:9pt; font-weight:bold;"
            )
            btn_del.clicked.connect(
                lambda _, k=key, n=entry.get('name', key): self._delete_part(k, n)
            )

            row_h.addWidget(btn_detail)
            row_h.addWidget(btn_edit)
            row_h.addWidget(btn_del)

            self._parts_list_layout.addWidget(row_w)

        self._parts_list_layout.addStretch()

    def _show_detail(self, key: str, entry: dict):
        PartDetailDialog(key, entry, parent=self).exec_()

    def _edit_part(self, key: str):
        from ui.part_wizard_dialog import PartWizardDialog
        wizard = PartWizardDialog(parent=self, edit_key=key)
        wizard.part_saved.connect(lambda _k, _n: self._rebuild_parts_list())
        wizard.exec_()

    def _delete_part(self, key: str, name: str):
        res = QMessageBox.question(
            self, "삭제 확인",
            f"'{name}'  [{key}]  부품을 레지스트리에서 삭제하시겠습니까?\n\n"
            "이 작업은 즉시 반영되며 되돌릴 수 없습니다.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if res != QMessageBox.Yes:
            return
        try:
            with open(REGISTRY_PATH, 'r', encoding='utf-8') as f:
                reg = json.load(f)
            reg.pop(key, None)
            with open(REGISTRY_PATH, 'w', encoding='utf-8') as f:
                json.dump(reg, f, ensure_ascii=False, indent=2)
            self._rebuild_parts_list()
        except Exception as e:
            QMessageBox.critical(self, "삭제 실패", str(e))

    # ── 최종 설정값 반환 ───────────────────────────────
    def get_final_settings(self) -> dict:
        _mode_vals = ["OR", "AND", "MARGIN_ONLY", "RATIO_ONLY"]
        return {
            'watch_dir': self._watch_path_edit.text(),
            'save_paths': {row['name']: row['edit'].text() for row in self._part_rows.values()},
            'classify': {
                'mode': _mode_vals[self._classify_mode.currentIndex()],
                'margin_limit': self._classify_margin.value(),
                'ratio_limit': round(self._classify_ratio.value() / 100.0, 4),
            },
        }
