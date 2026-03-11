# UI/interview_panel.py
"""
面试主界面 — 流式重构版
对接 InterviewEngine 的流式接口（get_first_question_stream /
submit_answer_stream / finish_session_stream），实现：
  - 真实逐 token 流式渲染（与 agent_panel 同构）
  - 新内容发布时自动滚动到底部
  - 用户已滚离底部时显示「↓ 新消息」浮动提示
"""
import json
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QTextEdit, QScrollArea, QFrame,
    QMessageBox, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QThread, QObject, QTimer, QEvent
from PySide6.QtGui import QColor, QKeyEvent

from UI.components import (
    Theme as T, ChatBubble, ScoreCardBubble, TypingIndicator, StreamSignals,
    ButtonFactory, GLOBAL_QSS, input_qss, combo_qss,
)


# ══════════════════════════════════════════════════════════════════════════════
# 后台工作线程（流式版）
# ══════════════════════════════════════════════════════════════════════════════

class InterviewWorker(QObject):
    """
    所有耗时操作（含流式 IO）在独立线程运行，通过 Signal 与 UI 通信。

    流式协议（与 interview_engine 约定）：
      __EVAL__:{json}\\n      → 评分数据
      __IS_FINISHED__\\n      → 本轮结束标记
      __FINISHED__\\n         → 面试已全部结束
      __SCORE__:{float}\\n    → 报告总分
      __ERROR__:{msg}\\n      → 错误
      其余                   → 正常文本 token
    """

    # ── 请求信号（主线程 → Worker）────────────────────────────────────────────
    request_start  = Signal(str, int)   # name, job_id
    request_answer = Signal(str)        # answer text
    request_finish = Signal()

    # ── 结果信号（Worker → 主线程）────────────────────────────────────────────
    session_started     = Signal(int)       # session_id
    stream_chunk        = Signal(str)       # 普通文本 token
    eval_received       = Signal(dict)      # 评分数据
    is_finished_flag    = Signal()          # 本轮已是最后一轮
    all_finished        = Signal()          # 面试全部完毕（无更多题目）
    score_received      = Signal(float)     # 报告总分
    stream_done         = Signal(str)       # 流结束，携带阶段标识
    error_occurred      = Signal(str)

    # 阶段标识常量
    PHASE_FIRST_Q = "first_q"
    PHASE_ANSWER  = "answer"
    PHASE_REPORT  = "report"

    def __init__(self, engine, db):
        super().__init__()
        self.engine = engine
        self.db = db
        self.session_id: int | None = None
        self._is_finished = False          # 本次 submit_answer 是否是最后一轮

    # ── 请求处理 ──────────────────────────────────────────────────────────────

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

            # ── 流式获取第一问 ──────────────────────────────────────────────
            parts: list[str] = []
            for token in self.engine.get_first_question_stream(self.session_id):
                parts.append(token)
                self.stream_chunk.emit(token)

            full_text = "".join(parts)
            self.engine.confirm_first_question(self.session_id, full_text)
            self.stream_done.emit(self.PHASE_FIRST_Q)

        except Exception as e:
            self.error_occurred.emit(str(e))

    def on_answer_requested(self, answer: str):
        if self.session_id is None:
            self.error_occurred.emit("Session not initialized")
            return
        try:
            ai_parts: list[str] = []
            eval_data: dict | None = None
            self._is_finished = False

            for token in self.engine.submit_answer_stream(self.session_id, answer):
                # ── 协议解析 ────────────────────────────────────────────────
                if token.startswith("__EVAL__:"):
                    eval_data = json.loads(token[len("__EVAL__:"):].strip())
                    self.eval_received.emit(eval_data)

                elif token == "__IS_FINISHED__\n":
                    self._is_finished = True
                    self.is_finished_flag.emit()

                elif token == "__FINISHED__\n":
                    self.all_finished.emit()
                    self.stream_done.emit(self.PHASE_ANSWER)
                    return

                elif token.startswith("__ERROR__:"):
                    self.error_occurred.emit(token[len("__ERROR__:"):].strip())
                    return

                else:
                    ai_parts.append(token)
                    self.stream_chunk.emit(token)

            ai_reply = "".join(ai_parts)
            self.engine.confirm_answer(self.session_id, ai_reply, self._is_finished)
            self.stream_done.emit(self.PHASE_ANSWER)

        except Exception as e:
            self.error_occurred.emit(str(e))

    def on_finish_requested(self):
        if self.session_id is None:
            self.error_occurred.emit("Session not initialized")
            return
        try:
            overall_score = 0.0
            report_parts: list[str] = []

            for token in self.engine.finish_session_stream(self.session_id):
                if token.startswith("__SCORE__:"):
                    overall_score = float(token[len("__SCORE__:"):].strip())
                    self.score_received.emit(overall_score)
                else:
                    report_parts.append(token)
                    self.stream_chunk.emit(token)

            report_text = "".join(report_parts)
            self.engine.confirm_finish(self.session_id, overall_score, report_text)
            self.stream_done.emit(self.PHASE_REPORT)

        except Exception as e:
            self.error_occurred.emit(str(e))


