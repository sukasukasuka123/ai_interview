# UI/quiz_panel.py
"""
题库管理与练习面板
功能：
  1. 按分类/难度浏览题库
  2. 随机抽题练习
  3. 查看答案
  4. 题库统计概览
"""
import random

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QScrollArea, QFrame, QTextBrowser, QSplitter,
    QSpinBox, QGraphicsDropShadowEffect, QSizePolicy, QLineEdit,
    QStackedWidget, QGridLayout, QProgressBar,
)
from PySide6.QtCore import Qt, Signal, QTimer, QPropertyAnimation, QEasingCurve, QRect
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QLinearGradient


# ── 色彩系统 ──────────────────────────────────────────────────────────────────
C = {
    "bg":        "#0F0F1A",   # 深夜蓝黑
    "surface":   "#1A1A2E",   # 卡片背景
    "surface2":  "#16213E",   # 次级卡片
    "accent":    "#E94560",   # 玫红主色
    "accent2":   "#0F3460",   # 深蓝辅色
    "neon":      "#00D4FF",   # 霓虹蓝
    "green":     "#00FF87",   # 霓虹绿
    "yellow":    "#FFD166",   # 金黄
    "text":      "#E8E8F0",   # 主文字
    "text_dim":  "#8888AA",   # 次要文字
    "border":    "#2A2A4A",   # 边框
    "tag_java":  "#FF6B6B",
    "tag_js":    "#FFE66D",
    "tag_db":    "#4ECDC4",
    "tag_net":   "#A8E6CF",
    "tag_algo":  "#C3A6FF",
    "tag_spring":"#FF9F43",
    "tag_jvm":   "#54A0FF",
    "tag_vue":   "#00D2D3",
}

LEVEL_COLORS = {
    "初级": ("#00FF87", "#0A2E1E"),
    "中级": ("#FFD166", "#2E2400"),
    "高级": ("#E94560", "#2E0A12"),
}

CLASSIFY_COLORS = {
    "Java基础":      C["tag_java"],
    "JVM":           C["tag_jvm"],
    "Spring":        C["tag_spring"],
    "MySQL":         C["tag_db"],
    "Redis":         C["tag_db"],
    "JavaScript":    C["tag_js"],
    "Vue/React":     C["tag_vue"],
    "计算机网络":    C["tag_net"],
    "数据结构与算法": C["tag_algo"],
}


def _classify_color(cls: str) -> str:
    return CLASSIFY_COLORS.get(cls, C["neon"])


