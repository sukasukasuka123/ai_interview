# service/interview_engine.py
"""
面试引擎 — 流式重构版（仿照 agent_core.py 架构）
管理一次完整的 AI 模拟面试会话：出题、追问、评分、生成报告。
使用原生 OpenAI SDK 真实流式输出，第一个 token 即时响应。
"""
import json
import os
from datetime import datetime
from typing import Generator, Optional

from openai import OpenAI

from service.evaluator import AnswerEvaluator, EvalResult
from service.knowledge_store import KnowledgeStore


# ── 对话历史管理（与 agent_core 同构）────────────────────────────────────────

class InterviewHistory:
    """面试会话的对话历史管理，每个 session_id 独立维护"""

    def __init__(self, system_prompt: str = "", max_turns: int = 30):
        self.system_prompt = system_prompt
        self.max_turns = max_turns
        self.messages: list[dict] = []

    def add_user(self, content: str):
        self.messages.append({"role": "user", "content": content})
        self._trim()

    def add_assistant(self, content: str):
        self.messages.append({"role": "assistant", "content": content or ""})
        self._trim()

    def _trim(self):
        user_indices = [i for i, m in enumerate(self.messages) if m["role"] == "user"]
        if len(user_indices) <= self.max_turns:
            return
        cutoff = user_indices[-self.max_turns]
        self.messages = self.messages[cutoff:]

    def get(self) -> list[dict]:
        result = []
        if self.system_prompt:
            result.append({"role": "system", "content": self.system_prompt})
        result.extend(self.messages)
        return result

    def clear(self):
        self.messages.clear()


# ── 系统提示词 ────────────────────────────────────────────────────────────────

_INTERVIEWER_SYSTEM = """你是一位专业、严谨的技术面试官，正在对"{job_name}"岗位的候选人进行模拟面试。

## 你的工作流程
1. 根据岗位技术栈，由浅入深地提问
2. 认真听取候选人的回答
3. 根据回答质量决定：追问细节 OR 切换下一个知识点
4. 面试结束时给出整体评价

## 出题原则
- 覆盖岗位核心技术栈：{tech_stack}
- 难度循序渐进：先考察基础概念，再深入原理和实践
- 每次只问一个问题，等候选人回答后再追问或换题
- 如果候选人回答正确且完整，追问更深层原理（如"能说说底层实现吗？"）
- 如果候选人回答有误，委婉指出并给出提示

## 语气要求
- 专业但不刻板，模拟真实面试氛围
- 候选人表现好时给予鼓励
- 回答简洁，不要做过多解释，保持面试节奏

## 重要约束
- 每次回复只包含一个问题或追问，不得一次问多个
- 不要在候选人回答前就告知答案
- 不要输出任何与面试无关的内容
"""

_REPORT_PROMPT = """请根据以下面试记录，生成一份结构化的面试评估报告。

岗位：{job_name}
候选人：{student_name}
面试题数：{turn_count} 题
各题得分：{scores_summary}

请用中文输出以下格式的报告（直接输出内容，不要 markdown 标题外的多余格式）：

【综合评价】
（2-3句话总体评价候选人表现）

【技术能力】
（评价技术知识掌握情况，指出强项和薄弱点）

【表现亮点】
（列出2-3个具体亮点）

【待提升项】
（列出2-3个需要改进的方向）

【学习建议】
（给出具体的学习资源方向或练习建议）
"""


# ── 面试引擎主类（真实流式架构）──────────────────────────────────────────────

