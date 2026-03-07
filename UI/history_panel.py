# UI/history_panel.py
"""
历史记录与成长曲线面板 — 重构版
使用统一组件库 UI/components.py 主题色彩
"""
import json
import math

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QTextEdit, QFrame, QGraphicsDropShadowEffect,
)
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont,
    QPolygonF, QLinearGradient, QPainterPath,
)

from UI.components import (
    Theme as T, ButtonFactory, GLOBAL_QSS, combo_qss,
)


# ── 折线面积图 ────────────────────────────────────────────────────────────────

class GrowthChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scores: list[float] = []
        self.setMinimumSize(380, 220)
        self.setStyleSheet("background: transparent;")

    def set_scores(self, scores: list[float]):
        self.scores = scores
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        W, H = self.width(), self.height()
        PL, PR, PT, PB = 38, 16, 30, 28
        cw, ch = W - PL - PR, H - PT - PB

        if not self.scores:
            p.setPen(QColor(T.TEXT_DIM))
            p.setFont(QFont(T.FONT, 13))
            p.drawText(self.rect(), Qt.AlignCenter, "暂无面试记录")
            return

        # 网格线
        p.setPen(QPen(QColor(T.BORDER2), 1))
        for i in range(6):
            y = PT + ch * (1 - i / 5)
            p.drawLine(PL, int(y), W - PR, int(y))
            p.setPen(QColor(T.TEXT_MUTE))
            p.setFont(QFont(T.FONT_MONO, 8))
            p.drawText(2, int(y) + 4, str(i * 2))
            p.setPen(QPen(QColor(T.BORDER2), 1))

        # 计算坐标点
        n = len(self.scores)
        step = cw / (n - 1) if n > 1 else cw / 2
        points = [
            QPointF(PL + i * step if n > 1 else PL + cw / 2,
                    PT + ch * (1 - s / 10))
            for i, s in enumerate(self.scores)
        ]

        # 面积填充
        if len(points) > 1:
            path = QPainterPath()
            path.moveTo(points[0].x(), PT + ch)
            for pt in points:
                path.lineTo(pt)
            path.lineTo(points[-1].x(), PT + ch)

            grad = QLinearGradient(0, PT, 0, PT + ch)
            grad.setColorAt(0, QColor(T.NEON).lighter(120))
            grad.setColorAt(0, QColor(0, 212, 255, 50))
            grad.setColorAt(1, QColor(0, 212, 255, 0))
            p.fillPath(path, QBrush(grad))

        # 折线
        neon = QColor(T.NEON)
        p.setPen(QPen(neon, 2.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for i in range(len(points) - 1):
            p.drawLine(points[i], points[i + 1])

        # 节点
        for pt in points:
            p.setPen(Qt.NoPen)
            p.setBrush(neon)
            p.drawEllipse(pt, 5, 5)
            p.setBrush(QColor(T.SURFACE))
            p.drawEllipse(pt, 2.5, 2.5)
            p.setBrush(neon)

        # X 轴标签
        p.setPen(QColor(T.TEXT_MUTE))
        p.setFont(QFont(T.FONT, 8))
        for i, pt in enumerate(points):
            p.drawText(int(pt.x()) - 8, H - 4, f"#{i + 1}")


# ── 雷达图 ────────────────────────────────────────────────────────────────────

class RadarChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data: dict = {}
        self.setMinimumSize(260, 260)
        self.setStyleSheet("background: transparent;")

    def set_data(self, data: dict):
        self.data = data
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        r = min(cx, cy) - 44

        if not self.data:
            p.setPen(QColor(T.TEXT_DIM))
            p.drawText(self.rect(), Qt.AlignCenter, "等待数据...")
            return

        cats = list(self.data.keys())
        n = len(cats)
        step = 2 * math.pi / n

        # 蜘蛛网
        p.setPen(QPen(QColor(T.BORDER2), 1))
        for level in range(1, 6):
            cur_r = r * (level / 5)
            pts = [QPointF(cx + cur_r * math.cos(i * step - math.pi / 2),
                           cy + cur_r * math.sin(i * step - math.pi / 2)) for i in range(n)]
            p.drawPolygon(QPolygonF(pts + [pts[0]]))

        # 轴线和标签
        p.setPen(QPen(QColor(T.BORDER2), 1))
        p.setFont(QFont(T.FONT, 10, QFont.Bold))
        p.setPen(QColor(T.TEXT_DIM))
        for i, cat in enumerate(cats):
            angle = i * step - math.pi / 2
            ex, ey = cx + r * math.cos(angle), cy + r * math.sin(angle)
            p.setPen(QPen(QColor(T.BORDER2), 1))
            p.drawLine(int(cx), int(cy), int(ex), int(ey))
            tx, ty = cx + (r + 22) * math.cos(angle), cy + (r + 22) * math.sin(angle)
            p.setPen(QColor(T.TEXT_DIM))
            fm = p.fontMetrics()
            bw = fm.horizontalAdvance(cat)
            p.drawText(int(tx - bw / 2), int(ty + 4), cat)

        # 数据区域
        data_pts = [
            QPointF(cx + r * (self.data.get(cat, 0) / 10) * math.cos(i * step - math.pi / 2),
                    cy + r * (self.data.get(cat, 0) / 10) * math.sin(i * step - math.pi / 2))
            for i, cat in enumerate(cats)
        ]
        poly = QPolygonF(data_pts + [data_pts[0]])
        p.setPen(QPen(QColor(T.NEON), 2))
        p.setBrush(QColor(0, 212, 255, 35))
        p.drawPolygon(poly)

        # 数据点
        p.setBrush(QColor(T.NEON))
        p.setPen(Qt.NoPen)
        for pt in data_pts:
            p.drawEllipse(pt, 4, 4)


# ── 暗色卡片 ──────────────────────────────────────────────────────────────────

class DarkCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background: {T.SURFACE};
                border: 1px solid {T.BORDER};
                border-radius: 12px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setColor(QColor(0, 0, 0, 80))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)


# ── 主面板 ────────────────────────────────────────────────────────────────────

class HistoryPanel(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet(GLOBAL_QSS + combo_qss())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_header())

        # 主内容区
        content = QWidget()
        content.setStyleSheet(f"background: {T.BG};")
        c_lay = QVBoxLayout(content)
        c_lay.setContentsMargins(26, 20, 26, 20)
        c_lay.setSpacing(18)

        c_lay.addLayout(self._build_charts())
        c_lay.addWidget(self._build_report(), stretch=1)
        layout.addWidget(content, stretch=1)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setFixedHeight(58)
        header.setStyleSheet(f"""
            QFrame {{
                background: {T.SURFACE};
                border-bottom: 1px solid {T.BORDER};
            }}
        """)
        lay = QHBoxLayout(header)
        lay.setContentsMargins(26, 0, 26, 0)
        lay.setSpacing(12)

        title = QLabel("📊  成长实验室")
        title.setStyleSheet(f"font-size: 16px; font-weight: 800; color: {T.TEXT}; font-family: {T.FONT};")

        member_lbl = QLabel("成员")
        member_lbl.setStyleSheet(f"color: {T.TEXT_DIM}; font-size: 12px;")

        self.student_combo = QComboBox()
        self.student_combo.setFixedSize(160, 34)

        sync_btn = ButtonFactory.solid("同步数据", T.NEON, height=34)
        sync_btn.setFixedWidth(90)
        sync_btn.clicked.connect(self._refresh)

        lay.addWidget(title)
        lay.addStretch()
        lay.addWidget(member_lbl)
        lay.addWidget(self.student_combo)
        lay.addWidget(sync_btn)

        self.student_combo.currentIndexChanged.connect(self._load_student_data)
        return header

    def _build_charts(self) -> QHBoxLayout:
        charts = QHBoxLayout()
        charts.setSpacing(16)

        # 折线图卡片
        growth_card = DarkCard()
        g_lay = QVBoxLayout(growth_card)
        g_lay.setContentsMargins(16, 14, 16, 14)
        g_title = QLabel("📈  综合得分趋势")
        g_title.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {T.NEON}; background: transparent; font-family: {T.FONT};")
        self.growth_chart = GrowthChart()
        g_lay.addWidget(g_title)
        g_lay.addWidget(self.growth_chart)

        # 雷达图卡片
        radar_card = DarkCard()
        r_lay = QVBoxLayout(radar_card)
        r_lay.setContentsMargins(16, 14, 16, 14)
        r_title = QLabel("🎯  最近能力维度")
        r_title.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {T.PURPLE}; background: transparent; font-family: {T.FONT};")
        self.radar_chart = RadarChart()
        r_lay.addWidget(r_title)
        r_lay.addWidget(self.radar_chart)

        charts.addWidget(growth_card, stretch=6)
        charts.addWidget(radar_card, stretch=4)
        return charts

    def _build_report(self) -> DarkCard:
        card = DarkCard()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(8)

        title = QLabel("📝  最近面试表现回顾")
        title.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {T.YELLOW}; background: transparent; font-family: {T.FONT};")

        self.report_view = QTextEdit()
        self.report_view.setReadOnly(True)
        self.report_view.setFrameShape(QFrame.NoFrame)
        self.report_view.setPlaceholderText("选择成员后查看详细历史面试反馈...")
        self.report_view.setStyleSheet(f"""
            QTextEdit {{
                background: transparent;
                color: {T.TEXT};
                font-size: 13px;
                border: none;
                font-family: {T.FONT};
                line-height: 1.7;
            }}
        """)

        lay.addWidget(title)
        lay.addWidget(self.report_view)
        return card

    # ── 数据逻辑（与原版相同） ────────────────────────────────────────────────

    def _refresh(self):
        self.student_combo.blockSignals(True)
        self.student_combo.clear()
        rows = self.db.fetchall("SELECT id, name FROM student ORDER BY id DESC")
        for sid, name in rows:
            self.student_combo.addItem(name, sid)
        self.student_combo.blockSignals(False)
        if self.student_combo.count() > 0:
            self._load_student_data()

    def _load_student_data(self):
        sid = self.student_combo.currentData()
        if not sid:
            return

        sessions = self.db.fetchall(
            "SELECT id, overall_score, report, started_at FROM interview_session "
            "WHERE student_id=? AND status='finished' ORDER BY started_at", (sid,)
        )
        if not sessions:
            self.growth_chart.set_scores([])
            self.radar_chart.set_data({})
            self.report_view.setPlainText("暂无已完成的面试记录。")
            return

        scores = [s[1] for s in sessions if s[1] is not None]
        self.growth_chart.set_scores(scores)

        latest = sessions[-1]
        self.report_view.setMarkdown(latest[2] or "无报告内容")

        turns = self.db.fetchall(
            "SELECT scores FROM interview_turn WHERE session_id=? AND scores IS NOT NULL", (latest[0],)
        )
        if turns:
            dim_totals = {"技术": [], "逻辑": [], "深度": [], "表达": []}
            key_map = {"tech": "技术", "logic": "逻辑", "depth": "深度", "clarity": "表达"}
            for (sc_json,) in turns:
                sc = json.loads(sc_json)
                for k, cn in key_map.items():
                    if k in sc:
                        dim_totals[cn].append(sc[k])
            radar_data = {cn: round(sum(v) / len(v), 1) if v else 0 for cn, v in dim_totals.items()}
            self.radar_chart.set_data(radar_data)