# ── 统计卡片 ──────────────────────────────────────────────────────────────────
class StatCard(QFrame):
    def __init__(self, icon: str, value: str, label: str, color: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(140, 90)
        self.setStyleSheet(f"""
            QFrame {{
                background: {C['surface']};
                border: 1px solid {color}44;
                border-radius: 12px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(color).darker(150))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)

        top = QHBoxLayout()
        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet("font-size: 20px;")
        val_lbl = QLabel(value)
        val_lbl.setStyleSheet(f"font-size: 22px; font-weight: 900; color: {color}; font-family: 'Courier New';")
        top.addWidget(icon_lbl)
        top.addStretch()
        top.addWidget(val_lbl)

        lbl = QLabel(label)
        lbl.setStyleSheet(f"font-size: 11px; color: {C['text_dim']}; font-weight: 600;")

        lay.addLayout(top)
        lay.addWidget(lbl)


# ── 题目卡片 ──────────────────────────────────────────────────────────────────
class QuestionCard(QFrame):
    def __init__(self, qid: int, classify: str, level: str, content: str, answer: str, index: int, parent=None):
        super().__init__(parent)
        self._answer = answer
        self._answer_visible = False
        self.setObjectName("QuestionCard")

        lvl_fg, lvl_bg = LEVEL_COLORS.get(level, ("#fff", "#333"))
        cls_color = _classify_color(classify)

        self.setStyleSheet(f"""
            QFrame#QuestionCard {{
                background: {C['surface']};
                border: 1px solid {C['border']};
                border-left: 4px solid {cls_color};
                border-radius: 12px;
            }}
            QFrame#QuestionCard:hover {{
                border-color: {cls_color}88;
                background: {C['surface2']};
            }}
        """)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 80))
        shadow.setOffset(0, 3)
        self.setGraphicsEffect(shadow)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(10)

        # 顶部：序号 + 分类标签 + 难度
        header = QHBoxLayout()

        num_lbl = QLabel(f"#{index:02d}")
        num_lbl.setStyleSheet(f"color: {C['text_dim']}; font-size: 12px; font-family: 'Courier New'; font-weight: 700;")

        cls_tag = QLabel(f" {classify} ")
        cls_tag.setStyleSheet(f"""
            background: {cls_color}22; color: {cls_color};
            border: 1px solid {cls_color}66; border-radius: 4px;
            font-size: 11px; font-weight: 700; padding: 1px 6px;
        """)

        lvl_tag = QLabel(f" {level} ")
        lvl_tag.setStyleSheet(f"""
            background: {lvl_bg}; color: {lvl_fg};
            border-radius: 4px; font-size: 11px;
            font-weight: 700; padding: 1px 6px;
        """)

        header.addWidget(num_lbl)
        header.addWidget(cls_tag)
        header.addWidget(lvl_tag)
        header.addStretch()

        # 题目内容
        q_lbl = QLabel(content)
        q_lbl.setWordWrap(True)
        q_lbl.setStyleSheet(f"""
            color: {C['text']}; font-size: 14px;
            line-height: 1.6; font-weight: 500;
        """)

        # 答案区域（折叠）
        self.answer_frame = QFrame()
        self.answer_frame.setVisible(False)
        self.answer_frame.setStyleSheet(f"""
            QFrame {{
                background: {C['accent2']}33;
                border: 1px solid {C['neon']}33;
                border-radius: 8px;
            }}
        """)
        ans_lay = QVBoxLayout(self.answer_frame)
        ans_lay.setContentsMargins(12, 10, 12, 10)

        ans_title = QLabel("💡 参考答案")
        ans_title.setStyleSheet(f"color: {C['neon']}; font-size: 12px; font-weight: 700; margin-bottom: 4px;")

        self.ans_text = QLabel(answer)
        self.ans_text.setWordWrap(True)
        self.ans_text.setStyleSheet(f"color: {C['text_dim']}; font-size: 13px; line-height: 1.5;")
        self.ans_text.setTextInteractionFlags(Qt.TextSelectableByMouse)

        ans_lay.addWidget(ans_title)
        ans_lay.addWidget(self.ans_text)

        # 展开答案按钮
        self.toggle_btn = QPushButton("👁 查看答案")
        self.toggle_btn.setFixedHeight(30)
        self.toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C['neon']};
                border: 1px solid {C['neon']}44; border-radius: 6px;
                font-size: 12px; font-weight: 600; padding: 0 12px;
            }}
            QPushButton:hover {{ background: {C['neon']}11; border-color: {C['neon']}; }}
        """)
        self.toggle_btn.clicked.connect(self._toggle_answer)
        self.toggle_btn.setFixedWidth(100)

        lay.addLayout(header)
        lay.addWidget(q_lbl)
        lay.addWidget(self.answer_frame)
        lay.addWidget(self.toggle_btn, alignment=Qt.AlignLeft)

    def _toggle_answer(self):
        self._answer_visible = not self._answer_visible
        self.answer_frame.setVisible(self._answer_visible)
        self.toggle_btn.setText("🙈 收起答案" if self._answer_visible else "👁 查看答案")


