# service/interview_engine.py
"""
InterviewEngine — 模拟面试引擎

面试官出题/追问走 Agent.stream()（带工具调用能力），
让 LLM 能主动检索课程知识库（search_ds_course）来出更有针对性的题目。

特殊 token 协议（由 submit_answer_stream 产出，UI 层消费）：
  __EVAL__:{json}    — 评分结果
  __IS_FINISHED__    — 本轮是最后一题，AI 给收尾语后 UI 禁用输入框
  __FINISHED__       — 已无未答题目（异常兜底）
  __ERROR__:{msg}    — 会话历史丢失等内部错误
  __SCORE__:{float}  — finish_session_stream 产出的总分
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Generator

from service.agent_core import Agent
from service.evaluator import AnswerEvaluator, EvalResult
# registry 自动从 env DS_COURSE_KB_ID 构造 KnowledgeCore
from service.tools.registry import get_interview_tools
from service.tools.difficulty_tools import get_default_level, get_question_difficulty


# ── 面试会话对话历史 ──────────────────────────────────────────────────────────

class InterviewHistory:
    """每个 session 独立的对话历史，system_prompt 按岗位动态生成。"""

    def __init__(self, system_prompt: str = "", max_turns: int = 30):
        self.system_prompt = system_prompt
        self.max_turns     = max_turns
        self.messages: list[dict] = []

    def add_user(self, content: str):
        self.messages.append({"role": "user", "content": content})
        self._trim()

    def add_assistant(self, content: str):
        self.messages.append({"role": "assistant", "content": content or ""})
        self._trim()

    def _trim(self):
        user_idx = [i for i, m in enumerate(self.messages) if m["role"] == "user"]
        if len(user_idx) > self.max_turns:
            self.messages = self.messages[user_idx[-self.max_turns]:]

    def get(self) -> list[dict]:
        result = []
        if self.system_prompt:
            result.append({"role": "system", "content": self.system_prompt})
        result.extend(self.messages)
        return result

    def clear(self):
        self.messages.clear()


# ── System Prompts ────────────────────────────────────────────────────────────

_INTERVIEWER_SYSTEM = """你是"{job_name}"岗位的技术面试官，风格专业但不死板，像真实面试一样自然对话。

## 技术栈
{tech_stack}

## 可用工具
- draw_questions_from_bank：从题库随机抽题。每道新题前必须调用，以抽到的题目为提问基础。
- search_ds_course：检索课程场景素材。抽题后可调用，把相关场景自然融入提问，不要原文复制检索结果。
- get_job_position_info：查询岗位技术栈详情。需要确认考察范围时调用。
- get_question_bank_stats：查询题库统计。需要了解题目分布时调用。

## 出题策略
- 从基础概念切入，根据候选人回答质量动态调整难度
- 回答扎实 → 追问底层原理或边界场景（"那如果...会怎样？"）
- 回答模糊 → 换个角度追问，帮助候选人打开思路（"你提到了X，能展开说说吗？"）
- 回答有误 → 不直接否定，先问"你确定吗？"或"还有其他可能性吗？"
- 每次只问一个问题，不要连续抛出多个问题

## 工具使用
- 先通过sql_tools能力群抽取难度题，后根据抽取的题目进行追问
- 调用 search_ds_course 检索课程相关场景，让题目更贴近实际课程内容
- 检索到场景后，把场景背景自然融入题目，不要直接把检索结果复制给候选人

## 对话风格
- 开场简短寒暄，然后直接进入技术问题
- 适时给出肯定（"不错"、"这个理解到位"），但不要过度称赞
- 追问时语气自然，像真人面试官一样，而不是机械地"好的，下一题"
- 回答完全错误时可以给一个小提示，引导候选人思考

## 硬约束
- 每次回复只包含一个问题，等候选人回答后再追问或换题
- 不要在候选人回答前剧透答案
- 不要输出评分、总结或"你的回答得X分"之类的内容（评分由系统处理）
"""

_REPORT_PROMPT = """根据以下面试记录，生成一份有温度的面试评估报告。

