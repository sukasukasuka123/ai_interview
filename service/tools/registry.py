# service/tools/registry.py
"""
工具注册中心

职责：
  1. 构建所有可用工具实例（懒加载，失败时跳过并打印警告）
  2. 根据 SkillSet 筛选并返回工具列表
  3. 提供兼容旧接口的便捷函数

知识库工具的两种使用方式（均支持）：
  方式 A — 由 registry 自动从 env 读取 kb_id 并构造 KnowledgeCore（推荐）：
      tools = get_interview_tools(db)                 # DS_COURSE_KB_ID 自动从 env 读
      tools = get_assistant_tools(db)                 # TECH_KB_ID      自动从 env 读

  方式 B — 外部手动传入 KnowledgeCore 实例（main.py 显式控制时使用）：
      tech_kb   = KnowledgeCore(knowledge_base_id=os.getenv("TECH_KB_ID"), label="技术")
      course_kb = KnowledgeCore(knowledge_base_id=os.getenv("DS_COURSE_KB_ID"), label="课程")
      tools     = get_tools_for(db=db, tech_kb=tech_kb, ds_course_kb=course_kb, skill_set=...)
"""
from __future__ import annotations

from typing import Any, Optional

from .db_tools import (
    create_history_tool,
    create_student_lookup_tool,
    create_job_info_tool,
    create_quiz_draw_tool,
    create_quiz_search_tool,
    create_quiz_stats_tool,
)
from .knowledge import (
    KnowledgeCore,
    create_knowledge_search_tool,
    create_ds_course_tool,
)
from .search_tools import create_web_search_tool, create_wiki_tool
from .permissions import (
    SkillSet,
    INTERVIEW_SKILLS,
    READONLY_SKILLS,
    ASSISTANT_SKILLS,
    ADMIN_SKILLS,
)
from .difficulty_tools import create_difficulty_tool



def build_tools(
    db=None,
    tech_kb: Optional[KnowledgeCore] = None,
    ds_course_kb: Optional[KnowledgeCore] = None,
) -> dict[str, Any]:
    """
    构建所有可用工具，返回 {tool_name: tool_obj} 字典。

    知识库工具说明：
      - tech_kb      → search_knowledge_base（HelperEngine 使用）
                        未传入时自动从 env TECH_KB_ID 构造
      - ds_course_kb → search_ds_course（InterviewEngine 使用）
                        未传入时自动从 env DS_COURSE_KB_ID 构造
    """
    result: dict[str, Any] = {}

    # ── DB 类工具 ─────────────────────────────────────────────────────────────
    _db_factories = [
        ("get_job_position_info",         create_job_info_tool),
        ("draw_questions_from_bank",      create_quiz_draw_tool),
        ("get_question_bank_stats",       create_quiz_stats_tool),
        ("search_question_bank",          create_quiz_search_tool),
        ("get_student_interview_history", create_history_tool),
        ("get_student_id_by_name",        create_student_lookup_tool),
        ("adjust_question_difficulty",    create_difficulty_tool), #根据评分调整题目难度工具
    ]
    for tool_name, factory in _db_factories:
        if db is None:
            print(f"[Registry] WARN: {tool_name} 跳过：db 未传入")
            continue
        try:
            result[tool_name] = factory(db)
            print(f"[Registry] OK: {tool_name}")
        except Exception as e:
            print(f"[Registry] FAIL: {tool_name} 加载失败：{e}")

    # ── 知识库类工具 ──────────────────────────────────────────────────────────
    # 工厂函数签名：factory(kb: KnowledgeCore = None)
    # kb=None 时工厂内部自动从 env 读取 kb_id 并构造 KnowledgeCore
    _kb_factories = [
        ("search_knowledge_base", create_knowledge_search_tool, tech_kb),
        ("search_ds_course",      create_ds_course_tool,        ds_course_kb),
    ]
    for tool_name, factory, kb_instance in _kb_factories:
        try:
            # kb_instance 为 None 时，工厂自动从 env 构造（若 env 也未配置则抛 ValueError 被捕获）
            result[tool_name] = factory(kb_instance)
            label = kb_instance.label if kb_instance else "auto-env"
            print(f"[Registry] OK: {tool_name} (kb={label!r})")
        except ValueError as e:
            print(f"[Registry] WARN: {tool_name} 跳过：{e}")
        except Exception as e:
            print(f"[Registry] FAIL: {tool_name} 加载失败：{e}")

    # ── 联网搜索类工具 ────────────────────────────────────────────────────────
    _search_factories = [
        ("web_search",       create_web_search_tool),
        ("search_wikipedia", create_wiki_tool),
    ]
    for tool_name, factory in _search_factories:
        try:
            result[tool_name] = factory()
            print(f"[Registry] OK: {tool_name}")
        except Exception as e:
            print(f"[Registry] FAIL: {tool_name} 加载失败：{e}")

    return result


def get_tools_for(
    db=None,
    tech_kb: Optional[KnowledgeCore] = None,
    ds_course_kb: Optional[KnowledgeCore] = None,
    skill_set: SkillSet = ASSISTANT_SKILLS,
) -> list:
    """根据 SkillSet 返回对应的工具列表。"""
    all_tools = build_tools(db=db, tech_kb=tech_kb, ds_course_kb=ds_course_kb)
    selected  = [obj for name, obj in all_tools.items() if name in skill_set]
    print(f"[Registry] 集合「{skill_set.name}」加载 {len(selected)}/{len(skill_set)} 个工具")
    return selected


# ── 便捷函数 ──────────────────────────────────────────────────────────────────

def get_interview_tools(db, ds_course_kb: Optional[KnowledgeCore] = None) -> list:
    """面试引擎专用（COMMON_GROUP + DS_COURSE_GROUP）。ds_course_kb=None 时自动读 env。"""
    return get_tools_for(db=db, ds_course_kb=ds_course_kb, skill_set=INTERVIEW_SKILLS)


def get_assistant_tools(db, tech_kb: Optional[KnowledgeCore] = None) -> list:
    """AI 助手全量工具（含 search_knowledge_base）。tech_kb=None 时自动读 env。"""
    return get_tools_for(db=db, tech_kb=tech_kb, skill_set=ASSISTANT_SKILLS)


def get_readonly_tools(db, tech_kb: Optional[KnowledgeCore] = None) -> list:
    """只读工具集。"""
    return get_tools_for(db=db, tech_kb=tech_kb, skill_set=READONLY_SKILLS)


def get_tools(db, tech_kb=None) -> list:
    """兼容旧接口，等同于 get_assistant_tools。"""
    return get_assistant_tools(db, tech_kb=tech_kb)