# UI/quiz_panel.py
"""
题库管理与练习面板 — 重构版
使用统一组件库 UI/components.py
"""
import random

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QScrollArea, QFrame, QTextBrowser, QSpinBox,
    QSizePolicy, QLineEdit, QGraphicsDropShadowEffect,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor

from UI.components import (
    Theme as T, StatBadge, ButtonFactory,
    GLOBAL_QSS, combo_qss, input_qss,
)

# ── 分类色彩映射 ──────────────────────────────────────────────────────────────
CLASSIFY_COLORS = {
    "Java基础":       T.ACCENT,
    "JVM":            T.NEON,
    "Spring":         T.YELLOW,
    "MySQL":          T.GREEN,
    "Redis":          T.GREEN,
    "JavaScript":     T.YELLOW,
    "Vue/React":      "#00D2D3",
    "计算机网络":     T.PURPLE,
    "数据结构与算法": T.PURPLE,
}
LEVEL_COLORS = {
    "初级": (T.GREEN,  f"{T.GREEN}15"),
    "中级": (T.YELLOW, f"{T.YELLOW}15"),
    "高级": (T.ACCENT, f"{T.ACCENT}15"),
}

def _cls_color(cls: str) -> str:
    return CLASSIFY_COLORS.get(cls, T.NEON)


# ── 题目卡片 ──────────────────────────────────────────────────────────────────

