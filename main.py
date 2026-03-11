# main.py
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QHBoxLayout, QTabWidget,
)

from service.db import DatabaseManager
from service.schema import SchemaInitializer
from service.knowledge_store import KnowledgeStore
from service.interview_engine import InterviewEngine
from service.agent_core import Agent
from service.tools import get_tools

from UI.interview_panel import InterviewPanel
from UI.agent_panel import AgentPanel
from UI.history_panel import HistoryPanel
from UI.quiz_panel import QuizPanel
from UI.components import Theme as T


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # ── 基础服务 ──────────────────────────────────────────────────────────────
    db = DatabaseManager("interview.db")
    SchemaInitializer(db).initialize()

    # 百炼云端知识库，仅做检索，无需本地导入文件
    ks = KnowledgeStore(db)

    engine = InterviewEngine(db, ks)

    # ── Agent ─────────────────────────────────────────────────────────────────
    agent = Agent(
        db=db,
        system_prompt="""你是一位专业的求职面试辅导助手。
你可以帮助用户：
1. 从题库随机抽题或搜索题目（使用 draw_questions_from_bank / search_question_bank）
2. 查看题库统计（使用 get_question_bank_stats）
3. 查询岗位技术要求（使用 get_job_position_info）
4. 从知识库检索技术概念（使用 search_knowledge_base）
5. 联网搜索最新技术资料（使用 web_search）
6. 查看学生历史面试表现（使用 get_student_interview_history）

请用简洁、专业的中文回答。优先查询知识库！知识库没有时再联网搜索。
输出格式清晰，善用 Markdown 标题和列表。""",
    )
    tools = get_tools(db, ks)
    agent.register_tools(tools)

    # ── 主窗口 ────────────────────────────────────────────────────────────────
    window = QMainWindow()
    window.setWindowTitle("AI 模拟面试与能力提升平台")
    window.resize(1340, 880)
    window.setStyleSheet(f"QMainWindow {{ background: {T.BG}; }}")

    central = QWidget()
    window.setCentralWidget(central)
    root = QHBoxLayout(central)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    tabs = QTabWidget()
    tabs.setStyleSheet(f"""
        QTabWidget::pane {{ border: none; background: {T.BG}; }}
        QTabBar {{ background: {T.SURFACE}; }}
        QTabBar::tab {{
            background: {T.SURFACE}; color: {T.TEXT_DIM};
            padding: 12px 26px; font-size: 13px; font-weight: 600;
            font-family: {T.FONT}; border: none;
            border-bottom: 2px solid transparent; min-width: 100px;
        }}
        QTabBar::tab:selected {{
            color: {T.NEON}; border-bottom: 2px solid {T.NEON}; background: {T.BG};
        }}
        QTabBar::tab:hover:!selected {{ color: {T.TEXT}; background: {T.SURFACE2}; }}
    """)

    interview_panel = InterviewPanel(db, engine)
    history_panel   = HistoryPanel(db)
    quiz_panel      = QuizPanel(db)
    agent_panel     = AgentPanel(agent)

    tabs.addTab(interview_panel, "🎯  模拟面试")
    tabs.addTab(quiz_panel,      "📚  题库练习")
    tabs.addTab(history_panel,   "📊  历史分析")
    tabs.addTab(agent_panel,     "🤖  AI 助手")

    root.addWidget(tabs)

    tabs.currentChanged.connect(
        lambda idx: history_panel._refresh() if tabs.widget(idx) is history_panel else None
    )

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()