class InterviewEngine:
    """
    面试引擎核心，使用原生 OpenAI SDK 实现真实流式输出。
    - get_first_question_stream / submit_answer_stream / finish_session_stream
      均返回 Generator[str, None, None]，供 UI 层逐 token 消费。
    - 同步版 get_first_question / submit_answer / finish_session 作为兼容接口保留。
    """

    MAX_TURNS = 8

    def __init__(
        self,
        db,
        knowledge_store: KnowledgeStore,
        model: str = "qwen3-omni-flash",
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ):
        self.db = db
        self.ks = knowledge_store
        self.evaluator = AnswerEvaluator()

        self._client = OpenAI(
            api_key=os.getenv("DASHSCOPE_API_KEY", ""),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens

        # session_id → InterviewHistory
        self._histories: dict[int, InterviewHistory] = {}

    # ── 内部：原始流式请求 ────────────────────────────────────────────────────

    def _stream_raw(
        self,
        messages: list[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Generator[str, None, None]:
        """
        向模型发起真实流式请求，逐 token yield 文本内容。
        与 agent_core.Agent.stream() 的文本段逻辑完全对齐。
        """
        try:
            response_stream = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=temperature if temperature is not None else self._temperature,
                max_tokens=max_tokens if max_tokens is not None else self._max_tokens,
                stream=True,
                stream_options={"include_usage": False},
            )
        except Exception as e:
            yield f"\n\n[⚠️ 调用失败: {e}]\n"
            return

        for chunk in response_stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content

    def _collect_stream(self, generator: Generator[str, None, None]) -> str:
        """收集流式输出为完整字符串（供同步接口使用）"""
        return "".join(generator)

    # ── 开始面试 ──────────────────────────────────────────────────────────────

    def start_session(self, student_id: int, job_position_id: int) -> int:
        now = datetime.now().isoformat()
        cur = self.db.execute(
            "INSERT INTO interview_session (student_id, job_position_id, status, started_at) VALUES (?,?,?,?)",
            (student_id, job_position_id, "ongoing", now),
        )
        session_id = cur.lastrowid

        job = self._get_job_by_id(session_id)
        tech_stack_str = "、".join(json.loads(job["tech_stack"]))
        system_content = _INTERVIEWER_SYSTEM.format(
            job_name=job["name"], tech_stack=tech_stack_str
        )

        history = InterviewHistory(system_prompt=system_content)
        history.add_user("你好，我准备好了，请开始面试。")
        self._histories[session_id] = history
        return session_id

    # ── 第一问：流式版 ────────────────────────────────────────────────────────

    def get_first_question_stream(self, session_id: int) -> Generator[str, None, None]:
        """
        流式获取第一个面试问题。
        UI 层消费完毕后须调用 confirm_first_question(session_id, full_text) 保存历史。
        """
        history = self._histories.get(session_id)
        if history is None:
            yield "❌ 会话不存在，请重新开始面试。"
            return
        yield from self._stream_raw(history.get())

    def confirm_first_question(self, session_id: int, full_text: str):
        """UI 层收集完流后调用，将 AI 回复写入历史和数据库"""
        history = self._histories.get(session_id)
        if history is None:
            return
        history.add_assistant(full_text)
        self._save_turn(session_id, question_text=full_text, student_answer="")

    # ── 第一问：同步兼容版 ────────────────────────────────────────────────────

    def get_first_question(self, session_id: int) -> str:
        full = self._collect_stream(self.get_first_question_stream(session_id))
        self.confirm_first_question(session_id, full)
        return full

    # ── 提交回答：流式版 ──────────────────────────────────────────────────────

    def submit_answer_stream(
        self, session_id: int, answer: str
    ) -> Generator[str, None, None]:
        """
        流式提交回答：
          1. 评估答案（同步，耗时较短）
          2. 流式输出 AI 回复
          3. 完整内容收集后由 confirm_answer() 写库
        先 yield 特殊标记行传递 eval 数据，再 yield AI 回复 token。

        协议：
          首行 __EVAL__:{json}\\n  → UI 解析评分卡
          后续行               → AI 正常回复 token
        """
        turn = self._get_latest_unanswered_turn(session_id)
        if not turn:
            yield "__FINISHED__\n"
            return

        turn_id, question_text = turn
        job = self._get_job_by_id(session_id)
        context = (
            self.ks.retrieve_as_context(question_text, job_position_id=job["id"])
            if hasattr(self.ks, "retrieve_as_context") else ""
        )

        # ── 同步评估 ──────────────────────────────────────────────────────────
        eval_result: EvalResult = self.evaluator.evaluate(
            question=question_text,
            answer=answer,
            job_name=job["name"],
            context=context,
        )
        self.db.execute(
            "UPDATE interview_turn SET student_answer=?, scores=? WHERE id=?",
            (answer, json.dumps(eval_result.to_dict()), turn_id),
        )

        # 传递评分数据给 UI
        yield f"__EVAL__:{json.dumps(eval_result.to_dict(), ensure_ascii=False)}\n"

        # ── 判断是否结束 ──────────────────────────────────────────────────────
        finished_count = self.db.fetchone(
            "SELECT COUNT(*) FROM interview_turn WHERE session_id=? AND student_answer!=''",
            (session_id,),
        )[0]
        is_finished = finished_count >= self.MAX_TURNS

        # ── 更新历史并发起流式请求 ────────────────────────────────────────────
        history = self._histories.get(session_id)
        if history is None:
            yield "__ERROR__:会话历史丢失\n"
            return

        history.add_user(answer)
        if is_finished:
            history.add_user("（面试轮数已到，请给候选人一个简短收尾语）")

        # 传递 is_finished 标记
        if is_finished:
            yield "__IS_FINISHED__\n"

        # 流式输出 AI 回复
        yield from self._stream_raw(history.get())

    def confirm_answer(self, session_id: int, ai_full_text: str, is_finished: bool):
        """UI 层收集完流后调用，将 AI 回复写入历史，并决定是否新建下一轮"""
        history = self._histories.get(session_id)
        if history is None:
            return
        history.add_assistant(ai_full_text)
        if not is_finished:
            self._save_turn(session_id, question_text=ai_full_text, student_answer="")

    # ── 提交回答：同步兼容版 ──────────────────────────────────────────────────

    def submit_answer(self, session_id: int, answer: str) -> dict:
        eval_result = None
        ai_parts: list[str] = []
        is_finished = False

        for token in self.submit_answer_stream(session_id, answer):
            if token.startswith("__EVAL__:"):
                data = json.loads(token[len("__EVAL__:"):].strip())
                # 重建 EvalResult（简单 dict 包装）
                eval_result = _DictEvalResult(data)
            elif token == "__IS_FINISHED__\n":
                is_finished = True
            elif token == "__FINISHED__\n":
                return {"ai_reply": "面试已结束，请点击「结束面试」查看报告。", "is_finished": True}
            elif token.startswith("__ERROR__:"):
                raise RuntimeError(token[len("__ERROR__:"):].strip())
            else:
                ai_parts.append(token)

        ai_reply = "".join(ai_parts)
        self.confirm_answer(session_id, ai_reply, is_finished)
        return {"eval": eval_result, "ai_reply": ai_reply, "is_finished": is_finished}

    # ── 结束面试：流式版 ──────────────────────────────────────────────────────

    def finish_session_stream(self, session_id: int) -> Generator[str, None, None]:
        """
        流式生成面试报告。
        完整内容收集后由 confirm_finish() 写库。

        协议：
          首行 __SCORE__:{overall_score}\\n → UI 显示总分
          后续行                            → 报告正文 token
        """
        turns = self.db.fetchall(
            "SELECT question_text, student_answer, scores FROM interview_turn "
            "WHERE session_id=? AND student_answer!='' ORDER BY turn_index",
            (session_id,),
        )

        if not turns:
            yield "__SCORE__:0\n"
            yield "本次面试未完成任何题目，无法生成报告。"
            return

        all_scores = []
        scores_summary_lines = []
        for i, (q, a, scores_json) in enumerate(turns, 1):
            if scores_json:
                sc = json.loads(scores_json)
                overall = sc.get("overall", 0)
                all_scores.append(overall)
                scores_summary_lines.append(
                    f"第{i}题（{q[:20]}…）: 综合 {overall}/10  "
                    f"技术{sc.get('tech', 0)} 逻辑{sc.get('logic', 0)} "
                    f"深度{sc.get('depth', 0)} 表达{sc.get('clarity', 0)}"
                )

        overall_score = round(sum(all_scores) / len(all_scores), 2) if all_scores else 0.0
        yield f"__SCORE__:{overall_score}\n"

        job = self._get_job_by_id(session_id)
        student = self._get_student(session_id)
        prompt = _REPORT_PROMPT.format(
            job_name=job["name"],
            student_name=student["name"],
            turn_count=len(turns),
            scores_summary="\n".join(scores_summary_lines),
        )

        yield from self._stream_raw(
            [{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=1500,
        )

    def confirm_finish(self, session_id: int, overall_score: float, report_text: str):
        """UI 层收集完流后调用，关闭会话并写库"""
        self._close_session(session_id, overall_score=overall_score, report=report_text)

    # ── 结束面试：同步兼容版 ──────────────────────────────────────────────────

    def finish_session(self, session_id: int) -> str:
        overall_score = 0.0
        report_parts: list[str] = []

        for token in self.finish_session_stream(session_id):
            if token.startswith("__SCORE__:"):
                overall_score = float(token[len("__SCORE__:"):].strip())
            else:
                report_parts.append(token)

        report_text = "".join(report_parts)
        self.confirm_finish(session_id, overall_score, report_text)
        return report_text

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
            "WHERE session_id=? AND student_answer='' ORDER BY turn_index DESC LIMIT 1",
            (session_id,),
        )

    def _close_session(self, session_id: int, overall_score: float, report: str):
        self.db.execute(
            "UPDATE interview_session "
            "SET status='finished', finished_at=?, overall_score=?, report=? "
            "WHERE id=?",
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


# ── 轻量 EvalResult 包装（同步兼容用）────────────────────────────────────────

class _DictEvalResult:
    """将 dict 包装为 EvalResult 鸭子类型，供同步兼容接口使用"""

    def __init__(self, data: dict):
        self._data = data
        self.overall = data.get("overall", 0)
        self.tech = data.get("tech", 0)
        self.logic = data.get("logic", 0)
        self.depth = data.get("depth", 0)
        self.clarity = data.get("clarity", 0)
        self.comment = data.get("comment", "")

    def to_dict(self) -> dict:
        return self._data