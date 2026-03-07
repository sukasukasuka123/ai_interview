# service/tools/registry.py
"""
面试 Agent 工具集
包含：
  1. 查询学生历史面试记录
  2. 查询岗位信息
  3. 知识库检索（RAG）
  4. 题库抽题工具（按分类/难度随机抽题）
  5. 题库内容查询（精确搜索）
  6. DuckDuckGo 网络搜索
  7. Wikipedia 技术概念查询
"""
import json
import os
import random
from typing import List, Optional

from langchain_core.tools import tool

try:
    from langchain_community.tools import DuckDuckGoSearchRun
except ImportError:
    from langchain_community.tools.ddg_search.tool import DuckDuckGoSearchRun

try:
    from langchain_community.tools import WikipediaQueryRun
    from langchain_community.utilities import WikipediaAPIWrapper
except ImportError:
    from langchain_community.tools.wikipedia.tool import WikipediaQueryRun
    from langchain_community.utilities.wikipedia import WikipediaAPIWrapper


# ── Tool 1：查询学生面试历史 ──────────────────────────────────────────────────

def create_history_tool(db):
    @tool
    def get_student_interview_history(student_id: int) -> str:
        """查询指定学生的历史面试记录，包含各次面试的岗位、得分和时间。"""
        rows = db.fetchall(
            """
            SELECT s.name, jp.name, iss.started_at, iss.overall_score, iss.status
            FROM interview_session iss
            JOIN student s ON iss.student_id = s.id
            JOIN job_position jp ON iss.job_position_id = jp.id
            WHERE iss.student_id = ?
            ORDER BY iss.started_at DESC
            """,
            (student_id,),
        )
        if not rows:
            return f"学生 ID={student_id} 暂无面试记录。"

        lines = [f"学生「{rows[0][0]}」历史面试记录（共 {len(rows)} 次）："]
        for student_name, job_name, started_at, score, status in rows:
            score_str = f"{score:.1f}/10" if score else "未完成"
            lines.append(f"  - 岗位：{job_name}  得分：{score_str}  时间：{started_at[:10]}  状态：{status}")
        return "\n".join(lines)

    return get_student_interview_history


# ── Tool 2：查询岗位信息 ──────────────────────────────────────────────────────

def create_job_info_tool(db):
    @tool
    def get_job_position_info(job_position_id: Optional[int] = None) -> str:
        """查询岗位信息。不传 ID 则列出所有岗位；传入 ID 则返回该岗位的详细技术栈。"""
        if job_position_id is None:
            rows = db.fetchall("SELECT id, name, description FROM job_position")
            if not rows:
                return "暂无岗位信息。"
            lines = ["当前支持的面试岗位："]
            for jid, name, desc in rows:
                lines.append(f"  [{jid}] {name}：{desc or '无描述'}")
            return "\n".join(lines)

        row = db.fetchone(
            "SELECT name, description, tech_stack FROM job_position WHERE id=?",
            (job_position_id,),
        )
        if not row:
            return f"未找到岗位 ID={job_position_id}"
        name, desc, tech_json = row
        tech = json.loads(tech_json)
        return f"岗位：{name}\n描述：{desc}\n核心技术栈：{', '.join(tech)}"

    return get_job_position_info


# ── Tool 3：知识库 RAG 检索 ───────────────────────────────────────────────────

def create_rag_tool(knowledge_store):
    @tool
    def search_knowledge_base(query: str, job_position_id: int = 0) -> str:
        """
        从本地知识库检索与问题相关的技术知识。
        job_position_id=0 表示通用知识库；1=Java后端；2=前端。
        适合查询面试题答案、技术概念、最佳实践。
        """
        results = knowledge_store.retrieve(query, job_position_id=job_position_id, top_k=3)
        if not results:
            return "知识库中未找到相关内容。"
        lines = [f"知识库检索结果（关键词：{query}）："]
        for i, r in enumerate(results, 1):
            lines.append(f"\n[{i}] {r}")
        return "\n".join(lines)

    return search_knowledge_base


# ── Tool 4：题库抽题 ──────────────────────────────────────────────────────────

