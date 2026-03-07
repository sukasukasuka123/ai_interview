# UI/agent_panel.py
"""
AI 知识助手面板 — 重构版
使用统一组件库 UI/components.py，支持原生流式输出
"""
import threading

from PySide6.QtWidgets import (
    QPushButton, QLineEdit, QVBoxLayout, QHBoxLayout,
    QLabel, QScrollArea, QWidget, QFrame,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor

from UI.components import (
    Theme as T, ChatBubble, TypingIndicator, StreamSignals,
    ButtonFactory, GLOBAL_QSS, input_qss,
)

# ── 快捷提示 ──────────────────────────────────────────────────────────────────
HINTS = [
    ("🎲", "随机抽题",   "从题库随机抽5道题",        T.NEON),
    ("🔍", "搜索题目",   "搜索 Redis 相关题目",       T.PURPLE),
    ("📊", "题库统计",   "查看题库分类统计",          T.YELLOW),
    ("🌐", "联网搜索",   "搜索 Spring Boot 3.0 新特性", T.GREEN),
    ("📚", "知识检索",   "什么是 MVCC？",            T.NEON),
    ("🏆", "历史记录",   "查看学生ID=1的面试记录",    T.ACCENT),
]


# ── 主面板 ────────────────────────────────────────────────────────────────────
class AgentPanel(QWidget):
    def __init__(self, agent, parent=None):
        super().__init__(parent)
        self.agent = agent
        self._stream_signals = StreamSignals()
        self._current_ai_bubble: ChatBubble | None = None
        self._typing_indicator: TypingIndicator | None = None
        self._is_streaming = False

        self._stream_signals.chunk_received.connect(self._on_chunk)
        self._stream_signals.stream_done.connect(self._on_stream_done)
        self._stream_signals.stream_error.connect(self._on_stream_error)

        self._build_ui()

    # ── UI 构建 ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setStyleSheet(GLOBAL_QSS + input_qss())

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())
        root.addWidget(self._build_hints())
        root.addWidget(self._build_chat_area(), stretch=1)
        root.addWidget(self._build_footer())

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setFixedHeight(56)
        header.setStyleSheet(f"""
            QFrame {{
                background: {T.SURFACE};
                border-bottom: 1px solid {T.BORDER};
            }}
        """)
        lay = QHBoxLayout(header)
        lay.setContentsMargins(22, 0, 22, 0)

        # 左：标题
        title = QLabel("🤖  AI 知识助手")
        title.setStyleSheet(f"""
            font-size: 16px; font-weight: 800; color: {T.TEXT};
            font-family: {T.FONT};
        """)

        # 中：工具状态
        self._tool_status = QLabel()
        self._update_tool_status()
        self._tool_status.setStyleSheet(f"""
            font-size: 11px; color: {T.GREEN}; font-weight: 600;
            background: {T.GREEN}11;
            border: 1px solid {T.GREEN}33;
            border-radius: 10px;
            padding: 2px 10px;
        """)

        # 右：清空按钮
        clear_btn = ButtonFactory.ghost("清空对话")
        clear_btn.clicked.connect(self._clear)

        lay.addWidget(title)
        lay.addStretch()
        lay.addWidget(self._tool_status)
        lay.addSpacing(12)
        lay.addWidget(clear_btn)
        return header

    def _build_hints(self) -> QFrame:
        frame = QFrame()
        frame.setFixedHeight(52)
        frame.setStyleSheet(f"""
            QFrame {{
                background: {T.SURFACE2};
                border-bottom: 1px solid {T.BORDER};
            }}
        """)
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(18, 10, 18, 10)
        lay.setSpacing(8)

        for icon, label, tooltip, color in HINTS:
            btn = ButtonFactory.tag(f"{icon} {label}", color)
            btn.setToolTip(tooltip)
            btn.clicked.connect(lambda checked, t=tooltip: self._quick_send(t))
            lay.addWidget(btn)

        lay.addStretch()
        return frame

    def _build_chat_area(self) -> QScrollArea:
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet(f"""
            QScrollArea {{ background: {T.BG}; border: none; }}
        """)

        self._chat_widget = QWidget()
        self._chat_widget.setStyleSheet(f"background: {T.BG};")
        self._chat_layout = QVBoxLayout(self._chat_widget)
        self._chat_layout.setContentsMargins(20, 18, 20, 10)
        self._chat_layout.setSpacing(10)
        self._chat_layout.addStretch()

        # 欢迎消息
        welcome = ChatBubble("assistant",
            "你好！我是 **AI 知识助手** 🤖\n\n"
            "我可以帮你：\n"
            "- 🎲 随机抽题练习\n"
            "- 🔍 搜索题目和查看答案\n"
            "- 📊 题库统计与分析\n"
            "- 🌐 联网搜索最新技术资料\n"
            "- 📚 知识库技术概念检索\n"
            "- 🏆 查看历史面试记录\n\n"
            "点击上方快捷按钮，或直接输入问题开始！"
        )
        self._chat_layout.insertWidget(0, welcome)

        self._scroll.setWidget(self._chat_widget)
        return self._scroll

    def _build_footer(self) -> QFrame:
        footer = QFrame()
        footer.setFixedHeight(72)
        footer.setStyleSheet(f"""
            QFrame {{
                background: {T.SURFACE};
                border-top: 1px solid {T.BORDER};
            }}
        """)
        lay = QHBoxLayout(footer)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(10)

        self._input = QLineEdit()
        self._input.setPlaceholderText("输入问题，按 Enter 发送...")
        self._input.setFixedHeight(44)
        self._input.returnPressed.connect(self._send)

        self._send_btn = ButtonFactory.solid("发送", T.NEON, height=44)
        self._send_btn.setFixedWidth(72)
        self._send_btn.clicked.connect(self._send)

        lay.addWidget(self._input, stretch=1)
        lay.addWidget(self._send_btn)
        return footer

    # ── 消息逻辑 ──────────────────────────────────────────────────────────────

    def _update_tool_status(self):
        count = len(self.agent.get_registered_tools()) if hasattr(self.agent, 'get_registered_tools') else 8
        self._tool_status.setText(f"● {count} 个工具就绪")

    def _quick_send(self, text: str):
        self._input.setText(text)
        self._send()

    def _send(self):
        if self._is_streaming:
            return
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self._add_user_bubble(text)
        self._start_stream(text)

    def _add_user_bubble(self, text: str):
        bubble = ChatBubble("user", text)
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, bubble)
        self._scroll_bottom()

    def _start_stream(self, text: str):
        self._is_streaming = True
        self._send_btn.setEnabled(False)
        self._input.setEnabled(False)

        # 打字指示器
        self._typing_indicator = TypingIndicator()
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, self._typing_indicator)
        self._scroll_bottom()

        def run():
            try:
                for chunk in self.agent.stream(text):
                    self._stream_signals.chunk_received.emit(chunk)
                self._stream_signals.stream_done.emit()
            except Exception as e:
                self._stream_signals.stream_error.emit(str(e))

        threading.Thread(target=run, daemon=True).start()

    def _on_chunk(self, chunk: str):
        # 移除打字指示器
        if self._typing_indicator:
            self._chat_layout.removeWidget(self._typing_indicator)
            self._typing_indicator.stop()
            self._typing_indicator.deleteLater()
            self._typing_indicator = None

        # 创建 AI 气泡（仅首个 chunk）
        if self._current_ai_bubble is None:
            self._current_ai_bubble = ChatBubble("assistant")
            self._chat_layout.insertWidget(self._chat_layout.count() - 1, self._current_ai_bubble)

        self._current_ai_bubble.append_chunk(chunk)
        self._scroll_bottom()

    def _on_stream_done(self):
        self._current_ai_bubble = None
        self._is_streaming = False
        self._send_btn.setEnabled(True)
        self._input.setEnabled(True)
        self._input.setFocus()

    def _on_stream_error(self, msg: str):
        if self._typing_indicator:
            self._chat_layout.removeWidget(self._typing_indicator)
            self._typing_indicator.stop()
            self._typing_indicator.deleteLater()
            self._typing_indicator = None

        err_bubble = ChatBubble("assistant", f"❌ 出错了：{msg}")
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, err_bubble)
        self._current_ai_bubble = None
        self._is_streaming = False
        self._send_btn.setEnabled(True)
        self._input.setEnabled(True)

    # ── 工具函数 ──────────────────────────────────────────────────────────────

    def _clear(self):
        while self._chat_layout.count() > 1:
            item = self._chat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.agent.clear_conversation()

    def _scroll_bottom(self):
        QTimer.singleShot(60, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        ))