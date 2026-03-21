# service/tools/permissions.py
"""
工具能力路由组 + SkillSet 定义

设计思路（类比路由组）：
  ToolGroup  = 一组功能相关的工具，是最小粒度的能力单元
  SkillSet   = 多个 ToolGroup 合并后的完整工具集，交给 Agent 使用
  合并方式   = ToolGroup | ToolGroup | ...  （支持 | 运算符）

新增工具时只需两步：
  1. 在对应 ToolGroup 里加工具名常量
  2. 在 registry._TOOL_FACTORIES 里注册工厂函数
  SkillSet 自动更新，无需手动维护每个集合的 tool_names 列表

当前 ToolGroup 分组：
  COMMON_GROUP   — 所有场景通用：岗位信息、题库抽题、题库统计
  QUIZ_GROUP     — 题库扩展：关键词搜索
  RAG_GROUP      — 知识库检索：技术知识库 + 面试技巧库
  SEARCH_GROUP   — 联网搜索：博查 + Wikipedia
  HISTORY_GROUP  — 历史记录：面试历史 + 学生姓名查找

当前 SkillSet：
  INTERVIEW_SKILLS = COMMON_GROUP
  READONLY_SKILLS  = COMMON_GROUP | QUIZ_GROUP | RAG_GROUP
  ASSISTANT_SKILLS = COMMON_GROUP | QUIZ_GROUP | RAG_GROUP | SEARCH_GROUP | HISTORY_GROUP
  ADMIN_SKILLS     = ASSISTANT_SKILLS（全量，预留扩展）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet


# ═══════════════════════════════════════════════════════════════════
# ToolGroup — 能力路由组
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ToolGroup:
    """
    一组功能相关的工具名称集合，构建 SkillSet 的最小单元。
    支持 | 运算符合并，结果仍为 ToolGroup 可继续合并。
    """
    name:  str
    tools: FrozenSet[str]

    def __or__(self, other: "ToolGroup") -> "ToolGroup":
        return ToolGroup(
            name=f"{self.name}+{other.name}",
            tools=self.tools | other.tools,
        )

    def __contains__(self, tool_name: str) -> bool:
        return tool_name in self.tools

    def __len__(self) -> int:
        return len(self.tools)

    def __repr__(self) -> str:
        return f"ToolGroup({self.name!r}, {sorted(self.tools)})"


# ═══════════════════════════════════════════════════════════════════
# SkillSet — Agent 使用的完整工具集
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class SkillSet:
    """
    Agent 配置使用的工具集合，带名称和描述的 ToolGroup 语义包装。
    向后兼容旧接口：skill_set.tool_names / tool_name in skill_set。
    """
    name:        str
    description: str
    tool_names:  FrozenSet[str]

    @classmethod
    def from_groups(cls, name: str, description: str, *groups: ToolGroup) -> "SkillSet":
        """从一个或多个 ToolGroup 合并构建 SkillSet。"""
        merged: FrozenSet[str] = frozenset()
        for g in groups:
            merged = merged | g.tools
        return cls(name=name, description=description, tool_names=merged)

    def __contains__(self, tool_name: str) -> bool:
        return tool_name in self.tool_names

    def __len__(self) -> int:
        return len(self.tool_names)


# ═══════════════════════════════════════════════════════════════════
# 工具名称常量
# ═══════════════════════════════════════════════════════════════════

# DB 类
TOOL_JOB_INFO       = "get_job_position_info"
TOOL_QUIZ_DRAW      = "draw_questions_from_bank"
TOOL_QUIZ_STATS     = "get_question_bank_stats"
TOOL_QUIZ_SEARCH    = "search_question_bank"
TOOL_HISTORY        = "get_student_interview_history"
TOOL_STUDENT_LOOKUP = "get_student_id_by_name"

# 知识库类
TOOL_RAG_TECH       = "search_knowledge_base"   # 技术知识库，HelperEngine 用
TOOL_RAG_DS_COURSE  = "search_ds_course"         # 数据结构课程库，InterviewEngine 用

# 联网搜索类
TOOL_WEB_SEARCH     = "web_search"
TOOL_WIKIPEDIA      = "search_wikipedia"

TOOL_DIFFICULTY_ADJUST = "adjust_question_difficulty" # 根据评分进行题目难度调整



# ═══════════════════════════════════════════════════════════════════
# ToolGroup 路由组
# ═══════════════════════════════════════════════════════════════════

COMMON_GROUP = ToolGroup(
    name="common",
    tools=frozenset({TOOL_JOB_INFO, TOOL_QUIZ_DRAW, TOOL_QUIZ_STATS,TOOL_DIFFICULTY_ADJUST}),
)

QUIZ_GROUP = ToolGroup(
    name="quiz",
    tools=frozenset({TOOL_QUIZ_SEARCH}),
)

RAG_GROUP = ToolGroup(
    name="rag",
    tools=frozenset({TOOL_RAG_TECH}),
)
# search_knowledge_base — 技术知识库，HelperEngine 专用

DS_COURSE_GROUP = ToolGroup(
    name="ds_course",
    tools=frozenset({TOOL_RAG_DS_COURSE}),
)
# search_ds_course — 数据结构课程库，InterviewEngine 专用

SEARCH_GROUP = ToolGroup(
    name="search",
    tools=frozenset({TOOL_WEB_SEARCH, TOOL_WIKIPEDIA}),
)

HISTORY_GROUP = ToolGroup(
    name="history",
    tools=frozenset({TOOL_HISTORY, TOOL_STUDENT_LOOKUP}),
)


# ═══════════════════════════════════════════════════════════════════
# SkillSet（由 ToolGroup 组合，自动维护）
# ═══════════════════════════════════════════════════════════════════

INTERVIEW_SKILLS = SkillSet.from_groups(
    "interview",
    "面试引擎专用：通用题库能力 + 数据结构课程素材检索",
    COMMON_GROUP, DS_COURSE_GROUP,
)

READONLY_SKILLS = SkillSet.from_groups(
    "readonly",
    "只读查询：题库搜索/统计 + 技术知识库检索（无历史、无联网）",
    COMMON_GROUP, QUIZ_GROUP, RAG_GROUP,
)

ASSISTANT_SKILLS = SkillSet.from_groups(
    "assistant",
    "AI 助手全量：题库 + 技术知识库 + 联网搜索 + 历史记录",
    COMMON_GROUP, QUIZ_GROUP, RAG_GROUP, SEARCH_GROUP, HISTORY_GROUP,
)

ADMIN_SKILLS = SkillSet.from_groups(
    "admin",
    "管理员全量：同 ASSISTANT_SKILLS，预留扩展",
    COMMON_GROUP, QUIZ_GROUP, RAG_GROUP, SEARCH_GROUP, HISTORY_GROUP,
)

ALL_SKILL_SETS: dict[str, SkillSet] = {
    INTERVIEW_SKILLS.name: INTERVIEW_SKILLS,
    READONLY_SKILLS.name:  READONLY_SKILLS,
    ASSISTANT_SKILLS.name: ASSISTANT_SKILLS,
    ADMIN_SKILLS.name:     ADMIN_SKILLS,
}