def create_quiz_draw_tool(db):
    @tool
    def draw_questions_from_bank(
        classify: str = "",
        level: str = "",
        count: int = 5,
    ) -> str:
        """
        从题库按分类和难度随机抽题。
        classify：题目分类，如 'Java基础'、'MySQL'、'Redis'、'JavaScript'、'Vue/React'、'Spring'、'JVM'、'计算机网络'、'数据结构与算法'。留空则不限分类。
        level：难度，'初级'/'中级'/'高级'，留空则不限难度。
        count：抽题数量，默认5题，最多20题。
        """
        count = min(count, 20)
        sql = "SELECT id, classify, level, content FROM question_bank WHERE 1=1"
        params = []
        if classify:
            sql += " AND classify=?"
            params.append(classify)
        if level:
            sql += " AND level=?"
            params.append(level)

        rows = db.fetchall(sql, tuple(params))
        if not rows:
            return f"未找到符合条件的题目（分类={classify or '不限'}，难度={level or '不限'}）。"

        selected = random.sample(rows, min(count, len(rows)))
        lines = [f"📚 已从题库抽取 {len(selected)} 道题目：\n"]
        for i, (qid, cls, lvl, content) in enumerate(selected, 1):
            lines.append(f"**Q{i}** [{cls} · {lvl}]\n{content}\n")
        return "\n".join(lines)

    return draw_questions_from_bank


# ── Tool 5：题库内容精确查询 ──────────────────────────────────────────────────

def create_quiz_search_tool(db):
    @tool
    def search_question_bank(keyword: str, show_answer: bool = True) -> str:
        """
        在题库中关键词搜索题目。
        keyword：搜索关键词（在题目内容中模糊匹配）。
        show_answer：是否显示参考答案，默认显示。
        """
        rows = db.fetchall(
            "SELECT id, classify, level, content, answer FROM question_bank "
            "WHERE content LIKE ? OR answer LIKE ? LIMIT 10",
            (f"%{keyword}%", f"%{keyword}%"),
        )
        if not rows:
            return f"题库中未找到包含「{keyword}」的题目。"

        lines = [f"🔍 搜索「{keyword}」共找到 {len(rows)} 道题目：\n"]
        for qid, cls, lvl, content, answer in rows:
            lines.append(f"**[{cls} · {lvl}]** {content}")
            if show_answer:
                lines.append(f"📝 参考答案：{answer[:200]}{'...' if len(answer) > 200 else ''}")
            lines.append("")
        return "\n".join(lines)

    return search_question_bank


# ── Tool 6：题库分类统计 ──────────────────────────────────────────────────────

def create_quiz_stats_tool(db):
    @tool
    def get_question_bank_stats() -> str:
        """
        查看题库的整体统计：各分类、各难度的题目数量分布。
        """
        rows = db.fetchall(
            "SELECT classify, level, COUNT(*) as cnt FROM question_bank GROUP BY classify, level ORDER BY classify, level"
        )
        if not rows:
            return "题库暂无数据。"

        total = db.fetchone("SELECT COUNT(*) FROM question_bank")[0]
        lines = [f"📊 题库统计（共 {total} 题）：\n"]

        current_cls = None
        for cls, lvl, cnt in rows:
            if cls != current_cls:
                current_cls = cls
                lines.append(f"\n**{cls}**")
            lines.append(f"  {lvl}：{cnt} 题")

        # 获取所有分类列表
        classifies = db.fetchall("SELECT DISTINCT classify FROM question_bank ORDER BY classify")
        lines.append(f"\n可用分类：{', '.join(r[0] for r in classifies)}")
        return "\n".join(lines)

    return get_question_bank_stats


# ── Tool 7：DuckDuckGo 网络搜索 ───────────────────────────────────────────────

def create_web_search_tool():
    _search = DuckDuckGoSearchRun()

    @tool
    def web_search(query: str) -> str:
        """
        通过 DuckDuckGo 搜索最新技术资料、新闻、框架更新等。
        适合查询本地知识库没有的最新信息（如某框架最新版本特性、行业趋势）。
        """
        try:
            return _search.run(query)
        except Exception as e:
            return f"搜索失败：{e}"

    return web_search


# ── Tool 8：Wikipedia 技术概念查询 ────────────────────────────────────────────

def create_wiki_tool():
    _wiki = WikipediaQueryRun(
        api_wrapper=WikipediaAPIWrapper(lang="zh", top_k_results=2, doc_content_chars_max=800)
    )

    @tool
    def search_wikipedia(query: str) -> str:
        """
        从 Wikipedia 查询技术概念的权威定义和背景知识。
        适合查询算法、数据结构、设计模式、计算机科学概念等基础知识。
        优先使用中文维基百科。
        """
        try:
            return _wiki.run(query)
        except Exception as e:
            return f"Wikipedia 查询失败：{e}"

    return search_wikipedia


# ── 工具注册入口 ──────────────────────────────────────────────────────────────

def get_tools(db, knowledge_store) -> list:
    """返回面试 Agent 的全部工具列表。"""
    return [
        create_history_tool(db),
        create_job_info_tool(db),
        create_rag_tool(knowledge_store),
        create_quiz_draw_tool(db),
        create_quiz_search_tool(db),
        create_quiz_stats_tool(db),
        create_web_search_tool(),
        create_wiki_tool(),
    ]