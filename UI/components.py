# UI/components.py
"""
统一 UI 组件库
供 AgentPanel、InterviewPanel 等所有面板共用
包含：色彩系统、气泡组件、流式输出气泡、打字指示器、卡片、按钮工厂等
"""

from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextBrowser, QSizePolicy, QGraphicsDropShadowEffect, QWidget,
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer, QPropertyAnimation, QEasingCurve, QRect
from PySide6.QtGui import QColor, QTextCursor, QFont, QLinearGradient, QPainter, QPen, QBrush


# ═══════════════════════════════════════════════════════════════════
# 色彩系统  (全局唯一，所有面板共享)
# ═══════════════════════════════════════════════════════════════════

class Theme:
    """暗夜霓虹主题 — 全局色彩常量"""
    BG          = "#0A0A14"
    SURFACE     = "#12121E"
    SURFACE2    = "#1A1A2E"
    SURFACE3    = "#0F1628"

    ACCENT      = "#E94560"   # 玫红
    NEON        = "#00D4FF"   # 电蓝
    GREEN       = "#00FF9D"   # 霓虹绿
    YELLOW      = "#FFD166"   # 暖金
    PURPLE      = "#B388FF"   # 幻紫

    TEXT        = "#E8E8F5"
    TEXT_DIM    = "#7070A0"
    TEXT_MUTE   = "#404060"

    BORDER      = "#1E1E3A"
    BORDER2     = "#2A2A50"

    USER_BUBBLE = "#0F2A4A"
    AI_BUBBLE   = "#12121E"

    # 语义色
    SUCCESS     = GREEN
    ERROR       = ACCENT
    WARNING     = YELLOW
    INFO        = NEON

    # 字体
    FONT        = '-apple-system, "PingFang SC", "Microsoft YaHei", sans-serif'
    FONT_MONO   = '"JetBrains Mono", "Cascadia Code", "Fira Code", monospace'

    @classmethod
    def as_dict(cls):
        return {k: v for k, v in vars(cls).items() if not k.startswith('_') and isinstance(v, str)}


T = Theme  # 简写别名


# ═══════════════════════════════════════════════════════════════════
# 流式信号
# ═══════════════════════════════════════════════════════════════════

class StreamSignals(QObject):
    """跨线程流式输出信号，AgentPanel / InterviewPanel 共用"""
    chunk_received  = Signal(str)   # 每个文字片段
    stream_done     = Signal()      # 流结束
    stream_error    = Signal(str)   # 出错消息


# ═══════════════════════════════════════════════════════════════════
# 打字动画指示器
# ═══════════════════════════════════════════════════════════════════