class QuestionCard(QFrame):
    def __init__(self, qid: int, classify: str, level: str, content: str, answer: str, index: int, parent=None):
        super().__init__(parent)
        self._answer_visible = False
        self.setObjectName("QCard")

        cls_color = _cls_color(classify)
        lvl_fg, lvl_bg = LEVEL_COLORS.get(level, (T.TEXT_DIM, T.SURFACE))

        self.setStyleSheet(f"""
            QFrame#QCard {{
                background: {T.SURFACE};
                border: 1px solid {T.BORDER};
                border-left: 3px solid {cls_color};
                border-radius: 10px;
            }}
            QFrame#QCard:hover {{
                background: {T.SURFACE2};
                border-color: {cls_color}66;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(12)
        shadow.setColor(QColor(0, 0, 0, 60))
        shadow.setOffset(0, 2)
        self.setGraphicsEffect(shadow)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(10)

        # ── 顶部标签行 ────────────────────────────────────────────────────────
        header = QHBoxLayout()
        header.setSpacing(6)

        num_lbl = QLabel(f"#{index:02d}")
        num_lbl.setStyleSheet(f"""
            color: {T.TEXT_MUTE}; font-size: 11px;
            font-family: {T.FONT_MONO}; font-weight: 700;
            background: transparent;
        """)

        cls_tag = QLabel(f" {classify} ")
        cls_tag.setStyleSheet(f"""
            background: {cls_color}18; color: {cls_color};
            border: 1px solid {cls_color}55; border-radius: 4px;
            font-size: 11px; font-weight: 700; padding: 1px 7px;
            font-family: {T.FONT};
        """)

        lvl_tag = QLabel(f" {level} ")
        lvl_tag.setStyleSheet(f"""
            background: {lvl_bg}; color: {lvl_fg};
            border-radius: 4px; font-size: 11px;
            font-weight: 700; padding: 1px 7px;
            font-family: {T.FONT};
        """)

        header.addWidget(num_lbl)
        header.addWidget(cls_tag)
        header.addWidget(lvl_tag)
        header.addStretch()
        lay.addLayout(header)

        # ── 题目内容 ──────────────────────────────────────────────────────────
        q_lbl = QLabel(content)
        q_lbl.setWordWrap(True)
        q_lbl.setStyleSheet(f"""
            color: {T.TEXT}; font-size: 14px;
            line-height: 1.6; font-weight: 500;
            background: transparent;
            font-family: {T.FONT};
        """)
        lay.addWidget(q_lbl)

        # ── 答案折叠区 ────────────────────────────────────────────────────────
        self.answer_frame = QFrame()
        self.answer_frame.setVisible(False)
        self.answer_frame.setStyleSheet(f"""
            QFrame {{
                background: {T.SURFACE3};
                border: 1px solid {T.NEON}22;
                border-radius: 8px;
            }}
        """)
        ans_lay = QVBoxLayout(self.answer_frame)
        ans_lay.setContentsMargins(12, 10, 12, 10)
        ans_lay.setSpacing(4)

        ans_title = QLabel("💡  参考答案")
        ans_title.setStyleSheet(f"""
            color: {T.NEON}; font-size: 11px; font-weight: 700;
            background: transparent; font-family: {T.FONT};
        """)

        self.ans_text = QLabel(answer)
        self.ans_text.setWordWrap(True)
        self.ans_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.ans_text.setStyleSheet(f"""
            color: {T.TEXT_DIM}; font-size: 13px; line-height: 1.6;
            background: transparent; font-family: {T.FONT};
        """)

        ans_lay.addWidget(ans_title)
        ans_lay.addWidget(self.ans_text)
        lay.addWidget(self.answer_frame)

        # ── 展开按钮 ──────────────────────────────────────────────────────────
        self.toggle_btn = ButtonFactory.primary("👁  查看答案", T.NEON, height=28)
        self.toggle_btn.setFixedWidth(100)
        self.toggle_btn.clicked.connect(self._toggle_answer)
        lay.addWidget(self.toggle_btn, alignment=Qt.AlignLeft)

    def _toggle_answer(self):
        self._answer_visible = not self._answer_visible
        self.answer_frame.setVisible(self._answer_visible)
        self.toggle_btn.setText("🙈  收起答案" if self._answer_visible else "👁  查看答案")


# ── 主面板 ────────────────────────────────────────────────────────────────────

class QuizPanel(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._all_questions = []
        self._build_ui()
        self._load_stats()
        self._load_questions()

    def _build_ui(self):
        self.setStyleSheet(GLOBAL_QSS + combo_qss() + input_qss() + f"""
            QSpinBox {{
                background: {T.BG}; border: 1px solid {T.BORDER2};
                border-radius: 6px; color: {T.TEXT}; padding: 4px 8px;
                font-size: 13px; font-family: {T.FONT};
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_hero())
        root.addWidget(self._build_toolbar())
        root.addWidget(self._build_content(), stretch=1)
        root.addWidget(self._build_statusbar())

    def _build_hero(self) -> QFrame:
        hero = QFrame()
        hero.setFixedHeight(148)
        hero.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 {T.SURFACE2},
                    stop:0.45 #0D0D20,
                    stop:1 {T.SURFACE3}
                );
                border-bottom: 1px solid {T.BORDER};
            }}
        """)
        lay = QVBoxLayout(hero)
        lay.setContentsMargins(28, 16, 28, 16)
        lay.setSpacing(12)

        title_row = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)

        title = QLabel("📚  题库练习中心")
        title.setStyleSheet(f"font-size: 22px; font-weight: 900; color: {T.TEXT}; font-family: {T.FONT}; background: transparent;")
        sub = QLabel("QUESTION BANK · PRACTICE MODE")
        sub.setStyleSheet(f"font-size: 10px; color: {T.ACCENT}; font-weight: 700; letter-spacing: 3px; background: transparent; font-family: {T.FONT};")

        col.addWidget(title)
        col.addWidget(sub)
        title_row.addLayout(col)
        title_row.addStretch()

        self._stats_container = QHBoxLayout()
        self._stats_container.setSpacing(10)
        self._stats_widget = QWidget()
        self._stats_widget.setStyleSheet("background: transparent;")
        self._stats_widget.setLayout(self._stats_container)
        title_row.addWidget(self._stats_widget)

        lay.addLayout(title_row)
        return hero

    def _build_toolbar(self) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(56)
        bar.setStyleSheet(f"""
            QFrame {{
                background: {T.SURFACE};
                border-bottom: 1px solid {T.BORDER};
            }}
        """)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(22, 0, 22, 0)
        lay.setSpacing(10)

        # 搜索框
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍  搜索题目关键词...")
        self.search_box.setFixedSize(210, 34)
        self.search_box.textChanged.connect(self._on_filter)

        # 分类
        cls_lbl = QLabel("分类")
        cls_lbl.setStyleSheet(f"color: {T.TEXT_DIM}; font-size: 12px;")
        self.cls_combo = QComboBox()
        self.cls_combo.setFixedSize(130, 34)
        self.cls_combo.addItem("全部分类", "")
        classifies = self.db.fetchall("SELECT DISTINCT classify FROM question_bank ORDER BY classify")
        for (cls,) in classifies:
            self.cls_combo.addItem(cls, cls)
        self.cls_combo.currentIndexChanged.connect(self._on_filter)

        # 难度
        lvl_lbl = QLabel("难度")
        lvl_lbl.setStyleSheet(f"color: {T.TEXT_DIM}; font-size: 12px;")
        self.lvl_combo = QComboBox()
        self.lvl_combo.setFixedSize(86, 34)
        self.lvl_combo.addItem("全部", "")
        for lvl in ["初级", "中级", "高级"]:
            self.lvl_combo.addItem(lvl, lvl)
        self.lvl_combo.currentIndexChanged.connect(self._on_filter)

        # 抽题数量
        cnt_lbl = QLabel("抽")
        cnt_lbl.setStyleSheet(f"color: {T.TEXT_DIM}; font-size: 12px;")
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 20)
        self.count_spin.setValue(5)
        self.count_spin.setFixedSize(58, 34)

        lay.addWidget(self.search_box)
        lay.addSpacing(4)
        lay.addWidget(cls_lbl)
        lay.addWidget(self.cls_combo)
        lay.addWidget(lvl_lbl)
        lay.addWidget(self.lvl_combo)
        lay.addWidget(cnt_lbl)
        lay.addWidget(self.count_spin)
        lay.addStretch()

        draw_btn = ButtonFactory.solid("🎲  随机抽题", T.ACCENT, height=34)
        all_btn  = ButtonFactory.primary("📋  全部题目", T.NEON, height=34)
        ref_btn  = ButtonFactory.ghost("🔄 刷新")
        ref_btn.setFixedSize(60, 34)

        draw_btn.clicked.connect(self._draw_random)
        all_btn.clicked.connect(self._show_all)
        ref_btn.clicked.connect(self.refresh)

        lay.addWidget(draw_btn)
        lay.addWidget(all_btn)
        lay.addWidget(ref_btn)
        return bar

    def _build_content(self) -> QScrollArea:
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet(f"QScrollArea {{ background: {T.BG}; border: none; }}")

        self._content_widget = QWidget()
        self._content_widget.setStyleSheet(f"background: {T.BG};")
        self._content_layout = QVBoxLayout(self._content_widget)
        self._content_layout.setContentsMargins(22, 18, 22, 18)
        self._content_layout.setSpacing(12)
        self._content_layout.addStretch()

        self._scroll.setWidget(self._content_widget)
        return self._scroll

    def _build_statusbar(self) -> QLabel:
        self._status_bar = QLabel("正在加载题库...")
        self._status_bar.setFixedHeight(26)
        self._status_bar.setAlignment(Qt.AlignCenter)
        self._status_bar.setStyleSheet(f"""
            background: {T.SURFACE};
            color: {T.TEXT_DIM};
            font-size: 11px;
            border-top: 1px solid {T.BORDER};
            font-family: {T.FONT};
        """)
        return self._status_bar

    # ── 数据加载 ──────────────────────────────────────────────────────────────

    def _load_stats(self):
        while self._stats_container.count():
            item = self._stats_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        total     = self.db.fetchone("SELECT COUNT(*) FROM question_bank")[0] or 0
        easy      = self.db.fetchone("SELECT COUNT(*) FROM question_bank WHERE level='初级'")[0] or 0
        mid       = self.db.fetchone("SELECT COUNT(*) FROM question_bank WHERE level='中级'")[0] or 0
        hard      = self.db.fetchone("SELECT COUNT(*) FROM question_bank WHERE level='高级'")[0] or 0
        cls_count = self.db.fetchone("SELECT COUNT(DISTINCT classify) FROM question_bank")[0] or 0

        for icon, val, lbl, color in [
            ("📚", str(total),     "总题数", T.NEON),
            ("🟢", str(easy),      "初级",   T.GREEN),
            ("🟡", str(mid),       "中级",   T.YELLOW),
            ("🔴", str(hard),      "高级",   T.ACCENT),
            ("🗂", str(cls_count), "分类",   T.PURPLE),
        ]:
            card = StatBadge(icon, val, lbl, color)
            self._stats_container.addWidget(card)

    def _load_questions(self):
        rows = self.db.fetchall(
            "SELECT id, classify, level, content, answer FROM question_bank ORDER BY classify, level"
        )
        self._all_questions = rows
        self._render(rows)

    def _render(self, rows):
        while self._content_layout.count() > 1:
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not rows:
            empty = QLabel("🔍  没有找到符合条件的题目")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(f"color: {T.TEXT_DIM}; font-size: 15px; padding: 60px; background: transparent;")
            self._content_layout.insertWidget(0, empty)
            self._status_bar.setText("无结果")
            return

        for i, (qid, cls, lvl, content, answer) in enumerate(rows, 1):
            card = QuestionCard(qid, cls, lvl, content, answer, i)
            self._content_layout.insertWidget(i - 1, card)

        self._status_bar.setText(f"共显示 {len(rows)} 道题  ·  点击「查看答案」展开解析")

    # ── 过滤 ──────────────────────────────────────────────────────────────────

    def _on_filter(self):
        cls     = self.cls_combo.currentData()
        lvl     = self.lvl_combo.currentData()
        keyword = self.search_box.text().strip().lower()

        filtered = [
            r for r in self._all_questions
            if (not cls or r[1] == cls)
            and (not lvl or r[2] == lvl)
            and (not keyword or keyword in r[3].lower() or keyword in r[4].lower())
        ]
        self._render(filtered)

    def _draw_random(self):
        cls   = self.cls_combo.currentData()
        lvl   = self.lvl_combo.currentData()
        count = self.count_spin.value()
        pool  = [r for r in self._all_questions
                 if (not cls or r[1] == cls) and (not lvl or r[2] == lvl)]

        if not pool:
            self._status_bar.setText("⚠️ 当前筛选条件下无题目可抽取")
            return

        selected = random.sample(pool, min(count, len(pool)))
        self._render(selected)
        self._status_bar.setText(f"🎲  随机抽取了 {len(selected)} 道题")

    def _show_all(self):
        self.cls_combo.setCurrentIndex(0)
        self.lvl_combo.setCurrentIndex(0)
        self.search_box.clear()
        self._render(self._all_questions)

    def refresh(self):
        self._load_stats()
        self._load_questions()