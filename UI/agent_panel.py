# UI/agent_panel.py
"""
AI 知识助手面板（支持流式输出 + 联网搜索 + 题库查询）
"""
import threading

from PySide6.QtWidgets import (
    QPushButton, QLineEdit, QVBoxLayout, QHBoxLayout,
    QLabel, QScrollArea, QWidget, QFrame, QTextBrowser,
    QSizePolicy, QGraphicsDropShadowEffect,
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer
from PySide6.QtGui import QColor, QTextCursor

from UI.base_panel import PanelFrame

# ── 色彩（与 QuizPanel 一致的暗夜主题） ──────────────────────────────────────
C = {
    "bg":       "#0F0F1A",
    "surface":  "#1A1A2E",
    "surface2": "#16213E",
    "accent":   "#E94560",
    "neon":     "#00D4FF",
    "green":    "#00FF87",
    "yellow":   "#FFD166",
    "text":     "#E8E8F0",
    "text_dim": "#8888AA",
    "border":   "#2A2A4A",
    "user_bubble": "#0F3460",
    "ai_bubble":   "#1A1A2E",
}

HINTS = [
    ("🎲", "随机抽题", "从题库随机抽5道题"),
    ("🔍", "搜索题目", "搜索 Redis 相关题目"),
    ("📊", "题库统计", "查看题库分类统计"),
    ("🌐", "联网搜索", "搜索 Spring Boot 3.0 新特性"),
    ("📚", "知识检索", "什么是 MVCC？"),
    ("🏆", "历史记录", "查看学生ID=1的面试记录"),
]


# ── 流式更新信号 ──────────────────────────────────────────────────────────────
class StreamSignals(QObject):
    chunk_received = Signal(str)   # 每个文字片段
    stream_done = Signal()         # 流结束
    stream_error = Signal(str)     # 出错


# ── 消息气泡 ──────────────────────────────────────────────────────────────────
class MessageBubble(QFrame):
    def __init__(self, role: str, content: str = "", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self._role = role
        self._full_content = content

        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 4, 8, 4)
        outer.setSpacing(0)

        self.bubble = QFrame()
        self.bubble.setObjectName("bubble")
        inner = QVBoxLayout(self.bubble)
        inner.setContentsMargins(14, 10, 14, 10)
        inner.setSpacing(4)

        # 角色标签
        if role == "assistant":
            role_lbl = QLabel("🤖  AI 助手")
            role_lbl.setStyleSheet(f"font-size: 10px; color: {C['neon']}; font-weight: 700; letter-spacing: 1px;")
        else:
            role_lbl = QLabel("👤  你")
            role_lbl.setStyleSheet(f"font-size: 10px; color: {C['yellow']}; font-weight: 700;")
        inner.addWidget(role_lbl)

        # 内容
        self.text_view = QTextBrowser()
        self.text_view.setOpenExternalLinks(True)
        self.text_view.setFrameShape(QFrame.NoFrame)
        self.text_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.text_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.text_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        if role == "assistant":
            self.text_view.setStyleSheet(f"""
                QTextBrowser {{
                    background: transparent; color: {C['text']};
                    font-size: 14px; border: none;
                    font-family: -apple-system, "PingFang SC", sans-serif;
                }}
            """)
            self.bubble.setStyleSheet(f"""
                QFrame#bubble {{
                    background: {C['ai_bubble']};
                    border: 1px solid {C['border']};
                    border-radius: 16px; border-top-left-radius: 4px;
                }}
            """)
            outer.addWidget(self.bubble, stretch=8)
            outer.addStretch(2)
        else:
            self.text_view.setStyleSheet(f"""
                QTextBrowser {{
                    background: transparent; color: {C['text']};
                    font-size: 14px; border: none;
                    font-family: -apple-system, "PingFang SC", sans-serif;
                }}
            """)
            self.bubble.setStyleSheet(f"""
                QFrame#bubble {{
                    background: {C['user_bubble']};
                    border: 1px solid {C['neon']}33;
                    border-radius: 16px; border-top-right-radius: 4px;
                }}
            """)
            outer.addStretch(2)
            outer.addWidget(self.bubble, stretch=8)

        inner.addWidget(self.text_view)

        if content:
            self._set_content(content)

    def _set_content(self, text: str):
        self._full_content = text
        self.text_view.setMarkdown(text)
        self._adjust_height()

    def append_chunk(self, chunk: str):
        """流式追加文本"""
        self._full_content += chunk
        self.text_view.setMarkdown(self._full_content)
        # 滚到末尾
        cursor = self.text_view.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.text_view.setTextCursor(cursor)
        self._adjust_height()

    def _adjust_height(self):
        self.text_view.document().setTextWidth(self.text_view.width() or 500)
        h = int(self.text_view.document().size().height()) + 24
        self.text_view.setFixedHeight(max(40, h))


class TypingIndicator(QFrame):
    """打字动画指示器"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)

        bubble = QFrame()
        bubble.setObjectName("typing_bubble")
        bubble.setStyleSheet(f"""
            QFrame#typing_bubble {{
                background: {C['ai_bubble']}; border: 1px solid {C['border']};
                border-radius: 12px; border-top-left-radius: 4px;
            }}
        """)
        bubble.setFixedSize(70, 36)
        b_lay = QHBoxLayout(bubble)
        b_lay.setContentsMargins(14, 8, 14, 8)
        b_lay.setSpacing(5)

        self._dots = []
        for _ in range(3):
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {C['neon']}44; font-size: 10px;")
            b_lay.addWidget(dot)
            self._dots.append(dot)

        lay.addWidget(bubble)
        lay.addStretch()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._step = 0
        self._timer.start(400)

    def _animate(self):
        for i, dot in enumerate(self._dots):
            if i == self._step % 3:
                dot.setStyleSheet(f"color: {C['neon']}; font-size: 10px;")
            else:
                dot.setStyleSheet(f"color: {C['neon']}44; font-size: 10px;")
        self._step += 1

    def stop(self):
        self._timer.stop()


# ── 主面板 ────────────────────────────────────────────────────────────────────
class AgentPanel(QWidget):
    def __init__(self, agent, parent=None):
        super().__init__(parent)
        self.agent = agent
        self._stream_signals = StreamSignals()
        self._current_ai_bubble: MessageBubble | None = None
        self._typing_indicator: TypingIndicator | None = None
        self._is_streaming = False

        self._stream_signals.chunk_received.connect(self._on_chunk)
        self._stream_signals.stream_done.connect(self._on_stream_done)
        self._stream_signals.stream_error.connect(self._on_stream_error)

        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet(f"""
            QWidget {{
                background: {C['bg']}; color: {C['text']};
                font-family: -apple-system, "PingFang SC", sans-serif;
            }}
            QScrollBar:vertical {{ width: 6px; background: transparent; }}
            QScrollBar::handle:vertical {{ background: {C['border']}; border-radius: 3px; min-height: 40px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 顶部 Header ───────────────────────────────────────────────────────
        header = QFrame()
        header.setFixedHeight(56)
        header.setStyleSheet(f"""
            QFrame {{
                background: {C['surface']};
                border-bottom: 1px solid {C['border']};
            }}
        """)
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(20, 0, 20, 0)

        title = QLabel("🤖  AI 知识助手")
        title.setStyleSheet(f"font-size: 16px; font-weight: 800; color: {C['text']};")

        self._tool_status = QLabel("● 8 个工具已就绪")
        self._tool_status.setStyleSheet(f"font-size: 11px; color: {C['green']}; font-weight: 600;")

        clear_btn = QPushButton("清空对话")
        clear_btn.setFixedSize(80, 28)
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C['text_dim']};
                border: 1px solid {C['border']}; border-radius: 6px; font-size: 11px;
            }}
            QPushButton:hover {{ color: {C['accent']}; border-color: {C['accent']}; }}
        """)
        clear_btn.clicked.connect(self._clear)

        h_lay.addWidget(title)
        h_lay.addStretch()
        h_lay.addWidget(self._tool_status)
        h_lay.addSpacing(16)
        h_lay.addWidget(clear_btn)
        root.addWidget(header)

        # ── 快捷提示卡片 ─────────────────────────────────────────────────────
        hints_frame = QFrame()
        hints_frame.setFixedHeight(56)
        hints_frame.setStyleSheet(f"background: {C['surface2']}; border-bottom: 1px solid {C['border']};")
        hints_lay = QHBoxLayout(hints_frame)
        hints_lay.setContentsMargins(16, 8, 16, 8)
        hints_lay.setSpacing(8)

        for icon, label, tooltip in HINTS:
            btn = QPushButton(f"{icon} {label}")
            btn.setToolTip(tooltip)
            btn.setFixedHeight(32)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {C['surface']}; color: {C['text_dim']};
                    border: 1px solid {C['border']}; border-radius: 16px;
                    font-size: 11px; font-weight: 600; padding: 0 12px;
                }}
                QPushButton:hover {{
                    color: {C['neon']}; border-color: {C['neon']}55;
                    background: {C['neon']}11;
                }}
            """)
            btn.clicked.connect(lambda checked, t=tooltip: self._quick_send(t))
            hints_lay.addWidget(btn)

        hints_lay.addStretch()
        root.addWidget(hints_frame)

        # ── 聊天区域 ──────────────────────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet(f"QScrollArea {{ background: {C['bg']}; border: none; }}")

        self._chat_widget = QWidget()
        self._chat_widget.setStyleSheet(f"background: {C['bg']};")
        self._chat_layout = QVBoxLayout(self._chat_widget)
        self._chat_layout.setContentsMargins(20, 20, 20, 10)
        self._chat_layout.setSpacing(12)
        self._chat_layout.addStretch()

        self._scroll.setWidget(self._chat_widget)
        root.addWidget(self._scroll, stretch=1)

        # ── 欢迎消息 ──────────────────────────────────────────────────────────
        welcome = MessageBubble("assistant",
            "你好！我是 AI 知识助手 🤖\n\n"
            "我可以帮你：\n"
            "- 🎲 从题库随机抽题练习\n"
            "- 🔍 搜索题目和查看答案\n"
            "- 📊 查看题库统计\n"
            "- 🌐 联网搜索最新技术资料\n"
            "- 📚 从知识库检索技术概念\n"
            "- 🏆 查看历史面试记录\n\n"
            "点击上方快捷按钮或直接输入问题开始吧！"
        )
        self._chat_layout.insertWidget(0, welcome)

        # ── 底部输入区 ────────────────────────────────────────────────────────
        footer = QFrame()
        footer.setFixedHeight(70)
        footer.setStyleSheet(f"""
            QFrame {{
                background: {C['surface']};
                border-top: 1px solid {C['border']};
            }}
        """)
        f_lay = QHBoxLayout(footer)
        f_lay.setContentsMargins(20, 12, 20, 12)
        f_lay.setSpacing(10)

        self._input = QLineEdit()
        self._input.setPlaceholderText("输入问题，按 Enter 发送...")
        self._input.setFixedHeight(44)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: {C['bg']}; border: 1px solid {C['border']};
                border-radius: 12px; padding: 0 16px;
                color: {C['text']}; font-size: 14px;
            }}
            QLineEdit:focus {{ border-color: {C['neon']}; }}
        """)
        self._input.returnPressed.connect(self._send)

        self._send_btn = QPushButton("发送")
        self._send_btn.setFixedSize(70, 44)
        self._send_btn.setCursor(Qt.PointingHandCursor)
        self._send_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C['neon']}22; color: {C['neon']};
                border: 1px solid {C['neon']}66; border-radius: 12px;
                font-size: 14px; font-weight: 700;
            }}
            QPushButton:hover {{ background: {C['neon']}44; }}
            QPushButton:disabled {{ background: {C['border']}; color: {C['text_dim']}; border-color: {C['border']}; }}
        """)
        self._send_btn.clicked.connect(self._send)

        f_lay.addWidget(self._input, stretch=1)
        f_lay.addWidget(self._send_btn)
        root.addWidget(footer)

    # ── 消息发送 ──────────────────────────────────────────────────────────────

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
        bubble = MessageBubble("user", text)
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, bubble)
        self._scroll_bottom()

    def _start_stream(self, text: str):
        self._is_streaming = True
        self._send_btn.setEnabled(False)
        self._input.setEnabled(False)

        # 显示打字指示器
        self._typing_indicator = TypingIndicator()
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, self._typing_indicator)
        self._scroll_bottom()

        # 在子线程中执行流式调用
        def run():
            try:
                for chunk in self.agent.stream(text):
                    self._stream_signals.chunk_received.emit(chunk)
                self._stream_signals.stream_done.emit()
            except Exception as e:
                self._stream_signals.stream_error.emit(str(e))

        threading.Thread(target=run, daemon=True).start()

    def _on_chunk(self, chunk: str):
        # 第一个 chunk：移除打字指示器，创建 AI 气泡
        if self._typing_indicator:
            self._chat_layout.removeWidget(self._typing_indicator)
            self._typing_indicator.stop()
            self._typing_indicator.deleteLater()
            self._typing_indicator = None

        if self._current_ai_bubble is None:
            self._current_ai_bubble = MessageBubble("assistant")
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
            self._typing_indicator.deleteLater()
            self._typing_indicator = None

        err_bubble = MessageBubble("assistant", f"❌ 出错了：{msg}")
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