class TypingIndicator(QFrame):
    """三点呼吸动画，AI 思考中使用"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 4, 8, 4)

        bubble = QFrame()
        bubble.setObjectName("typing_bubble")
        bubble.setStyleSheet(f"""
            QFrame#typing_bubble {{
                background: {T.AI_BUBBLE};
                border: 1px solid {T.BORDER2};
                border-radius: 18px;
                border-top-left-radius: 4px;
            }}
        """)
        bubble.setFixedSize(76, 40)

        b_lay = QHBoxLayout(bubble)
        b_lay.setContentsMargins(16, 10, 16, 10)
        b_lay.setSpacing(6)

        self._dots = []
        for _ in range(3):
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {T.NEON}33; font-size: 9px; background: transparent;")
            b_lay.addWidget(dot)
            self._dots.append(dot)

        outer.addWidget(bubble)
        outer.addStretch()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._step = 0
        self._timer.start(380)

    def _animate(self):
        for i, dot in enumerate(self._dots):
            alpha = "FF" if i == self._step % 3 else "33"
            dot.setStyleSheet(f"color: {T.NEON}{alpha}; font-size: 9px; background: transparent;")
        self._step += 1

    def stop(self):
        self._timer.stop()


# ═══════════════════════════════════════════════════════════════════
# 通用聊天气泡  (Agent + Interview 共用)
# ═══════════════════════════════════════════════════════════════════

class ChatBubble(QFrame):
    """
    统一聊天气泡组件，支持：
      - role: "user" | "assistant" | "ai" | "system"
      - Markdown 渲染
      - 流式 append_chunk()
      - 自适应高度
    """

    # 角色配置
    _ROLE_CFG = {
        "user": {
            "label": "👤  你",
            "label_color": T.YELLOW,
            "bg": T.USER_BUBBLE,
            "border": f"{T.NEON}33",
            "radius": "18px 18px 4px 18px",
            "align": "right",
        },
        "assistant": {
            "label": "🤖  AI 助手",
            "label_color": T.NEON,
            "bg": T.AI_BUBBLE,
            "border": T.BORDER2,
            "radius": "4px 18px 18px 18px",
            "align": "left",
        },
        "ai": {  # 别名
            "label": "🤖  AI 面试官",
            "label_color": T.NEON,
            "bg": T.AI_BUBBLE,
            "border": T.BORDER2,
            "radius": "4px 18px 18px 18px",
            "align": "left",
        },
        "system": {
            "label": "",
            "label_color": T.TEXT_DIM,
            "bg": "transparent",
            "border": "transparent",
            "radius": "8px",
            "align": "center",
        },
    }

    def __init__(self, role: str, content: str = "", max_width: int = 520, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self._role = role
        self._content = content
        self._max_width = max_width

        cfg = self._ROLE_CFG.get(role, self._ROLE_CFG["assistant"])

        outer = QHBoxLayout(self)
        outer.setContentsMargins(6, 3, 6, 3)
        outer.setSpacing(0)

        # system 消息居中显示
        if role == "system":
            lbl = QLabel(content)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(f"""
                color: {T.TEXT_DIM}; font-size: 11px;
                padding: 4px 12px; background: transparent;
                font-family: {T.FONT};
            """)
            outer.addWidget(lbl)
            return

        # 气泡容器
        self.bubble = QFrame()
        self.bubble.setObjectName("bubble")
        self.bubble.setMaximumWidth(max_width)
        self.bubble.setStyleSheet(f"""
            QFrame#bubble {{
                background: {cfg['bg']};
                border: 1px solid {cfg['border']};
                border-radius: {cfg['radius']};
            }}
        """)

        inner = QVBoxLayout(self.bubble)
        inner.setContentsMargins(14, 10, 14, 10)
        inner.setSpacing(5)

        # 角色标签
        if cfg["label"]:
            role_lbl = QLabel(cfg["label"])
            role_lbl.setStyleSheet(f"""
                font-size: 10px; color: {cfg['label_color']};
                font-weight: 700; letter-spacing: 1px;
                background: transparent;
                font-family: {T.FONT};
            """)
            inner.addWidget(role_lbl)

        # 内容视图
        self.text_view = QTextBrowser()
        self.text_view.setOpenExternalLinks(True)
        self.text_view.setFrameShape(QFrame.NoFrame)
        self.text_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.text_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.text_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.text_view.setStyleSheet(f"""
            QTextBrowser {{
                background: transparent;
                color: {T.TEXT};
                font-size: 14px;
                border: none;
                font-family: {T.FONT};
                line-height: 1.7;
            }}
        """)
        inner.addWidget(self.text_view)

        # 布局对齐
        if cfg["align"] == "right":
            outer.addStretch(2)
            outer.addWidget(self.bubble, stretch=8)
        elif cfg["align"] == "left":
            outer.addWidget(self.bubble, stretch=8)
            outer.addStretch(2)
        else:
            outer.addWidget(self.bubble)

        # 初始内容
        if content:
            self._set_content(content)

    def _set_content(self, text: str):
        self._content = text
        self.text_view.setMarkdown(text)
        self._adjust_height()

    def append_chunk(self, chunk: str):
        """流式追加文字片段"""
        self._content += chunk
        self.text_view.setMarkdown(self._content)
        cursor = self.text_view.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.text_view.setTextCursor(cursor)
        self._adjust_height()

    def _adjust_height(self):
        w = min(self.text_view.width() or self._max_width - 28, self._max_width - 28)
        self.text_view.document().setTextWidth(w)
        h = int(self.text_view.document().size().height()) + 20
        self.text_view.setFixedHeight(max(36, h))


# ═══════════════════════════════════════════════════════════════════
# 评分卡片气泡  (InterviewPanel 专用)
# ═══════════════════════════════════════════════════════════════════

class ScoreCardBubble(QFrame):
    """评分结果展示卡片，统一样式"""

    def __init__(self, eval_result, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)

        card = QFrame()
        card.setObjectName("score_card")
        card.setStyleSheet(f"""
            QFrame#score_card {{
                background: {T.SURFACE2};
                border: 1px solid {T.NEON}22;
                border-left: 3px solid {T.NEON};
                border-radius: 12px;
            }}
        """)

        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(T.NEON).darker(300))
        shadow.setOffset(0, 4)
        card.setGraphicsEffect(shadow)

        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(16, 14, 16, 14)
        card_lay.setSpacing(10)

        # 标题
        title = QLabel("📊  本题评估报告")
        title.setStyleSheet(f"""
            font-weight: 700; font-size: 13px; color: {T.NEON};
            font-family: {T.FONT}; background: transparent;
        """)
        card_lay.addWidget(title)

        # 分数行
        scores_row = QHBoxLayout()
        scores_row.setSpacing(0)
        score_items = [
            ("技术", eval_result.tech_score,  T.NEON),
            ("逻辑", eval_result.logic_score, T.PURPLE),
            ("深度", eval_result.depth_score, T.YELLOW),
            ("表达", eval_result.clarity_score, T.GREEN),
        ]
        for label, score, color in score_items:
            item_frame = QFrame()
            item_frame.setStyleSheet("background: transparent;")
            item_lay = QVBoxLayout(item_frame)
            item_lay.setContentsMargins(10, 6, 10, 6)
            item_lay.setSpacing(2)
            item_lay.setAlignment(Qt.AlignCenter)

            val_lbl = QLabel(str(score))
            val_lbl.setAlignment(Qt.AlignCenter)
            val_lbl.setStyleSheet(f"""
                font-size: 22px; font-weight: 900; color: {color};
                font-family: {T.FONT_MONO}; background: transparent;
            """)
            name_lbl = QLabel(label)
            name_lbl.setAlignment(Qt.AlignCenter)
            name_lbl.setStyleSheet(f"font-size: 10px; color: {T.TEXT_DIM}; background: transparent;")

            item_lay.addWidget(val_lbl)
            item_lay.addWidget(name_lbl)
            scores_row.addWidget(item_frame)

        # 综合分数
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet(f"color: {T.BORDER2}; background: {T.BORDER2};")
        sep.setFixedWidth(1)
        scores_row.addWidget(sep)

        overall_frame = QFrame()
        overall_frame.setStyleSheet(f"""
            background: {T.GREEN}11;
            border-radius: 8px;
        """)
        overall_lay = QVBoxLayout(overall_frame)
        overall_lay.setContentsMargins(14, 8, 14, 8)
        overall_lay.setAlignment(Qt.AlignCenter)

        overall_val = QLabel(f"{eval_result.overall_score:.1f}")
        overall_val.setAlignment(Qt.AlignCenter)
        overall_val.setStyleSheet(f"""
            font-size: 26px; font-weight: 900; color: {T.GREEN};
            font-family: {T.FONT_MONO}; background: transparent;
        """)
        overall_name = QLabel("综合")
        overall_name.setAlignment(Qt.AlignCenter)
        overall_name.setStyleSheet(f"font-size: 10px; color: {T.GREEN}AA; background: transparent;")
        overall_lay.addWidget(overall_val)
        overall_lay.addWidget(overall_name)
        scores_row.addWidget(overall_frame)

        card_lay.addLayout(scores_row)

        # 建议
        if eval_result.suggestion:
            tip = QLabel(f"💡  {eval_result.suggestion}")
            tip.setWordWrap(True)
            tip.setStyleSheet(f"""
                font-size: 12px; color: {T.TEXT_DIM};
                background: {T.SURFACE3};
                border-radius: 6px;
                padding: 8px 10px;
                font-family: {T.FONT};
            """)
            card_lay.addWidget(tip)

        outer.addWidget(card, stretch=9)
        outer.addStretch(1)


# ═══════════════════════════════════════════════════════════════════
# 统计徽章卡片
# ═══════════════════════════════════════════════════════════════════

class StatBadge(QFrame):
    """紧凑统计徽章，用于 QuizPanel Hero 区域"""

    def __init__(self, icon: str, value: str, label: str, color: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(130, 82)
        self.setStyleSheet(f"""
            QFrame {{
                background: {T.SURFACE};
                border: 1px solid {color}33;
                border-top: 2px solid {color};
                border-radius: 10px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(16)
        shadow.setColor(QColor(color).darker(200))
        shadow.setOffset(0, 3)
        self.setGraphicsEffect(shadow)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(2)

        top = QHBoxLayout()
        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet("font-size: 18px; background: transparent;")
        val_lbl = QLabel(value)
        val_lbl.setStyleSheet(f"""
            font-size: 20px; font-weight: 900; color: {color};
            font-family: {T.FONT_MONO}; background: transparent;
        """)
        top.addWidget(icon_lbl)
        top.addStretch()
        top.addWidget(val_lbl)

        name_lbl = QLabel(label)
        name_lbl.setStyleSheet(f"font-size: 10px; color: {T.TEXT_DIM}; font-weight: 600; background: transparent;")

        lay.addLayout(top)
        lay.addWidget(name_lbl)


# ═══════════════════════════════════════════════════════════════════
# 按钮工厂
# ═══════════════════════════════════════════════════════════════════

class ButtonFactory:
    """统一风格按钮生成器"""

    @staticmethod
    def primary(text: str, color: str = T.NEON, height: int = 38) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedHeight(height)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {color}22;
                color: {color};
                border: 1px solid {color}66;
                border-radius: {height // 2}px;
                font-size: 13px; font-weight: 700;
                padding: 0 18px;
                font-family: {T.FONT};
            }}
            QPushButton:hover {{ background: {color}44; border-color: {color}; }}
            QPushButton:pressed {{ background: {color}66; }}
            QPushButton:disabled {{
                background: {T.BORDER}; color: {T.TEXT_MUTE};
                border-color: {T.BORDER};
            }}
        """)
        return btn

    @staticmethod
    def solid(text: str, color: str = T.NEON, height: int = 38) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedHeight(height)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {color};
                color: #0A0A14;
                border: none;
                border-radius: {height // 2}px;
                font-size: 13px; font-weight: 800;
                padding: 0 18px;
                font-family: {T.FONT};
            }}
            QPushButton:hover {{ background: {color}CC; }}
            QPushButton:pressed {{ background: {color}AA; }}
            QPushButton:disabled {{
                background: {T.BORDER}; color: {T.TEXT_MUTE};
            }}
        """)
        return btn

    @staticmethod
    def ghost(text: str, height: int = 30) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedHeight(height)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {T.TEXT_DIM};
                border: 1px solid {T.BORDER2};
                border-radius: 6px;
                font-size: 12px;
                padding: 0 12px;
                font-family: {T.FONT};
            }}
            QPushButton:hover {{ color: {T.ACCENT}; border-color: {T.ACCENT}; }}
        """)
        return btn

    @staticmethod
    def tag(text: str, color: str, height: int = 32) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedHeight(height)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {T.SURFACE};
                color: {T.TEXT_DIM};
                border: 1px solid {T.BORDER2};
                border-radius: {height // 2}px;
                font-size: 11px; font-weight: 600;
                padding: 0 14px;
                font-family: {T.FONT};
            }}
            QPushButton:hover {{
                color: {color};
                border-color: {color}55;
                background: {color}11;
            }}
        """)
        return btn