# ══════════════════════════════════════════════════════════════════════════════
# 「↓ 新消息」浮动提示按钮
# ══════════════════════════════════════════════════════════════════════════════

class NewMessageToast(QPushButton):
    """
    悬浮在聊天区右下角的「↓ 新消息」提示。
    仅当用户滚离底部 且 有新内容时显示。
    """

    def __init__(self, parent: QWidget):
        super().__init__("↓  新消息", parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(110, 34)
        self._apply_style(False)
        self.hide()

    def _apply_style(self, pulsing: bool):
        base = f"""
            QPushButton {{
                background: {T.NEON};
                color: #0a0a0f;
                border: none;
                border-radius: 17px;
                font-size: 12px;
                font-weight: 700;
                font-family: {T.FONT};
                padding: 0 12px;
            }}
            QPushButton:hover {{
                background: {T.PURPLE};
                color: #ffffff;
            }}
        """
        self.setStyleSheet(base)

    def update_position(self, parent_rect):
        """紧贴父 QScrollArea 右下角"""
        x = parent_rect.width() - self.width() - 18
        y = parent_rect.height() - self.height() - 14
        self.move(x, y)
        self.raise_()


# ══════════════════════════════════════════════════════════════════════════════
# 主面板
# ══════════════════════════════════════════════════════════════════════════════

class InterviewPanel(QWidget):
    def __init__(self, db, engine, parent=None):
        super().__init__(parent)
        self.db = db
        self.engine = engine
        self._session_id: int | None = None

        # ── 流式状态 ──────────────────────────────────────────────────────────
        self._is_streaming = False
        self._current_ai_bubble: ChatBubble | None = None
        self._typing_indicator: TypingIndicator | None = None
        self._stream_phase: str = ""          # first_q / answer / report
        self._pending_is_finished = False     # 本轮是否是最后一轮

        # ── 滚动状态 ──────────────────────────────────────────────────────────
        self._user_scrolled_up = False        # 用户是否手动滚离了底部
        self._has_new_content = False         # 是否有未读新内容

        # ── 后台线程 ──────────────────────────────────────────────────────────
        self._worker = InterviewWorker(engine, db)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)

        self._worker.request_start.connect(self._worker.on_start_requested)
        self._worker.request_answer.connect(self._worker.on_answer_requested)
        self._worker.request_finish.connect(self._worker.on_finish_requested)

        self._worker.session_started.connect(self._on_session_started)
        self._worker.stream_chunk.connect(self._on_chunk)
        self._worker.eval_received.connect(self._on_eval_received)
        self._worker.is_finished_flag.connect(self._on_is_finished_flag)
        self._worker.all_finished.connect(self._on_all_finished)
        self._worker.score_received.connect(self._on_score_received)
        self._worker.stream_done.connect(self._on_stream_done)
        self._worker.error_occurred.connect(self._on_error)

        self._thread.start()
        self._build_ui()

    # ══════════════════════════════════════════════════════════════════════════
    # UI 构建
    # ══════════════════════════════════════════════════════════════════════════

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

        title = QLabel("🎯  模拟面试")
        title.setStyleSheet(
            f"font-size: 15px; font-weight: 800; color: {T.TEXT}; font-family: {T.FONT};"
        )
        lay.addWidget(title)
        lay.addSpacing(20)

        name_lbl = QLabel("姓名")
        name_lbl.setStyleSheet(f"color: {T.TEXT_DIM}; font-size: 12px;")
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("请输入姓名")
        self.name_input.setFixedSize(130, 34)

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
        self._scroll.setStyleSheet(
            f"QScrollArea {{ background: {T.BG}; border: none; }}"
        )

        self._chat_container = QWidget()
        self._chat_container.setStyleSheet(f"background: {T.BG};")
        self._chat_layout = QVBoxLayout(self._chat_container)
        self._chat_layout.setContentsMargins(22, 20, 22, 20)
        self._chat_layout.setSpacing(12)
        self._chat_layout.addStretch()

        welcome = ChatBubble("system", "请输入姓名、选择岗位，然后点击「开始面试」")
        self._chat_layout.insertWidget(0, welcome)

        self._scroll.setWidget(self._chat_container)

        # ── 监听滚动条变化 ────────────────────────────────────────────────────
        self._scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)

        # ── 「新消息」浮动 Toast ───────────────────────────────────────────────
        self._toast = NewMessageToast(self._scroll)
        self._toast.clicked.connect(self._jump_to_bottom)
        self._scroll.resizeEvent = self._on_scroll_resize   # type: ignore[method-assign]

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

        self.status_lbl = QLabel("准备就绪")
        self.status_lbl.setStyleSheet(
            f"color: {T.TEXT_DIM}; font-size: 12px; font-family: {T.FONT};"
        )
        f_lay.addWidget(self.status_lbl)

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

    # ══════════════════════════════════════════════════════════════════════════
    # 流式 chunk 处理（与 agent_panel._on_chunk 同构）
    # ══════════════════════════════════════════════════════════════════════════

    def _on_chunk(self, chunk: str):
        """接收普通文本 token，追加到当前 AI 气泡"""
        # 移除打字指示器（首个 token 时）
        if self._typing_indicator is not None:
            self._remove_typing_indicator()

        # 首个 token → 创建新气泡
        if self._current_ai_bubble is None:
            role = "ai" if self._stream_phase != InterviewWorker.PHASE_REPORT else "ai"
            self._current_ai_bubble = ChatBubble("ai")
            self._chat_layout.insertWidget(
                self._chat_layout.count() - 1, self._current_ai_bubble
            )

        self._current_ai_bubble.append_chunk(chunk)
        self._notify_new_content()

    # ══════════════════════════════════════════════════════════════════════════
    # 各类信号槽
    # ══════════════════════════════════════════════════════════════════════════

    def _on_session_started(self, session_id: int):
        self._session_id = session_id
        self._stream_phase = InterviewWorker.PHASE_FIRST_Q
        self._is_streaming = True
        self._add_typing_indicator()
        self._set_loading(True, "AI 面试官正在出题...")

    def _on_eval_received(self, data: dict):
        """
        收到评分数据 → 保证插入顺序：用户回答 → 评分卡 → typing indicator → AI气泡

        流程：
          1. 暂时摘下 typing indicator（从布局移除但不销毁）
          2. 插入评分卡气泡
          3. 把 typing indicator 重新挂回布局末尾占位
        这样后续 _on_chunk 首 token 到来时，撤掉 typing indicator、创建
        AI 气泡，最终顺序就是：评分卡 → AI流式气泡 ✓
        """

        class _FakeEval:
            def __init__(self, d):
                # ScoreCardBubble 期望的字段名（*_score + suggestion）
                self.overall_score  = d.get("overall_score",  d.get("overall",  0))
                self.tech_score     = d.get("tech_score",     d.get("tech",     0))
                self.logic_score    = d.get("logic_score",    d.get("logic",    0))
                self.depth_score    = d.get("depth_score",    d.get("depth",    0))
                self.clarity_score  = d.get("clarity_score",  d.get("clarity",  0))
                self.suggestion     = d.get("suggestion",     d.get("comment",  ""))
                # 裸名别名（兼容其他可能的访问方式）
                self.overall = self.overall_score
                self.tech    = self.tech_score
                self.logic   = self.logic_score
                self.depth   = self.depth_score
                self.clarity = self.clarity_score
                self.comment = self.suggestion
            def to_dict(self): return data

        # ── 1. 暂时摘下 typing indicator ──────────────────────────────────────
        if self._typing_indicator is not None:
            self._chat_layout.removeWidget(self._typing_indicator)
            # 不 deleteLater，后面还要重新插回去

        # ── 2. 插入评分卡 ──────────────────────────────────────────────────────
        self._add_score_bubble(_FakeEval(data))

        # ── 3. 把 typing indicator 重新挂到末尾占位 ───────────────────────────
        if self._typing_indicator is not None:
            self._chat_layout.insertWidget(
                self._chat_layout.count() - 1, self._typing_indicator
            )
            self._notify_new_content()

    def _on_is_finished_flag(self):
        self._pending_is_finished = True

    def _on_all_finished(self):
        """submit_answer 返回 __FINISHED__：面试已无更多题目"""
        self._add_system_msg("面试已结束，请点击「结束面试」查看报告。")
        self.status_lbl.setText("题目已完成，请点击「结束面试」生成报告")
        self._set_input_enabled(False)

    def _on_score_received(self, score: float):
        self._add_system_msg(f"━━  综合得分：{score}/10  ━━")

    def _on_stream_done(self, phase: str):
        """流结束：根据阶段决定后续 UI 状态"""
        # 清理流式气泡引用
        self._current_ai_bubble = None
        self._is_streaming = False

        if phase == InterviewWorker.PHASE_FIRST_Q:
            self._set_loading(False)
            self._set_input_enabled(True)
            self.finish_btn.setEnabled(True)
            self._add_system_msg("面试已开始，加油！🚀")

        elif phase == InterviewWorker.PHASE_ANSWER:
            self._set_loading(False)
            if self._pending_is_finished:
                self._pending_is_finished = False
                self._set_input_enabled(False)
                self.status_lbl.setText("题目已完成，请点击「结束面试」生成报告")
            else:
                self._set_input_enabled(True)

        elif phase == InterviewWorker.PHASE_REPORT:
            self._set_loading(False)
            self._add_system_msg("面试完成 ✓")
            self.status_lbl.setText("面试完成 ✓")
            self.start_btn.setEnabled(True)
            self.name_input.setEnabled(True)
            self.job_combo.setEnabled(True)
            self._session_id = None

    def _on_error(self, msg: str):
        self._remove_typing_indicator()
        self._current_ai_bubble = None
        self._is_streaming = False
        self._set_loading(False)
        self._set_input_enabled(True)
        self.start_btn.setEnabled(True)
        self.name_input.setEnabled(True)
        self.job_combo.setEnabled(True)
        QMessageBox.critical(self, "错误", f"发生错误：{msg}")

    # ══════════════════════════════════════════════════════════════════════════
    # 逻辑控制
    # ══════════════════════════════════════════════════════════════════════════

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
        self.start_btn.setEnabled(False)
        self.name_input.setEnabled(False)
        self.job_combo.setEnabled(False)
        self._clear_chat()
        # 重置滚动状态
        self._user_scrolled_up = False
        self._has_new_content = False
        self._toast.hide()

        self._worker.request_start.emit(name, job_id)

    def _send_answer(self):
        if self._is_streaming:
            return
        answer = self.answer_input.toPlainText().strip()
        if not answer:
            return
        self.answer_input.clear()
        self._add_bubble("user", answer)
        self._pending_is_finished = False
        self._stream_phase = InterviewWorker.PHASE_ANSWER
        self._is_streaming = True
        self._add_typing_indicator()
        self._set_loading(True, "AI 正在思考...")
        self._set_input_enabled(False)
        self._worker.request_answer.emit(answer)

    def _finish_interview(self):
        self._set_loading(True, "正在生成最终报告...")
        self._set_input_enabled(False)
        self.finish_btn.setEnabled(False)
        self._stream_phase = InterviewWorker.PHASE_REPORT
        self._is_streaming = True
        self._add_system_msg("━━━━━━  面试结束，正在生成报告  ━━━━━━")
        self._add_typing_indicator()
        self._worker.request_finish.emit()

    # ══════════════════════════════════════════════════════════════════════════
    # 滚动 & 「新消息」Toast 逻辑
    # ══════════════════════════════════════════════════════════════════════════

    def _on_scroll_changed(self, value: int):
        """滚动条值变化时，判断用户是否在底部"""
        sb = self._scroll.verticalScrollBar()
        at_bottom = value >= sb.maximum() - 10
        if at_bottom:
            # 回到底部 → 清除提示
            self._user_scrolled_up = False
            self._has_new_content = False
            self._toast.hide()
        else:
            self._user_scrolled_up = True

    def _notify_new_content(self):
        """
        有新内容到来时：
          - 如果用户在底部 → 自动滚到底部
          - 如果用户滚离底部 → 显示 Toast 提示
        """
        if self._user_scrolled_up:
            self._has_new_content = True
            self._toast.update_position(self._scroll.rect())
            self._toast.show()
            self._toast.raise_()
        else:
            self._scroll_to_bottom()

    def _jump_to_bottom(self):
        """点击 Toast → 立即滚到底部并隐藏 Toast"""
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())
        self._user_scrolled_up = False
        self._has_new_content = False
        self._toast.hide()

    def _scroll_to_bottom(self):
        QTimer.singleShot(50, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        ))

    def _on_scroll_resize(self, event):
        """QScrollArea resize 时更新 Toast 位置"""
        QScrollArea.resizeEvent(self._scroll, event)
        if self._toast.isVisible():
            self._toast.update_position(self._scroll.rect())

    # ══════════════════════════════════════════════════════════════════════════
    # UI 辅助
    # ══════════════════════════════════════════════════════════════════════════

    def _add_typing_indicator(self):
        if self._typing_indicator is not None:
            return
        self._typing_indicator = TypingIndicator()
        self._chat_layout.insertWidget(
            self._chat_layout.count() - 1, self._typing_indicator
        )
        self._scroll_to_bottom()

    def _remove_typing_indicator(self):
        if self._typing_indicator is None:
            return
        self._chat_layout.removeWidget(self._typing_indicator)
        self._typing_indicator.stop()
        self._typing_indicator.deleteLater()
        self._typing_indicator = None

    def _add_bubble(self, role: str, text: str):
        bubble = ChatBubble(role, text)
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, bubble)
        self._notify_new_content()

    def _add_score_bubble(self, eval_result):
        bubble = ScoreCardBubble(eval_result)
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, bubble)
        self._notify_new_content()

    def _add_system_msg(self, text: str):
        bubble = ChatBubble("system", text)
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, bubble)
        self._notify_new_content()

    def _clear_chat(self):
        while self._chat_layout.count() > 1:
            item = self._chat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _set_loading(self, loading: bool, msg: str = ""):
        if loading:
            self.status_lbl.setText(f"⏳  {msg}")
            self.status_lbl.setStyleSheet(
                f"color: {T.NEON}; font-size: 12px; font-weight: 600;"
            )
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
        self.status_lbl.setStyleSheet(
            f"color: {T.ACCENT}; font-weight: bold; font-size: 12px;"
        )
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