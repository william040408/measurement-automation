"""
관리자 리포트 다이얼로그 — 부품·항목·폴더 선택 후 Excel 리포트 생성
"""

import os
import json
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QComboBox, QListWidget, QListWidgetItem,
    QFileDialog, QCheckBox, QProgressBar, QMessageBox, QScrollArea,
    QWidget, QSizePolicy, QSplitter, QFrame
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont


# ── 워커 쓰레드 ─────────────────────────────────────────────────────

class ReportWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(int, int)
    error    = pyqtSignal(str)

    def __init__(self, kwargs: dict):
        super().__init__()
        self._kw = kwargs

    def run(self):
        try:
            from modules.report_generator import generate_report
            processed, skipped = generate_report(
                **self._kw,
                progress_cb=lambda cur, tot, msg: self.progress.emit(cur, tot, msg)
            )
            self.finished.emit(processed, skipped)
        except Exception as e:
            import traceback
            self.error.emit(traceback.format_exc())


# ── 메인 다이얼로그 ──────────────────────────────────────────────────

class AdminReportDialog(QDialog):
    def __init__(self, detector, registry: dict, parent=None):
        super().__init__(parent)
        self.detector  = detector
        self.registry  = self._build_choices(registry)   # {key: {name, signature, ...}}
        self._worker   = None

        self.setWindowTitle("📊 관리자 데이터 리포트")
        self.setMinimumSize(860, 680)
        self._build_ui()

    @staticmethod
    def _build_choices(registry: dict) -> dict:
        """센서바디 N바 1·2·3개는 압력별 하나의 통합 항목으로 대체 (첫 등장 위치에)."""
        from modules.report_generator import sensor_body_groups
        groups = sensor_body_groups(registry)
        member_of = {vk: gk for gk, g in groups.items() for vk in g["group_variants"]}
        choices = {}
        for key, cfg in registry.items():
            gk = member_of.get(key)
            if gk is None:
                choices[key] = cfg
            elif gk not in choices:
                choices[gk] = groups[gk]
        return choices

    # ── UI 구성 ─────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # ── 왼쪽 패널 ───────────────────────────────────────────────
        left = QWidget()
        lv   = QVBoxLayout(left)
        lv.setSpacing(8)
        lv.setContentsMargins(0, 0, 4, 0)

        # 부품 선택
        gb_part = QGroupBox("1. 부품 선택")
        pv = QVBoxLayout(gb_part)
        self.cmb_part = QComboBox()
        for key, cfg in self.registry.items():
            self.cmb_part.addItem(cfg.get('name', key), key)
        self.cmb_part.currentIndexChanged.connect(self._on_part_changed)
        pv.addWidget(self.cmb_part)
        lv.addWidget(gb_part)

        # 항목 선택
        gb_items = QGroupBox("2. 포함할 항목 선택")
        iv = QVBoxLayout(gb_items)
        btn_row = QHBoxLayout()
        btn_all  = QPushButton("전체 선택")
        btn_none = QPushButton("전체 해제")
        btn_all.clicked.connect(self._select_all_items)
        btn_none.clicked.connect(self._deselect_all_items)
        btn_row.addWidget(btn_all)
        btn_row.addWidget(btn_none)
        iv.addLayout(btn_row)

        self.lst_items = QListWidget()
        self.lst_items.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        iv.addWidget(self.lst_items)
        lv.addWidget(gb_items, stretch=1)

        splitter.addWidget(left)

        # ── 오른쪽 패널 ─────────────────────────────────────────────
        right = QWidget()
        rv    = QVBoxLayout(right)
        rv.setSpacing(8)
        rv.setContentsMargins(4, 0, 0, 0)

        # 폴더 선택
        gb_folder = QGroupBox("3. PDF 폴더 선택 (여러 개 가능)")
        fv = QVBoxLayout(gb_folder)
        btn_f_row = QHBoxLayout()
        btn_add_folder = QPushButton("📁 폴더 추가")
        btn_del_folder = QPushButton("🗑 선택 삭제")
        btn_add_folder.clicked.connect(self._add_folder)
        btn_del_folder.clicked.connect(self._del_folder)
        btn_f_row.addWidget(btn_add_folder)
        btn_f_row.addWidget(btn_del_folder)
        fv.addLayout(btn_f_row)
        self.lst_folders = QListWidget()
        self.lst_folders.setMinimumHeight(120)
        fv.addWidget(self.lst_folders)
        rv.addWidget(gb_folder)

        # 필터
        gb_type = QGroupBox("4. 필터")
        tv = QVBoxLayout(gb_type)
        tv.setSpacing(4)

        tv.addWidget(QLabel("▸ 주야간:"))
        shift_row = QHBoxLayout()
        self.chk_주간 = QCheckBox("주간")
        self.chk_야간 = QCheckBox("야간")
        self.chk_주간.setChecked(True)
        self.chk_야간.setChecked(True)
        shift_row.addWidget(self.chk_주간)
        shift_row.addWidget(self.chk_야간)
        shift_row.addStretch()
        tv.addLayout(shift_row)

        tv.addWidget(QLabel("▸ 파일 종류:"))
        self.chk_standard = QCheckBox("표준")
        self.chk_T        = QCheckBox("공구교환 (T)")
        self.chk_S        = QCheckBox("세팅품 (S)")
        self.chk_su       = QCheckBox("수정품 (수)")
        self.chk_other    = QCheckBox("기타 (호기-차수 패턴 없음)")
        for chk in (self.chk_standard, self.chk_T, self.chk_S, self.chk_su):
            chk.setChecked(True)
            tv.addWidget(chk)
        self.chk_other.setChecked(False)
        tv.addWidget(self.chk_other)
        rv.addWidget(gb_type)

        # 출력 경로
        gb_out = QGroupBox("5. 저장 경로")
        ov = QVBoxLayout(gb_out)

        folder_row = QHBoxLayout()
        self.lbl_out_folder = QLabel("(폴더 미선택)")
        self.lbl_out_folder.setWordWrap(True)
        self.lbl_out_folder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        btn_out = QPushButton("폴더 선택…")
        btn_out.setFixedWidth(90)
        btn_out.clicked.connect(self._choose_output_folder)
        folder_row.addWidget(self.lbl_out_folder, stretch=1)
        folder_row.addWidget(btn_out)
        ov.addLayout(folder_row)

        fname_row = QHBoxLayout()
        from PyQt5.QtWidgets import QLineEdit
        fname_row.addWidget(QLabel("파일명:"))
        self.edt_filename = QLineEdit()
        self.edt_filename.setPlaceholderText("예: 리포트_CARRIER250.xlsx")
        fname_row.addWidget(self.edt_filename)
        ov.addLayout(fname_row)

        rv.addWidget(gb_out)

        rv.addStretch()
        splitter.addWidget(right)
        splitter.setSizes([440, 380])

        root.addWidget(splitter, stretch=1)

        # ── 진행바 ───────────────────────────────────────────────────
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.lbl_progress = QLabel("")
        self.lbl_progress.setVisible(False)
        root.addWidget(self.progress_bar)
        root.addWidget(self.lbl_progress)

        # ── 하단 버튼 ────────────────────────────────────────────────
        btn_row_bot = QHBoxLayout()
        self.btn_generate = QPushButton("📊 리포트 생성")
        self.btn_generate.setFixedHeight(44)
        self.btn_generate.setFont(QFont("Malgun Gothic", 11, QFont.Weight.Bold))
        self.btn_generate.setStyleSheet(
            "background-color: #2980b9; color: white; border-radius: 8px;"
        )
        self.btn_generate.clicked.connect(self._generate)

        btn_close = QPushButton("닫기")
        btn_close.setFixedWidth(80)
        btn_close.clicked.connect(self.close)

        btn_row_bot.addWidget(self.btn_generate, stretch=1)
        btn_row_bot.addWidget(btn_close)
        root.addLayout(btn_row_bot)

        self._output_folder = ""
        self._on_part_changed()

    # ── 이벤트 핸들러 ────────────────────────────────────────────────

    def _on_part_changed(self):
        self.lst_items.clear()
        key = self.cmb_part.currentData()
        if not key:
            return
        sig = self.registry.get(key, {}).get('signature', [])
        for i, label in enumerate(sig):
            item = QListWidgetItem(f"[{i}] {label}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.lst_items.addItem(item)

    def _select_all_items(self):
        for i in range(self.lst_items.count()):
            self.lst_items.item(i).setCheckState(Qt.CheckState.Checked)

    def _deselect_all_items(self):
        for i in range(self.lst_items.count()):
            self.lst_items.item(i).setCheckState(Qt.CheckState.Unchecked)

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "PDF 폴더 선택")
        if not folder:
            return
        existing = [self.lst_folders.item(i).text()
                    for i in range(self.lst_folders.count())]
        if folder not in existing:
            self.lst_folders.addItem(folder)

    def _del_folder(self):
        for item in self.lst_folders.selectedItems():
            self.lst_folders.takeItem(self.lst_folders.row(item))

    def _choose_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Excel 저장 폴더 선택")
        if folder:
            self._output_folder = folder
            self.lbl_out_folder.setText(folder)
            # 파일명이 비어있으면 기본값 세팅
            if not self.edt_filename.text().strip():
                from datetime import datetime
                key  = self.cmb_part.currentData() or "리포트"
                date = datetime.now().strftime("%Y%m%d")
                self.edt_filename.setText(f"리포트_{key}_{date}.xlsx")

    # ── 생성 ────────────────────────────────────────────────────────

    def _generate(self):
        # 유효성 검사
        key = self.cmb_part.currentData()
        if not key:
            QMessageBox.warning(self, "오류", "부품을 선택해 주세요."); return

        selected_indices = []
        item_names       = []
        for i in range(self.lst_items.count()):
            w = self.lst_items.item(i)
            if w.checkState() == Qt.CheckState.Checked:
                selected_indices.append(w.data(Qt.ItemDataRole.UserRole))
                label = w.text().split("] ", 1)[1] if "] " in w.text() else w.text()
                item_names.append(label)

        if not selected_indices:
            QMessageBox.warning(self, "오류", "항목을 하나 이상 선택해 주세요."); return

        folders = [self.lst_folders.item(i).text()
                   for i in range(self.lst_folders.count())]
        if not folders:
            QMessageBox.warning(self, "오류", "PDF 폴더를 하나 이상 추가해 주세요."); return

        if not self._output_folder:
            QMessageBox.warning(self, "오류", "저장 폴더를 선택해 주세요."); return

        fname = self.edt_filename.text().strip()
        if not fname:
            QMessageBox.warning(self, "오류", "파일명을 입력해 주세요."); return
        if not fname.lower().endswith('.xlsx'):
            fname += '.xlsx'
        output_path = os.path.join(self._output_folder, fname)

        if os.path.exists(output_path):
            ans = QMessageBox.question(
                self, "파일 덮어쓰기",
                f"'{fname}' 파일이 이미 존재합니다.\n덮어쓰시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if ans != QMessageBox.StandardButton.Yes:
                return

        if not (self.chk_주간.isChecked() or self.chk_야간.isChecked()):
            QMessageBox.warning(self, "오류", "주간 또는 야간을 하나 이상 선택해 주세요."); return

        if not (self.chk_standard.isChecked() or self.chk_T.isChecked()
                or self.chk_S.isChecked() or self.chk_su.isChecked()
                or self.chk_other.isChecked()):
            QMessageBox.warning(self, "오류", "포함할 파일 종류를 하나 이상 선택해 주세요."); return

        # 워커 시작
        self._last_output_path = output_path
        kwargs = dict(
            part_key         = key,
            part_config      = self.registry.get(key, {}),
            selected_indices = selected_indices,
            item_names       = item_names,
            folders          = folders,
            include_standard = self.chk_standard.isChecked(),
            include_T        = self.chk_T.isChecked(),
            include_S        = self.chk_S.isChecked(),
            include_su       = self.chk_su.isChecked(),
            include_other    = self.chk_other.isChecked(),
            include_주간     = self.chk_주간.isChecked(),
            include_야간     = self.chk_야간.isChecked(),
            detector         = self.detector,
            output_path      = output_path,
        )

        self._worker = ReportWorker(kwargs)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(True)
        self.lbl_progress.setText("분석 중…")
        self.lbl_progress.setVisible(True)
        self.btn_generate.setEnabled(False)

        self._worker.start()

    def _on_progress(self, cur: int, tot: int, msg: str):
        if tot > 0:
            self.progress_bar.setRange(0, tot)
            self.progress_bar.setValue(cur)
        self.lbl_progress.setText(f"({cur}/{tot if tot else '?'}) {msg}")

    def _on_finished(self, processed: int, skipped: int):
        self.progress_bar.setVisible(False)
        self.lbl_progress.setVisible(False)
        self.btn_generate.setEnabled(True)
        msg = (f"✅ 리포트 생성 완료!\n\n"
               f"처리: {processed}건  /  건너뜀: {skipped}건\n\n"
               f"저장 경로:\n{self._last_output_path}")
        QMessageBox.information(self, "완료", msg)
        os.startfile(os.path.dirname(self._last_output_path))

    def _on_error(self, tb: str):
        self.progress_bar.setVisible(False)
        self.lbl_progress.setVisible(False)
        self.btn_generate.setEnabled(True)
        QMessageBox.critical(self, "오류 발생", f"리포트 생성 중 오류가 발생했습니다:\n\n{tb}")