# ═══════════════════════════════════════════════════════════════════
# 全局 QSS 滚动条 + 基础样式
# ═══════════════════════════════════════════════════════════════════

GLOBAL_QSS = f"""
    QWidget {{
        background: {T.BG};
        color: {T.TEXT};
        font-family: {T.FONT};
    }}
    QScrollBar:vertical {{
        width: 5px;
        background: transparent;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {T.BORDER2};
        border-radius: 2px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {T.NEON}66;
    }}
    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        height: 5px;
        background: transparent;
    }}
    QScrollBar::handle:horizontal {{
        background: {T.BORDER2};
        border-radius: 2px;
    }}
    QScrollBar::add-line:horizontal,
    QScrollBar::sub-line:horizontal {{
        width: 0;
    }}
    QComboBox QAbstractItemView {{
        background: {T.SURFACE2};
        color: {T.TEXT};
        selection-background-color: {T.NEON}22;
        border: 1px solid {T.BORDER2};
        outline: none;
    }}
"""

# 头部导航栏 QSS
def header_qss(border_color: str = T.BORDER) -> str:
    return f"""
        QFrame {{
            background: {T.SURFACE};
            border-bottom: 1px solid {border_color};
        }}
    """

# 输入框 QSS
def input_qss(focus_color: str = T.NEON) -> str:
    return f"""
        QLineEdit, QTextEdit {{
            background: {T.BG};
            border: 1px solid {T.BORDER2};
            border-radius: 10px;
            padding: 8px 14px;
            color: {T.TEXT};
            font-size: 14px;
            font-family: {T.FONT};
        }}
        QLineEdit:focus, QTextEdit:focus {{
            border-color: {focus_color};
        }}
        QLineEdit:disabled, QTextEdit:disabled {{
            background: {T.SURFACE};
            color: {T.TEXT_MUTE};
        }}
        QLineEdit::placeholder, QTextEdit::placeholder {{
            color: {T.TEXT_MUTE};
        }}
    """

def combo_qss(focus_color: str = T.NEON) -> str:
    return f"""
        QComboBox {{
            background: {T.BG};
            border: 1px solid {T.BORDER2};
            border-radius: 8px;
            padding: 6px 12px;
            color: {T.TEXT};
            font-size: 13px;
            font-family: {T.FONT};
        }}
        QComboBox:focus {{ border-color: {focus_color}; }}
        QComboBox::drop-down {{ border: none; width: 20px; }}
        QComboBox::down-arrow {{
            image: none;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 5px solid {T.TEXT_DIM};
            margin: 4px;
        }}
    """