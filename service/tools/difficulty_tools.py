# service/tools/difficulty_tools.py
"""
难度调整工具 - 根据评分动态决定下一题难度
"""
from langchain_core.tools import tool
from pydantic import BaseModel, Field

DefaultLevel = "中级"

def get_default_level():
    """获取默认的题目难度"""
    return DefaultLevel

# 手动调用
def get_question_difficulty(
            overall: float,
            current_level: str = "中级"
    ) -> str:
        """
        根据本轮答题表现，智能调整下一题的难度。
        规则：
        - 综合分 >= 8：提升难度（当前初级→中级，当前中级→高级）
        - 综合分 6-8：保持当前难度
        - 综合分 < 6：降低难度（当前高级→中级，当前中级→初级）
        """

        LEVEL_ORDER = ["初级", "中级", "高级"]
        LEVEL_INDEX = {level: idx for idx, level in enumerate(LEVEL_ORDER)}
        # 对于未知的 current_level，回退到默认的“中级”难度
        current_idx = LEVEL_INDEX.get(current_level, LEVEL_INDEX["中级"])

        if overall >= 8:
            # 提升难度
            next_idx = min(current_idx + 1, 2)
        elif overall >= 6:
            # 保持难度
            next_idx = current_idx
        else:
            # 降低难度
            next_idx = max(current_idx - 1, 0)

        next_level = LEVEL_ORDER[next_idx]

        return next_level


# AI调用工具
class DifficultyAdjustInput(BaseModel):
    """根据本轮评分计算下一轮题目难度"""
    overall: int = Field(...,description="综合分")
    current_level: str = Field(default=DefaultLevel, description="当前题目难度：初级/中级/高级")

def create_difficulty_tool():
    """工厂函数，返回难度调整工具"""

    @tool(args_schema=DifficultyAdjustInput)
    def adjust_question_difficulty(
            overall: int,
            current_level: str = "中级"
    ) -> str:
        """
        根据本轮答题表现，智能调整下一题的难度。
        规则：
        - 综合分 >= 8：提升难度（当前初级→中级，当前中级→高级）
        - 综合分 6-8：保持当前难度
        - 综合分 < 6：降低难度（当前高级→中级，当前中级→初级）
        """

        LEVEL_ORDER = ["初级", "中级", "高级"]
        current_idx = LEVEL_ORDER.index(current_level)

        if overall >= 8:
            # 提升难度
            next_idx = min(current_idx + 1, 2)
        elif overall >= 6:
            # 保持难度
            next_idx = current_idx
        else:
            # 降低难度
            next_idx = max(current_idx - 1, 0)

        next_level = LEVEL_ORDER[next_idx]

        return next_level

    return adjust_question_difficulty