岗位：{job_name}
候选人：{student_name}
面试题数：{turn_count} 题
各题得分：
{scores_summary}

要求：
- 语气像导师给学生的反馈，而不是冷冰冰的评分表
- 指出真实存在的问题，不要虚假鼓励
- 建议要具体可操作，不要泛泛而谈

输出格式（直接输出，不加多余标记）：

【综合评价】
（2-3句整体印象，提炼最突出的特点）

【技术能力】
（哪些掌握扎实，哪些存在明显漏洞，举具体题目说明）

【表现亮点】
（2-3个真实亮点，可以引用候选人的回答）

【需要加强】
（2-3个具体薄弱点，说明为什么重要）

【下一步建议】
（具体的学习路径，推荐方向或练习方式）
"""


# ── InterviewEngine ───────────────────────────────────────────────────────────

class InterviewEngine:
    """
    模拟面试引擎。

    面试官出题/追问走 Agent.stream()，LLM 可主动调用工具（如 search_ds_course）
    检索课程素材，出更有针对性的题目。

    与 HelperEngine 的关键区别：
      - _histories 字典：每个 session_id 对应独立的 InterviewHistory
      - Agent.conversation 不直接使用；面试对话历史由 InterviewHistory 管理，
        每次调用前注入 Agent，调用后把结果同步回 InterviewHistory
      - AnswerEvaluator：独立评分器，评分结果通过特殊 token 传给 UI

    使用示例：
        engine = InterviewEngine(db=db)
        panel  = InterviewPanel(db, engine)
    """

    MAX_TURNS = 8

    def __init__(
        self,
        db,
        model: str = "qwen3-omni-flash",
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ):
        self.db        = db
        self.evaluator = AnswerEvaluator()
        # 每一轮的提问级别
        self._turn_levels = get_default_level()  # 获取默认难度[中等]

        self._agent = Agent(
            db=db,
            system_prompt="",
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        self._agent.register_tools(get_interview_tools(db))

        # session_id → InterviewHistory
        self._histories: dict[int, InterviewHistory] = {}


    # ── 内部：借用 Agent 做带工具的流式调用 ──────────────────────────────────
    # 每次调用前：把 InterviewHistory 的消息列表同步进 Agent.conversation
    # 每次调用后：把 Agent 产出的最终文本同步回 InterviewHistory
    # 这样 Agent 的 tool_calling 循环可以正常运作，同时 session 状态由 InterviewHistory 管理

    def _agent_stream(
        self,
        history: InterviewHistory,
        user_msg: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Generator[str, None, None]:
        """
        把 history 注入 Agent，流式生成回复，过滤掉工具调用提示行。
        调用方负责在流结束后调用 history.add_assistant(full_text)。
        """
        # 把当前 InterviewHistory 同步进 Agent.conversation
        self._agent.conversation.clear()
        self._agent.conversation.update_system_prompt(history.system_prompt)
        for msg in history.messages:
            if msg["role"] == "user":
                self._agent.conversation.add_user(msg["content"])
            elif msg["role"] == "assistant":
                self._agent.conversation.add_assistant(msg["content"])

        # 临时覆盖温度/token（如有）
        orig_temp   = self._agent._temperature
        orig_tokens = self._agent._max_tokens
        if temperature is not None:
            self._agent._temperature = temperature
        if max_tokens is not None:
            self._agent._max_tokens = max_tokens

        try:
            for chunk in self._agent.stream(user_msg):
                # 过滤掉 Agent 输出的工具调用提示行，不展示给候选人
                if chunk.startswith("\n\n⚙️ **正在调用**"):
                    continue
                yield chunk
        finally:
            self._agent._temperature = orig_temp
            self._agent._max_tokens  = orig_tokens

    # ── 开始面试 ──────────────────────────────────────────────────────────────

    def start_session(self, student_id: int, job_position_id: int) -> int:
        now = datetime.now().isoformat()
        cur = self.db.execute(
            "INSERT INTO interview_session "
            "(student_id, job_position_id, status, started_at) VALUES (?,?,?,?)",
            (student_id, job_position_id, "ongoing", now),
        )
        session_id = cur.lastrowid

        job            = self._get_job_by_id(session_id)
        tech_stack_str = "、".join(json.loads(job["tech_stack"]))
        system_content = _INTERVIEWER_SYSTEM.format(
            job_name=job["name"], tech_stack=tech_stack_str
        )

        history = InterviewHistory(system_prompt=system_content)
        self._histories[session_id] = history
        return session_id

    # ── 第一问 ────────────────────────────────────────────────────────────────

    def get_first_question_stream(self, session_id: int) -> Generator[str, None, None]:
        history = self._histories.get(session_id)
        if history is None:
            yield " 会话不存在，请重新开始面试。"
            return

        parts: list[str] = []
        for chunk in self._agent_stream(history, "你好，我准备好了，请开始面试。"):
            parts.append(chunk)
            yield chunk

        full_text = "".join(parts)
        history.add_user("你好，我准备好了，请开始面试。")
        history.add_assistant(full_text)
        self._save_turn(session_id, question_text=full_text, student_answer="")

    def confirm_first_question(self, session_id: int, full_text: str):
        """UI 层用流式拼好全文后调用，把第一问落库（流式版已内置，此方法供兼容保留）。"""
        pass

    # ── 提交回答 ──────────────────────────────────────────────────────────────

    def submit_answer_stream(
        self, session_id: int, answer: str
    ) -> Generator[str, None, None]:
        turn = self._get_latest_unanswered_turn(session_id)
        if not turn:
            yield "__FINISHED__\n"
            return

        turn_id, question_text = turn
        job = self._get_job_by_id(session_id)

        # 同步评分，结果通过特殊 token 传给 UI 层
        eval_result: EvalResult = self.evaluator.evaluate(
            question=question_text,
            answer=answer,
            job_name=job["name"],
        )

        self.db.execute(
            "UPDATE interview_turn SET student_answer=?, scores=? WHERE id=?",
            (answer, json.dumps(eval_result.to_dict()), turn_id),
        )
        yield f"__EVAL__:{json.dumps(eval_result.to_dict(), ensure_ascii=False)}\n"

        finished_count = self.db.fetchone(
            "SELECT COUNT(*) FROM interview_turn "
            "WHERE session_id=? AND student_answer!=''",
            (session_id,),
        )[0]
        is_finished = finished_count >= self.MAX_TURNS

        history = self._histories.get(session_id)
        if history is None:
            yield "__ERROR__:会话历史丢失\n"
            return

        if is_finished:
            yield "__IS_FINISHED__\n"

        cur_level = self._turn_levels
        new_level = self._get_next_level(eval_result.overall_score,cur_level)
        self._set_next_level(new_level)

        print(f"{answer}\n\n【面试官注意】当前题目难度为：{self._turn_levels}，下一题请用此难度抽题。")
        # 面试官根据候选人回答做出追问或换题（带工具调用）
        followup_prompt = (
            f"{answer}\n\n【面试官注意】当前题目难度为：{self._turn_levels}，下一题请用此难度抽题。"
            if not is_finished
            else f"{answer}\n\n（面试轮数已到，请自然地结束面试）"
        )

        parts: list[str] = []
        for chunk in self._agent_stream(history, followup_prompt):
            parts.append(chunk)
            yield chunk

        ai_full_text = "".join(parts)
        history.add_user(answer)
        history.add_assistant(ai_full_text)
        if not is_finished:
            self._save_turn(session_id, question_text=ai_full_text, student_answer="")

    def confirm_answer(self, session_id: int, ai_full_text: str, is_finished: bool):
        """流式版已内置历史同步和落库，此方法供兼容保留。"""
        pass

    # ── 结束面试 ──────────────────────────────────────────────────────────────

    def finish_session_stream(self, session_id: int) -> Generator[str, None, None]:
        turns = self.db.fetchall(
            "SELECT question_text, student_answer, scores FROM interview_turn "
            "WHERE session_id=? AND student_answer!='' ORDER BY turn_index",
            (session_id,),
        )
        if not turns:
            yield "__SCORE__:0\n"
            yield "本次面试未完成任何题目，无法生成报告。"
            return

        all_scores, lines = [], []
        for i, (q, a, sc_json) in enumerate(turns, 1):
            if sc_json:
                sc = json.loads(sc_json)
                ov = sc.get("overall", 0)
                all_scores.append(ov)
                lines.append(
                    f"第{i}题（{q[:20]}…）: 综合 {ov}/10  "
                    f"技术{sc.get('tech',0)} 逻辑{sc.get('logic',0)} "
                    f"深度{sc.get('depth',0)} 表达{sc.get('clarity',0)}"
                )

        overall_score = round(sum(all_scores) / len(all_scores), 2) if all_scores else 0.0
        yield f"__SCORE__:{overall_score}\n"

        job     = self._get_job_by_id(session_id)
        student = self._get_student(session_id)
        prompt  = _REPORT_PROMPT.format(
            job_name=job["name"],
            student_name=student["name"],
            turn_count=len(turns),
            scores_summary="\n".join(lines),
        )

        # 报告生成不需要工具，直接用 _client 做纯文本流式
        try:
            stream = self._agent._client.chat.completions.create(
                model=self._agent._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=1500,
                stream=True,
                stream_options={"include_usage": False},
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            yield f"\n\n[报告生成失败: {e}]\n"

    def confirm_finish(self, session_id: int, overall_score: float, report_text: str):
        self._close_session(session_id, overall_score=overall_score, report=report_text)

    # ── 运行时调整 ────────────────────────────────────────────────────────────

    def set_model(self, model: str, temperature: float | None = None) -> "InterviewEngine":
        self._agent.set_model(model, temperature)
        return self

    @property
    def agent(self) -> Agent:
        return self._agent

    # ── 内部辅助 ──────────────────────────────────────────────────────────────

    def _save_turn(self, session_id: int, question_text: str, student_answer: str):
        idx = self.db.fetchone(
            "SELECT COALESCE(MAX(turn_index)+1, 0) FROM interview_turn WHERE session_id=?",
            (session_id,),
        )[0]
        self.db.execute(
            "INSERT INTO interview_turn "
            "(session_id, turn_index, question_text, student_answer, created_at) "
            "VALUES (?,?,?,?,?)",
            (session_id, idx, question_text, student_answer, datetime.now().isoformat()),
        )

    def _get_latest_unanswered_turn(self, session_id: int):
        return self.db.fetchone(
            "SELECT id, question_text FROM interview_turn "
            "WHERE session_id=? AND student_answer='' "
            "ORDER BY turn_index DESC LIMIT 1",
            (session_id,),
        )

    def _close_session(self, session_id: int, overall_score: float, report: str):
        self.db.execute(
            "UPDATE interview_session "
            "SET status='finished', finished_at=?, overall_score=?, report=? WHERE id=?",
            (datetime.now().isoformat(), overall_score, report, session_id),
        )
        self._histories.pop(session_id, None)

    def _get_job_by_id(self, session_id: int) -> dict:
        row = self.db.fetchone(
            "SELECT jp.id, jp.name, jp.tech_stack FROM interview_session s "
            "JOIN job_position jp ON s.job_position_id=jp.id WHERE s.id=?",
            (session_id,),
        )
        return {"id": row[0], "name": row[1], "tech_stack": row[2]}

    def _get_student(self, session_id: int) -> dict:
        row = self.db.fetchone(
            "SELECT st.id, st.name FROM interview_session s "
            "JOIN student st ON s.student_id=st.id WHERE s.id=?",
            (session_id,),
        )
        return {"id": row[0], "name": row[1]}

    def get_session_turns(self, session_id: int) -> list:
        return self.db.fetchall(
            "SELECT turn_index, question_text, student_answer, scores "
            "FROM interview_turn WHERE session_id=? ORDER BY turn_index",
            (session_id,),
        )

    def _get_next_level(self, overall: float,curlevle: str) -> str:
        """获取下一轮的题目难度，调用函数"""
        levle = get_question_difficulty(overall,curlevle)
        return levle

    def _set_next_level(self, level: str):
        """设置下一轮的题目难度"""
        self._turn_levels = level