# ── 主面板 ────────────────────────────────────────────────────────────────────
class QuizPanel(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._all_questions = []
        self._displayed_questions = []
        self._build_ui()
        self._load_stats()
        self._load_questions()

    def _build_ui(self):
        self.setStyleSheet(f"""
            QWidget {{ background: {C['bg']}; color: {C['text']}; font-family: -apple-system, "PingFang SC", sans-serif; }}
            QScrollBar:vertical {{ width: 6px; background: transparent; }}
            QScrollBar::handle:vertical {{ background: {C['border']}; border-radius: 3px; min-height: 40px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QComboBox QAbstractItemView {{ background: {C['surface']}; color: {C['text']}; selection-background-color: {C['accent2']}; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 顶部 Hero 区域 ────────────────────────────────────────────────────
        hero = QFrame()
        hero.setFixedHeight(160)
        hero.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 {C['surface2']}, stop:0.5 #1a0a2e, stop:1 {C['surface2']});
                border-bottom: 1px solid {C['border']};
            }}
        """)
        hero_lay = QVBoxLayout(hero)
        hero_lay.setContentsMargins(30, 20, 30, 20)

        title_row = QHBoxLayout()
        title = QLabel("📚  题库练习中心")
        title.setStyleSheet(f"""
            font-size: 26px; font-weight: 900; color: {C['text']};
            letter-spacing: 1px;
        """)
        subtitle = QLabel("QUESTION BANK")
        subtitle.setStyleSheet(f"font-size: 11px; color: {C['accent']}; font-weight: 700; letter-spacing: 3px; margin-top: 4px;")

        title_col = QVBoxLayout()
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        title_row.addLayout(title_col)
        title_row.addStretch()

        # 统计卡片行
        self.stats_row = QHBoxLayout()
        self.stats_row.setSpacing(12)
        self._stat_cards_widget = QWidget()
        self._stat_cards_widget.setLayout(self.stats_row)

        hero_lay.addLayout(title_row)
        hero_lay.addWidget(self._stat_cards_widget)
        root.addWidget(hero)

        # ── 工具栏 ────────────────────────────────────────────────────────────
        toolbar = QFrame()
        toolbar.setFixedHeight(60)
        toolbar.setStyleSheet(f"background: {C['surface']}; border-bottom: 1px solid {C['border']};")
        tb_lay = QHBoxLayout(toolbar)
        tb_lay.setContentsMargins(24, 0, 24, 0)
        tb_lay.setSpacing(12)

        # 搜索框
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍  搜索题目关键词...")
        self.search_box.setFixedHeight(34)
        self.search_box.setFixedWidth(220)
        self.search_box.setStyleSheet(f"""
            QLineEdit {{
                background: {C['bg']}; border: 1px solid {C['border']};
                border-radius: 8px; padding: 0 12px; color: {C['text']}; font-size: 13px;
            }}
            QLineEdit:focus {{ border-color: {C['neon']}; }}
        """)
        self.search_box.textChanged.connect(self._on_search)

        # 分类过滤
        cls_lbl = QLabel("分类")
        cls_lbl.setStyleSheet(f"color: {C['text_dim']}; font-size: 12px;")
        self.cls_combo = QComboBox()
        self.cls_combo.setFixedWidth(130)
        self._style_combo(self.cls_combo)
        self.cls_combo.addItem("全部分类", "")
        classifies = self.db.fetchall("SELECT DISTINCT classify FROM question_bank ORDER BY classify")
        for (cls,) in classifies:
            self.cls_combo.addItem(cls, cls)
        self.cls_combo.currentIndexChanged.connect(self._filter)

        # 难度过滤
        lvl_lbl = QLabel("难度")
        lvl_lbl.setStyleSheet(f"color: {C['text_dim']}; font-size: 12px;")
        self.lvl_combo = QComboBox()
        self.lvl_combo.setFixedWidth(90)
        self._style_combo(self.lvl_combo)
        self.lvl_combo.addItem("全部", "")
        for lvl in ["初级", "中级", "高级"]:
            self.lvl_combo.addItem(lvl, lvl)
        self.lvl_combo.currentIndexChanged.connect(self._filter)

        # 抽题数量
        cnt_lbl = QLabel("抽题")
        cnt_lbl.setStyleSheet(f"color: {C['text_dim']}; font-size: 12px;")
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 20)
        self.count_spin.setValue(5)
        self.count_spin.setFixedWidth(60)
        self.count_spin.setStyleSheet(f"""
            QSpinBox {{
                background: {C['bg']}; border: 1px solid {C['border']};
                border-radius: 6px; color: {C['text']}; padding: 4px 8px; font-size: 13px;
            }}
            QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; }}
        """)

        # 操作按钮
        draw_btn = self._make_btn("🎲  随机抽题", C["accent"], self._draw_random)
        all_btn = self._make_btn("📋  全部题目", C["neon"], self._show_all)
        refresh_btn = self._make_btn("🔄  刷新", C["text_dim"], self._load_questions)
        refresh_btn.setFixedWidth(70)

        tb_lay.addWidget(self.search_box)
        tb_lay.addWidget(cls_lbl)
        tb_lay.addWidget(self.cls_combo)
        tb_lay.addWidget(lvl_lbl)
        tb_lay.addWidget(self.lvl_combo)
        tb_lay.addWidget(cnt_lbl)
        tb_lay.addWidget(self.count_spin)
        tb_lay.addStretch()
        tb_lay.addWidget(draw_btn)
        tb_lay.addWidget(all_btn)
        tb_lay.addWidget(refresh_btn)
        root.addWidget(toolbar)

        # ── 内容区：题目列表 ──────────────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet(f"QScrollArea {{ background: {C['bg']}; border: none; }}")

        self._content_widget = QWidget()
        self._content_widget.setStyleSheet(f"background: {C['bg']};")
        self._content_layout = QVBoxLayout(self._content_widget)
        self._content_layout.setContentsMargins(24, 20, 24, 20)
        self._content_layout.setSpacing(14)
        self._content_layout.addStretch()

        self._scroll.setWidget(self._content_widget)
        root.addWidget(self._scroll, stretch=1)

        # ── 底部状态栏 ────────────────────────────────────────────────────────
        self._status_bar = QLabel("正在加载题库...")
        self._status_bar.setFixedHeight(28)
        self._status_bar.setAlignment(Qt.AlignCenter)
        self._status_bar.setStyleSheet(f"""
            background: {C['surface']}; color: {C['text_dim']};
            font-size: 11px; border-top: 1px solid {C['border']};
        """)
        root.addWidget(self._status_bar)

    def _style_combo(self, combo: QComboBox):
        combo.setFixedHeight(34)
        combo.setStyleSheet(f"""
            QComboBox {{
                background: {C['bg']}; border: 1px solid {C['border']};
                border-radius: 8px; padding: 0 10px; color: {C['text']}; font-size: 13px;
            }}
            QComboBox:focus {{ border-color: {C['neon']}; }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox::down-arrow {{ border: none; }}
        """)

    def _make_btn(self, text: str, color: str, slot) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedHeight(34)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {color}22; color: {color};
                border: 1px solid {color}66; border-radius: 8px;
                font-size: 13px; font-weight: 700; padding: 0 16px;
            }}
            QPushButton:hover {{ background: {color}44; border-color: {color}; }}
            QPushButton:pressed {{ background: {color}66; }}
        """)
        btn.clicked.connect(slot)
        return btn

    # ── 数据加载 ──────────────────────────────────────────────────────────────

    def _load_stats(self):
        # 清空旧卡片
        while self.stats_row.count():
            item = self.stats_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        total = self.db.fetchone("SELECT COUNT(*) FROM question_bank")[0] or 0
        easy = self.db.fetchone("SELECT COUNT(*) FROM question_bank WHERE level='初级'")[0] or 0
        mid = self.db.fetchone("SELECT COUNT(*) FROM question_bank WHERE level='中级'")[0] or 0
        hard = self.db.fetchone("SELECT COUNT(*) FROM question_bank WHERE level='高级'")[0] or 0
        cls_count = self.db.fetchone("SELECT COUNT(DISTINCT classify) FROM question_bank")[0] or 0

        cards = [
            ("📚", str(total), "总题数", C["neon"]),
            ("🟢", str(easy), "初级题", C["green"]),
            ("🟡", str(mid), "中级题", C["yellow"]),
            ("🔴", str(hard), "高级题", C["accent"]),
            ("🗂️", str(cls_count), "知识分类", "#C3A6FF"),
        ]
        for icon, val, lbl, color in cards:
            card = StatCard(icon, val, lbl, color)
            self.stats_row.addWidget(card)
        self.stats_row.addStretch()

    def _load_questions(self, classify: str = "", level: str = ""):
        rows = self.db.fetchall(
            "SELECT id, classify, level, content, answer FROM question_bank ORDER BY classify, level"
        )
        self._all_questions = rows
        self._render_questions(rows)

    def _render_questions(self, rows):
        # 清空旧卡片
        while self._content_layout.count() > 1:
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not rows:
            empty = QLabel("🔍  没有找到符合条件的题目")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(f"color: {C['text_dim']}; font-size: 16px; padding: 60px;")
            self._content_layout.insertWidget(0, empty)
            self._status_bar.setText("无结果")
            return

        for i, (qid, cls, lvl, content, answer) in enumerate(rows, 1):
            card = QuestionCard(qid, cls, lvl, content, answer, i)
            self._content_layout.insertWidget(i - 1, card)

        self._status_bar.setText(f"共显示 {len(rows)} 道题目  ·  点击「查看答案」展开参考解析")

    # ── 过滤和搜索 ────────────────────────────────────────────────────────────

    def _filter(self):
        cls = self.cls_combo.currentData()
        lvl = self.lvl_combo.currentData()
        keyword = self.search_box.text().strip().lower()

        filtered = []
        for row in self._all_questions:
            qid, q_cls, q_lvl, content, answer = row
            if cls and q_cls != cls:
                continue
            if lvl and q_lvl != lvl:
                continue
            if keyword and keyword not in content.lower() and keyword not in answer.lower():
                continue
            filtered.append(row)
        self._render_questions(filtered)

    def _on_search(self):
        self._filter()

    def _draw_random(self):
        cls = self.cls_combo.currentData()
        lvl = self.lvl_combo.currentData()
        count = self.count_spin.value()

        pool = self._all_questions
        if cls:
            pool = [r for r in pool if r[1] == cls]
        if lvl:
            pool = [r for r in pool if r[2] == lvl]

        if not pool:
            self._status_bar.setText("⚠️ 当前筛选条件下无题目可抽取")
            return

        selected = random.sample(pool, min(count, len(pool)))
        self._render_questions(selected)
        self._status_bar.setText(f"🎲 随机抽取了 {len(selected)} 道题目")

    def _show_all(self):
        self.cls_combo.setCurrentIndex(0)
        self.lvl_combo.setCurrentIndex(0)
        self.search_box.clear()
        self._render_questions(self._all_questions)

    def refresh(self):
        self._load_stats()
        self._load_questions()