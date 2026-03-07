# UI/interview_panel.py
"""
面试主界面 — 重构版
使用统一组件库 UI/components.py，所有气泡/样式统一
事件逻辑保持不变，仅重构 UI 层
"""
import json
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QTextEdit, QScrollArea, QFrame,
    QMessageBox, QSizePolicy, QGraphicsDropShadowEffect,
)
from PySide6.QtCore import Qt, Signal, QThread, QObject, QTimer, QEvent
from PySide6.QtGui import QColor, QKeyEvent

from UI.components import (
    Theme as T, ChatBubble, ScoreCardBubble, TypingIndicator,
    ButtonFactory, GLOBAL_QSS, input_qss, combo_qss,
)


# ── 后台工作线程（逻辑不变） ──────────────────────────────────────────────────

class InterviewWorker(QObject):
    request_start  = Signal(str, int)
    request_answer = Signal(str)
    request_finish = Signal()

    first_question_ready = Signal(str)
    answer_result_ready  = Signal(dict)
    report_ready         = Signal(str)
    error_occurred       = Signal(str)
    session_started      = Signal(int)

    def __init__(self, engine, db):
        super().__init__()
        self.engine = engine
        self.db = db
        self.session_id = None

    def on_start_requested(self, name: str, job_id: int):
        try:
            row = self.db.fetchone("SELECT id FROM student WHERE name=?", (name,))
            if row:
                student_id = row[0]
            else:
                cur = self.db.execute(
                    "INSERT INTO student (name, created_at) VALUES (?,?)",
                    (name, datetime.now().isoformat()),
                )
                student_id = cur.lastrowid
            self.session_id = self.engine.start_session(student_id, job_id)
            self.session_started.emit(self.session_id)
            q = self.engine.get_first_question(self.session_id)
            self.first_question_ready.emit(q)
        except Exception as e:
            self.error_occurred.emit(str(e))

    def on_answer_requested(self, answer: str):
        try:
            if self.session_id is None:
                raise RuntimeError("Session not initialized")
            result = self.engine.submit_answer(self.session_id, answer)
            self.answer_result_ready.emit(result)
        except Exception as e:
            self.error_occurred.emit(str(e))

    def on_finish_requested(self):
        try:
            if self.session_id is None:
                raise RuntimeError("Session not initialized")
            report = self.engine.finish_session(self.session_id)
            self.report_ready.emit(report)
        except Exception as e:
            self.error_occurred.emit(str(e))


# ── 主面板 ────────────────────────────────────────────────────────────────────

