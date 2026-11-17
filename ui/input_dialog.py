import os
import json
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QRadioButton, 
    QButtonGroup, QSpinBox, QPushButton, QCheckBox, QGroupBox, 
    QFrame, QStackedWidget, QWidget, QTextEdit, QMessageBox, QScrollArea, QApplication
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer

class InputDialog(QDialog):
    from config.settings import CONFIG_DIR as _MACHINE_CONFIG_DIR
    HISTORY_FILE = os.path.join(_MACHINE_CONFIG_DIR, "user_history.json")
    del _MACHINE_CONFIG_DIR
    
    history = {}
    last_timing = 1

    @classmethod
    def load_history(cls):
        if os.path.exists(cls.HISTORY_FILE) and os.path.getsize(cls.HISTORY_FILE) > 0:
            try:
                with open(cls.HISTORY_FILE, "r", encoding="utf-8") as f:
                    cls.history = json.load(f)
                    cls.last_timing = cls.history.get("_global_last_timing", 1)
            except Exception:
                cls.history = {}

    @classmethod
    def save_history(cls):
        os.makedirs(os.path.dirname(cls.HISTORY_FILE), exist_ok=True)
        try:
            cls.history["_global_last_timing"] = cls.last_timing
            with open(cls.HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(cls.history, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"히스토리 저장 실패: {e}")

    action_triggered = pyqtSignal(str, dict, object)
    save_requested = pyqtSignal(dict)
    discard_requested = pyqtSignal()

    def __init__(self, file_name, config, parent=None):
        super().__init__(parent)
        InputDialog.load_history()
        self.file_name = file_name
        self.config = config
        self.pdf_path = ""           # 레거시 (미사용)
        self.full_pdf_path = ""      # main.py에서 dialog.full_pdf_path = ... 로 주입
        self._is_saved = False
        self._saved_final_path = ""
        self.is_sample = False       # 측정의뢰품 모드 플래그
        self.part_name = config.get('name', '알 수 없는 부품')
        # part_type 필드 우선, 없으면 이름으로 추론 (하위호환)
        _pt = config.get("part_type", "")
        if not _pt:
            _pt = "apc" if "APC" in self.part_name else ""
        self.is_apc = (_pt == "apc")
        self.result_data = {}
        
        # [수정] 한 번만 위로 띄우기 (고정 해제)
        self.setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.WindowSystemMenuHint | Qt.WindowMinMaxButtonsHint)
        
        self.init_ui()
        self.raise_()
        self.activateWindow()

    def init_ui(self):
        self.setWindowTitle("🛠️ AZtech 작업 콘솔")
        self.setMinimumSize(800, 950)
        self.main_layout = QVBoxLayout(self)
        self.stack = QStackedWidget()
        self.main_layout.addWidget(self.stack)
        
        # 페이지 1: 호기 설정
        self.setup_page_input()
        # 페이지 2: 결과 확인 및 작업
        self.setup_page_action()
        
        self.stack.setCurrentIndex(0)

    def setup_page_input(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        
        group_style = """
            QGroupBox { font-weight: bold; font-size: 11pt; border: 2px solid #dcdde1; 
                        border-radius: 8px; margin-top: 20px; padding-top: 15px; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 15px; padding: 0 5px; color: #2980b9; }
        """

        part_hist = InputDialog.history.get(self.part_name, {"site": "신관", "machines": [0, 0, 0]})

        info_frame = QFrame()
        info_frame.setStyleSheet("background-color: #f8f9fa; border-radius: 10px; border: 2px solid #3498db; padding: 15px;")
        info_layout = QVBoxLayout(info_frame)

        part_label = QLabel(self.part_name)
        part_label.setStyleSheet("font-size: 20pt; font-weight: bold; color: #2c3e50; border: none;")
        part_label.setAlignment(Qt.AlignCenter)
        info_layout.addWidget(part_label)
        info_layout.addWidget(QLabel(f"📄 파일명: {self.file_name}"))
        layout.addWidget(info_frame)

        timing_group = QGroupBox("⏰ 차수")
        timing_group.setStyleSheet(group_style)
        t_box = QHBoxLayout()
        self.timing_group_btn = QButtonGroup(self)
        for i, text in enumerate(["초물", "중물", "종물"], 1):
            radio = QRadioButton(text); self.timing_group_btn.addButton(radio, i); t_box.addWidget(radio)
            if i == InputDialog.last_timing: radio.setChecked(True)
        timing_group.setLayout(t_box)

        if self.is_apc:
            # APC는 시간대만 입력
            self.radio_new = QRadioButton("신관"); self.radio_new.setChecked(True)  # 더미
            self.radio_main = QRadioButton("본관")
            self.machine_spins = []
            self.type_groups = []
            layout.addWidget(timing_group)
        else:
            row1 = QHBoxLayout()
            site_group = QGroupBox("📍 위치")
            site_group.setStyleSheet(group_style)
            site_box = QHBoxLayout()
            self.radio_new = QRadioButton("신관"); self.radio_main = QRadioButton("본관")
            if part_hist.get("site") == "신관": self.radio_new.setChecked(True)
            else: self.radio_main.setChecked(True)
            site_box.addWidget(self.radio_new); site_box.addWidget(self.radio_main)
            site_group.setLayout(site_box)
            row1.addWidget(site_group); row1.addWidget(timing_group)
            layout.addLayout(row1)

            m_group = QGroupBox("🔢 호기 설정")
            m_group.setStyleSheet(group_style)
            m_layout = QVBoxLayout()
            self.machine_spins = []; self.type_groups = []
            data_count = len(self.config.get('data_ranges', [None]))
            hist_machines = part_hist.get("machines", [0, 0, 0])

            def _make_exclusive(chk, others):
                def handler(checked):
                    if checked:
                        for o in others:
                            o.setChecked(False)
                return handler

            for i in range(3):
                row = QHBoxLayout()
                spin = QSpinBox(); spin.setRange(0, 35); spin.setFixedSize(80, 35)
                spin.setValue(hist_machines[i] if i < len(hist_machines) else 0)
                self.machine_spins.append(spin)

                chk_t  = QCheckBox("공구교환")
                chk_s  = QCheckBox("세팅품")
                chk_su = QCheckBox("수정품")
                for chk in (chk_t, chk_s, chk_su):
                    chk.setChecked(False)
                chk_t.toggled.connect(_make_exclusive(chk_t,  [chk_s, chk_su]))
                chk_s.toggled.connect(_make_exclusive(chk_s,  [chk_t, chk_su]))
                chk_su.toggled.connect(_make_exclusive(chk_su, [chk_t, chk_s]))
                self.type_groups.append((chk_t, chk_s, chk_su))

                row.addWidget(QLabel(f"{i+1}번 호기:")); row.addWidget(spin)
                row.addSpacing(15)
                row.addWidget(chk_t); row.addWidget(chk_s); row.addWidget(chk_su)
                row.addStretch()
                m_layout.addLayout(row)
                if i >= data_count:
                    spin.setEnabled(False)
                    for chk in (chk_t, chk_s, chk_su):
                        chk.setEnabled(False)

            m_group.setLayout(m_layout)
            layout.addWidget(m_group)

        layout.addStretch()

        self.btn_next = QPushButton("입력 완료 및 결과 확인 (Enter)")
        self.btn_next.setFixedHeight(60)
        self.btn_next.setStyleSheet("background-color: #2ecc71; color: white; font-weight: bold; font-size: 15pt; border-radius: 8px;")
        self.btn_next.clicked.connect(self.go_to_action_page)
        self.btn_next.setDefault(True)

        btn_discard_p1 = QPushButton("🗑️ 측정 불량 파기")
        btn_discard_p1.setFixedHeight(60)
        btn_discard_p1.setStyleSheet("background-color: #95a5a6; color: white; font-weight: bold; font-size: 11pt; border-radius: 8px;")
        btn_discard_p1.clicked.connect(self._confirm_discard)
        btn_discard_p1.setDefault(False)
        btn_discard_p1.setAutoDefault(False)

        btn_sample = QPushButton("📋 측정의뢰품")
        btn_sample.setFixedHeight(60)
        btn_sample.setStyleSheet("background-color: #8e44ad; color: white; font-weight: bold; font-size: 12pt; border-radius: 8px;")
        btn_sample.clicked.connect(self._go_as_sample)
        btn_sample.setDefault(False)
        btn_sample.setAutoDefault(False)

        bottom_row = QHBoxLayout()
        bottom_row.addWidget(btn_discard_p1, 1)
        bottom_row.addSpacing(8)
        bottom_row.addWidget(self.btn_next, 3)
        bottom_row.addSpacing(8)
        bottom_row.addWidget(btn_sample, 1)
        layout.addLayout(bottom_row)
        self.stack.addWidget(page)

    def setup_page_action(self):
        self.action_page = QWidget()
        layout = QVBoxLayout(self.action_page)
        
        # 1. 상단 분석 로그 (고정 높이)
        layout.addWidget(QLabel("<b>🔍 실시간 분석 로그 (모든 호기 합계):</b>"))
        self.debug_log = QTextEdit()
        self.debug_log.setReadOnly(True)
        self.debug_log.setFixedHeight(250) 
        self.debug_log.setStyleSheet("background-color: #2c3e50; color: #ecf0f1; font-family: Consolas; font-size: 10pt; padding: 10px;")
        layout.addWidget(self.debug_log)

        # 2. 중앙 스크롤 영역 (유동적 길이의 핵심)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")
        
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background-color: transparent;")
        
        # ⭐ 핵심: 위젯들이 위에서부터 차곡차곡 쌓이게 Alignment 설정
        self.scroll_main_layout = QVBoxLayout(scroll_content)
        self.scroll_main_layout.setAlignment(Qt.AlignTop) 
        self.scroll_main_layout.setContentsMargins(10, 10, 10, 10)
        self.scroll_main_layout.setSpacing(15) # 카드 사이 간격

        # 💡 여기가 에러의 원인이었던 부분! 이름을 하나로 통일합니다.
        self.content_layout = self.scroll_main_layout 
        
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        # 3. 하단 버튼 (저장/종료) - 기존 유지
        btn_row = QHBoxLayout()
        self.btn_save = QPushButton("💾 데이터 분류 저장")
        self.btn_save.setFixedHeight(55)
        self.btn_save.setStyleSheet("background-color: #e67e22; color: white; font-weight: bold; font-size: 13pt; border-radius: 8px;")
        self.btn_save.clicked.connect(self.request_save)
        
        self.btn_close = QPushButton("❌ 작업 종료 (창 닫기)")
        self.btn_close.setFixedHeight(55)
        self.btn_close.setStyleSheet("background-color: #2980b9; color: white; font-weight: bold; font-size: 13pt; border-radius: 8px;")
        self.btn_close.clicked.connect(self._handle_close)

        btn_discard_p2 = QPushButton("🗑️ 측정 불량 파기")
        btn_discard_p2.setFixedHeight(55)
        btn_discard_p2.setStyleSheet("background-color: #95a5a6; color: white; font-weight: bold; font-size: 11pt; border-radius: 8px;")
        btn_discard_p2.clicked.connect(self._confirm_discard)

        btn_row.addWidget(btn_discard_p2)
        btn_row.addWidget(self.btn_save)
        btn_row.addWidget(self.btn_close)
        layout.addLayout(btn_row)

        btn_back = QPushButton("⬅️ 정보 수정으로 돌아가기")
        btn_back.setFixedHeight(35)
        btn_back.clicked.connect(self._go_back_to_page1)
        layout.addWidget(btn_back)

        self.stack.addWidget(self.action_page)

    def request_save(self):
        """저장 버튼 클릭 시 호출"""
        print(f"\n[DIALOG_LOG] --- 저장 요청 시작 ---")

        # 1. 파일 점유 체크
        if self.full_pdf_path and os.path.exists(self.full_pdf_path):
            try:
                with open(self.full_pdf_path, 'a') as f:
                    pass 
                print("[DIALOG_LOG] 1. 파일 점유 확인: 통과 (정상)")
            except IOError:
                print("[DIALOG_LOG] 1. 파일 점유 확인: 실패 (사용 중)")
                QMessageBox.critical(self, "파일 접근 오류", f"⚠️ '{self.file_name}' 파일이 열려 있습니다.")
                return

        print(f"[DIALOG_LOG] 3. 버튼 비활성화 및 시그널 전송 준비")
        self.btn_save.setEnabled(False)
        self.btn_save.setText("⏳ 서버 저장 중...")
        self.btn_save.setStyleSheet("background-color: #bdc3c7; color: white; font-weight: bold; font-size: 13pt; border-radius: 8px;")
        QApplication.processEvents() # UI 강제 업데이트

        # 3. 데이터 추출 및 검증
        try:
            data = self.update_and_get_data()
            print(f"[DIALOG_LOG] 2. 데이터 추출 성공: {data}")
            
            # 💡 [수정 포인트] 데이터가 없으면 경고창 띄우고 버튼 다시 살려주기
            if not self.is_apc and not self.is_sample and (not data['site'] or not data['machines']):
                print("[DIALOG_LOG] 2. 데이터 검증 실패: 필수값 누락")
                QMessageBox.warning(self, "입력 누락", "위치 및 호기 설정을 확인해 주세요.")
                self.btn_save.setEnabled(True)
                self.btn_save.setText("💾 데이터 분류 저장")
                self.btn_save.setStyleSheet("background-color: #e67e22; color: white; font-weight: bold; font-size: 13pt; border-radius: 8px;")
                return 
                
        except Exception as e:
            print(f"[DIALOG_LOG] 2. 데이터 추출 중 에러: {e}")
            self.btn_save.setEnabled(True)
            self.btn_save.setText("💾 데이터 분류 저장")
            return

        # 4. 모든 검증 통과 시 시그널 발생
        self.save_requested.emit(data)
        print(f"[DIALOG_LOG] --- 시그널 발생 완료 ---")

    def update_and_get_data(self):
        InputDialog.last_timing = self.timing_group_btn.checkedId()
        timings = {1: "초물", 2: "중물", 3: "종물"}

        if self.is_sample:
            self.result_data = {
                "site": "",
                "machines": [1],
                "timing_name": timings.get(InputDialog.last_timing, "미정"),
                "timing": InputDialog.last_timing,
                "tool_changes": [""],
                "is_sample": True,
            }
            return self.result_data

        if self.is_apc:
            self.result_data = {
                "site": "",
                "machines": [1],
                "timing_name": timings.get(InputDialog.last_timing, "미정"),
                "timing": InputDialog.last_timing,
                "tool_changes": [""],
            }
            return self.result_data

        current_site = "신관" if self.radio_new.isChecked() else "본관"
        current_machines = [s.value() for s in self.machine_spins]
        InputDialog.history[self.part_name] = {"site": current_site, "machines": current_machines}

        self.result_data = {
            "site": current_site,
            "machines": [v for v in current_machines if v > 0],
            "timing_name": timings.get(InputDialog.last_timing, "미정"),
            "timing": InputDialog.last_timing,
            "tool_changes": [self._get_type_suffix(i) for i, s in enumerate(self.machine_spins) if s.value() > 0]
        }
        return self.result_data

    def _get_type_suffix(self, machine_idx: int) -> str:
        """해당 호기의 품종 구분 문자 반환: 'T' / 'S' / '수' / '' """
        if machine_idx >= len(self.type_groups):
            return ""
        chk_t, chk_s, chk_su = self.type_groups[machine_idx]
        if chk_t.isChecked():  return "T"
        if chk_s.isChecked():  return "S"
        if chk_su.isChecked(): return "수"
        return ""

    def _go_as_sample(self):
        self.is_sample = True
        self.go_to_action_page()

    def go_to_action_page(self):

        # 1. 입력 검증 (APC·측정의뢰품은 호기 없음)
        if not self.is_apc and not self.is_sample:
            current_machines = [s.value() for s in self.machine_spins if s.value() > 0]
            if not current_machines:
                QMessageBox.warning(self, "입력 오류", "⚠️ 최소 하나 이상의 호기 번호(1~35)를 입력해야 합니다.")
                return
            if len(current_machines) != len(set(current_machines)):
                QMessageBox.warning(self, "입력 오류", "⚠️ 중복된 호기 번호가 있습니다.")
                return

        # 2. 데이터 업데이트 및 기존 UI 비우기
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
            elif item.layout(): # 레이아웃인 경우 내부 위젯까지 삭제
                while item.layout().count():
                    sub_item = item.layout().takeAt(0)
                    if sub_item.widget(): sub_item.widget().deleteLater()

        data = self.update_and_get_data()
        self.action_triggered.emit("preview", data, "ALL")

        # 3. 호기별 작업 버튼 생성 로직 (기존 유지)
        mappings = self.config.get('excel_mapping', [])
        num_parts = len(data['machines'])

        for p_idx, m_no in enumerate(data['machines']):
            unit_frame = QFrame()
            unit_frame.setStyleSheet("""
                QFrame { background-color: #fdfdfe; border: 1px solid #dcdde1; border-radius: 10px; margin-bottom: 10px; }
                QLabel { border: none; color: #2c3e50; font-weight: bold; }
            """)
            unit_layout = QVBoxLayout(unit_frame)
            unit_layout.setContentsMargins(15, 10, 15, 15)
            unit_layout.setSpacing(8)

            # 1. 제목 및 요약 멘트 박스
            if self.is_sample:
                unit_layout.addWidget(QLabel("💬 측정의뢰품 요약:"))
            elif self.is_apc:
                unit_layout.addWidget(QLabel("💬 APC 요약:"))
            else:
                unit_layout.addWidget(QLabel(f"💬 {m_no}호기 요약:"))
            
            report_edit = QTextEdit()
            report_edit.setReadOnly(True)
            
            # ⭐ 핵심: main.py에서 이 위젯을 찾기 위해 고유 이름을 부여합니다.
            report_edit.setObjectName(f"report_edit_{p_idx}")

            report_edit.setMinimumHeight(60)
            report_edit.setMaximumHeight(100)
            report_edit.setStyleSheet("background-color: #ffffff; border: 1px solid #ebedef; padding: 5px;")
            unit_layout.addWidget(report_edit)

            # 특이사항 알림 영역 (초기 숨김)
            alert_label = QLabel()
            alert_label.setObjectName(f"alert_area_{p_idx}")
            alert_label.setWordWrap(True)
            alert_label.setStyleSheet(
                "background-color: #fff3cd; color: #856404; font-weight: bold; "
                "border: 2px solid #ffc107; border-radius: 6px; padding: 8px;"
            )
            alert_label.setVisible(False)
            unit_layout.addWidget(alert_label)

            row = QHBoxLayout()
            excel_btns = []

            if self.is_sample:
                # 측정의뢰품: 엑셀 버튼 비활성화
                for b_idx, mapping in enumerate(mappings or [None]):
                    if mapping is None:
                        break
                    btn = QPushButton(f"📊 {mapping.get('block_name', f'블록{b_idx+1}')}")
                    btn.setMinimumWidth(160)
                    btn.setFixedHeight(45)
                    btn.setEnabled(False)
                    btn.setStyleSheet("background-color: #bdc3c7; color: #7f8c8d; font-weight: bold; border-radius: 5px;")
                    row.addWidget(btn)
            elif num_parts == 1:
                for b_idx, mapping in enumerate(mappings):
                    btn = QPushButton(f"📊 {mapping.get('block_name', f'블록{b_idx+1}')}")
                    btn.setMinimumWidth(160)
                    btn.setFixedHeight(45)
                    btn.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; border-radius: 5px;")
                    btn.clicked.connect(lambda chk, pi=0, bi=b_idx, b=btn: self.copy_with_feedback(pi, bi, b, data))
                    row.addWidget(btn)
                    excel_btns.append(btn)
            else:
                if p_idx < len(mappings):
                    btn = QPushButton(f"📊 {mappings[p_idx].get('block_name', f'{p_idx+1}번째')}")
                    btn.setMinimumWidth(200)
                    btn.setFixedHeight(45)
                    btn.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; border-radius: 5px;")
                    btn.clicked.connect(lambda chk, pi=p_idx, bi=p_idx, b=btn: self.copy_with_feedback(pi, bi, b, data))
                    row.addWidget(btn)
                    excel_btns.append(btn)

            btn_ka = QPushButton("💬 카톡")
            btn_ka.setFixedSize(90, 45)
            btn_ka.setStyleSheet("background-color: #f1c40f; color: black; font-weight: bold; border-radius: 5px;")
            btn_ka.clicked.connect(lambda chk, pi=p_idx, b=btn_ka: self.copy_with_feedback(pi, None, b, data, is_kakao=True))
            row.addWidget(btn_ka)

            unit_layout.addLayout(row)
            
            self.content_layout.addWidget(unit_frame)

        if self.is_sample:
            self.btn_save.setText("💾 PDF 저장")

        self.stack.setCurrentIndex(1)

    def copy_with_feedback(self, p_idx, b_idx, btn, data, is_kakao=False):
        # 실제 동작 트리거
        if is_kakao:
            self.action_triggered.emit("kakao", data, p_idx)
        else:
            self.action_triggered.emit("excel", data, (p_idx, b_idx))
        
        # 버튼 피드백 설정
        original_text = btn.text()
        original_style = btn.styleSheet()
        
        btn.setText("✅ 완료")
        # 엑셀(초록)이나 카톡(노랑) 배경색은 유지하고 텍스트만 변경
        if is_kakao:
            btn.setStyleSheet("background-color: #f1c40f; color: #2c3e50; font-weight: bold; border-radius: 5px;")
        else:
            btn.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; border-radius: 5px;")
        
        # 원래대로 복구
        QTimer.singleShot(500, lambda: (
            btn.setText(original_text),
            btn.setStyleSheet(original_style)
        ))

    # 💡 [여기서부터 새로 추가/변경] 안 쓰는 final_accept는 지우고 아래 함수를 넣으세요!
    def mark_as_saved(self):
        """저장이 완료되었을 때 창을 끄지 않고 버튼 상태만 완료로 변경"""
        self._is_saved = True
        self.btn_save.setText("✅ 저장 완료")
        self.btn_save.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; font-size: 13pt; border-radius: 8px;")

        # 이미 이동된 파일을 또 저장하지 못하도록 버튼을 비활성화 (뒤로 가기로 재활성화 가능)
        self.btn_save.setEnabled(False)

    def _go_back_to_page1(self):
        """뒤로 가기 — 이미 저장한 경우 재저장 의사를 확인하고 버튼/모드 완전 초기화"""
        if self._is_saved:
            reply = QMessageBox.question(
                self, "정보 수정 후 재저장",
                "이미 저장이 완료된 데이터입니다.\n"
                "정보를 수정하고 다시 저장하면 기존 파일이 새 이름으로 이동됩니다.\n\n"
                "정보를 수정하시겠습니까?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
            self._is_saved = False

        # 측정의뢰품 모드 해제 + 저장 버튼 완전 초기화
        self.is_sample = False
        self.btn_save.setText("💾 데이터 분류 저장")
        self.btn_save.setStyleSheet(
            "background-color: #e67e22; color: white; font-weight: bold; font-size: 13pt; border-radius: 8px;"
        )
        self.btn_save.setEnabled(True)
        self.stack.setCurrentIndex(0)

    def _unsaved_warning(self) -> bool:
        """저장 없이 닫으려 할 때 경고창. True → 닫기 허용, False → 취소."""
        if self._saved_final_path:
            return True  # 한 번이라도 저장된 적 있음 → 경고 불필요
        reply = QMessageBox.warning(
            self, "저장하지 않고 종료",
            f"⚠️ '{self.file_name}' 파일이 아직 저장되지 않았습니다.\n\n"
            "창을 닫으면 PDF가 watch_input 폴더에 그대로 남아\n"
            "수동으로 처리가 필요합니다.\n\n"
            "그래도 종료하시겠습니까?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        return reply == QMessageBox.Yes

    def _handle_close(self):
        """'작업 종료' 버튼 — 미저장 시 경고 후 닫기"""
        if self._unsaved_warning():
            self.accept()

    def set_special_alerts(self, p_idx: int, alerts):
        """특이사항 알림 표시 (alerts: 메시지 문자열 리스트)"""
        widget = self.findChild(QLabel, f"alert_area_{p_idx}")
        if widget is None:
            return
        if alerts:
            widget.setText("\n\n".join(alerts))
            widget.setVisible(True)
        else:
            widget.setVisible(False)

    def closeEvent(self, event):
        """X 버튼 — 미저장 시 경고 후 닫기"""
        if self._unsaved_warning():
            event.accept()
        else:
            event.ignore()

    def _confirm_discard(self):
        reply = QMessageBox.question(
            self, "측정 불량 파기",
            f"⚠️ '{self.file_name}' 파일을 삭제하고 작업을 취소하시겠습니까?\n\n파일이 영구 삭제되며 복구할 수 없습니다.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            # PDF가 다른 프로그램에서 열려있으면 삭제 불가 → 경고 후 창 유지
            pdf_path = self.full_pdf_path
            if pdf_path and os.path.exists(pdf_path):
                try:
                    with open(pdf_path, 'r+b'):
                        pass
                except (PermissionError, IOError):
                    QMessageBox.warning(
                        self, "파기 불가",
                        f"📄 '{self.file_name}' 파일이 다른 프로그램에서 열려 있습니다.\n"
                        "뷰어를 완전히 종료한 후 다시 시도해 주세요."
                    )
                    return
            self.discard_requested.emit()
            self.reject()