class InterviewPanel(QWidget):
    def __init__(self, db, engine, parent=None):
        super().__init__(parent)
        self.db = db
        self.engine = engine
        self._session_id: int | None = None

        # 线程
        self._worker = InterviewWorker(engine, db)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)

        self._worker.request_start.connect(self._worker.on_start_requested)
        self._worker.request_answer.connect(self._worker.on_answer_requested)
        self._worker.request_finish.connect(self._worker.on_finish_requested)

        self._worker.first_question_ready.connect(self._on_first_question)
        self._worker.answer_result_ready.connect(self._on_answer_result)
        self._worker.report_ready.connect(self._on_report)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.session_started.connect(self._on_session_started)

        self._thread.start()
        self._build_ui()

    # ── UI 构建 ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setStyleSheet(GLOBAL_QSS + input_qss() + combo_qss())

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())
        root.addWidget(self._build_chat_area(), stretch=1)
        root.addWidget(self._build_footer())

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setFixedHeight(60)
        header.setStyleSheet(f"""
            QFrame {{
                background: {T.SURFACE};
                border-bottom: 1px solid {T.BORDER};
            }}
        """)
        lay = QHBoxLayout(header)
        lay.setContentsMargins(22, 0, 22, 0)
        lay.setSpacing(12)

        # 标题
        title = QLabel("🎯  模拟面试")
        title.setStyleSheet(f"font-size: 15px; font-weight: 800; color: {T.TEXT}; font-family: {T.FONT};")
        lay.addWidget(title)
        lay.addSpacing(20)

        # 姓名输入
        name_lbl = QLabel("姓名")
        name_lbl.setStyleSheet(f"color: {T.TEXT_DIM}; font-size: 12px;")
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("请输入姓名")
        self.name_input.setFixedSize(130, 34)

        # 岗位选择
        job_lbl = QLabel("岗位")
        job_lbl.setStyleSheet(f"color: {T.TEXT_DIM}; font-size: 12px;")
        self.job_combo = QComboBox()
        self.job_combo.setFixedSize(170, 34)
        self._load_jobs()

        lay.addWidget(name_lbl)
        lay.addWidget(self.name_input)
        lay.addSpacing(8)
        lay.addWidget(job_lbl)
        lay.addWidget(self.job_combo)
        lay.addStretch()

        # 操作按钮
        self.start_btn = ButtonFactory.solid("开始面试", T.NEON, height=34)
        self.start_btn.setFixedWidth(90)
        self.start_btn.clicked.connect(self._start_interview)

        self.finish_btn = ButtonFactory.solid("结束面试", T.GREEN, height=34)
        self.finish_btn.setFixedWidth(90)
        self.finish_btn.setEnabled(False)
        self.finish_btn.clicked.connect(self._finish_interview)

        lay.addWidget(self.start_btn)
        lay.addWidget(self.finish_btn)
        return header

    def _build_chat_area(self) -> QScrollArea:
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet(f"QScrollArea {{ background: {T.BG}; border: none; }}")

        self._chat_container = QWidget()
        self._chat_container.setStyleSheet(f"background: {T.BG};")
        self._chat_layout = QVBoxLayout(self._chat_container)
        self._chat_layout.setContentsMargins(22, 20, 22, 20)
        self._chat_layout.setSpacing(12)
        self._chat_layout.addStretch()

        # 欢迎提示
        welcome = ChatBubble("system", "请输入姓名、选择岗位，然后点击「开始面试」")
        self._chat_layout.insertWidget(0, welcome)

        self._scroll.setWidget(self._chat_container)
        return self._scroll

    def _build_footer(self) -> QFrame:
        footer = QFrame()
        footer.setFixedHeight(100)
        footer.setStyleSheet(f"""
            QFrame {{
                background: {T.SURFACE};
                border-top: 1px solid {T.BORDER};
            }}
        """)
        f_lay = QVBoxLayout(footer)
        f_lay.setContentsMargins(22, 12, 22, 12)
        f_lay.setSpacing(8)

        # 状态栏
        self.status_lbl = QLabel("准备就绪")
        self.status_lbl.setStyleSheet(f"""
            color: {T.TEXT_DIM}; font-size: 12px;
            font-family: {T.FONT};
        """)
        f_lay.addWidget(self.status_lbl)

        # 输入行
        input_row = QHBoxLayout()
        input_row.setSpacing(10)

        self.answer_input = QTextEdit()
        self.answer_input.setPlaceholderText("输入你的回答... (Ctrl+Enter 发送)")
        self.answer_input.setFixedHeight(54)
        self.answer_input.setEnabled(False)
        self.answer_input.installEventFilter(self)

        self.send_btn = ButtonFactory.solid("发送", T.NEON, height=54)
        self.send_btn.setFixedWidth(80)
        self.send_btn.setEnabled(False)
        self.send_btn.clicked.connect(self._send_answer)

        input_row.addWidget(self.answer_input)
        input_row.addWidget(self.send_btn)
        f_lay.addLayout(input_row)
        return footer

    # ── 逻辑控制（与原版相同） ────────────────────────────────────────────────

    def _load_jobs(self):
        self.job_combo.clear()
        try:
            rows = self.db.fetchall("SELECT id, name FROM job_position")
            for jid, name in rows:
                self.job_combo.addItem(name, jid)
        except Exception:
            self.job_combo.addItem("暂无岗位", 0)

    def _start_interview(self):
        name = self.name_input.text().strip()
        if not name:
            self._show_toast("请输入姓名")
            return
        if self.job_combo.count() == 0 or self.job_combo.currentData() is None:
            self._show_toast("请选择岗位")
            return

        job_id = self.job_combo.currentData()
        self._set_loading(True, "正在初始化面试会话...")
        self.start_btn.setEnabled(False)
        self.name_input.setEnabled(False)
        self.job_combo.setEnabled(False)
        self._clear_chat()
        self._worker.request_start.emit(name, job_id)

    def _on_session_started(self, session_id: int):
        self._session_id = session_id

    def _send_answer(self):
        answer = self.answer_input.toPlainText().strip()
        if not answer:
            return
        self.answer_input.clear()
        self._add_bubble("user", answer)
        self._set_loading(True, "AI 正在思考...")
        self._set_input_enabled(False)
        self._worker.request_answer.emit(answer)

    def _finish_interview(self):
        self._set_loading(True, "正在生成最终报告...")
        self._set_input_enabled(False)
        self.finish_btn.setEnabled(False)
        self._worker.request_finish.emit()

    # ── 信号槽 ────────────────────────────────────────────────────────────────

    def _on_first_question(self, question: str):
        self._set_loading(False)
        self._add_bubble("ai", question)
        self._set_input_enabled(True)
        self.finish_btn.setEnabled(True)
        self._add_system_msg("面试已开始，加油！🚀")

    def _on_answer_result(self, result: dict):
        self._set_loading(False)
        eval_r = result.get("eval")
        ai_reply = result.get("ai_reply", "")
        is_finished = result.get("is_finished", False)

        if eval_r:
            self._add_score_bubble(eval_r)
        if ai_reply:
            self._add_bubble("ai", ai_reply)

        if is_finished:
            self._set_input_enabled(False)
            self.status_lbl.setText("题目已完成，请点击「结束面试」生成报告")
        else:
            self._set_input_enabled(True)

    def _on_report(self, report: str):
        self._set_loading(False)
        self._add_system_msg("━━━━━━  面试结束  ━━━━━━")
        self._add_bubble("ai", report)
        self.status_lbl.setText("面试完成 ✓")
        self.start_btn.setEnabled(True)
        self.name_input.setEnabled(True)
        self.job_combo.setEnabled(True)
        self._session_id = None

    def _on_error(self, msg: str):
        self._set_loading(False)
        self._set_input_enabled(True)
        self.start_btn.setEnabled(True)
        self.name_input.setEnabled(True)
        self.job_combo.setEnabled(True)
        QMessageBox.critical(self, "错误", f"发生错误：{msg}")

    # ── UI 辅助 ───────────────────────────────────────────────────────────────

    def _add_bubble(self, role: str, text: str):
        bubble = ChatBubble(role, text)
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, bubble)
        self._scroll_to_bottom()

    def _add_score_bubble(self, eval_result):
        bubble = ScoreCardBubble(eval_result)
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, bubble)
        self._scroll_to_bottom()

    def _add_system_msg(self, text: str):
        bubble = ChatBubble("system", text)
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, bubble)

    def _clear_chat(self):
        while self._chat_layout.count() > 1:
            item = self._chat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _scroll_to_bottom(self):
        QTimer.singleShot(50, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        ))

    def _set_loading(self, loading: bool, msg: str = ""):
        if loading:
            self.status_lbl.setText(f"⏳  {msg}")
            self.status_lbl.setStyleSheet(f"color: {T.NEON}; font-size: 12px; font-weight: 600;")
        else:
            self.status_lbl.setStyleSheet(f"color: {T.TEXT_DIM}; font-size: 12px;")

    def _set_input_enabled(self, enabled: bool):
        self.answer_input.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)
        if enabled:
            self.answer_input.setFocus()

    def _show_toast(self, msg: str):
        orig = self.status_lbl.text()
        self.status_lbl.setText(f"⚠️  {msg}")
        self.status_lbl.setStyleSheet(f"color: {T.ACCENT}; font-weight: bold; font-size: 12px;")
        QTimer.singleShot(2000, lambda: (
            self.status_lbl.setText(orig),
            self.status_lbl.setStyleSheet(f"color: {T.TEXT_DIM}; font-size: 12px;"),
        ))

    def eventFilter(self, obj, event):
        if obj is self.answer_input and event.type() == QEvent.KeyPress:
            ke: QKeyEvent = event
            if ke.key() == Qt.Key_Return and ke.modifiers() == Qt.ControlModifier:
                if self.send_btn.isEnabled():
                    self._send_answer()
                return True
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        self._thread.quit()
        self._thread.wait()
        super().closeEvent(event)