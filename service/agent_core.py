# service/agent_core.py
"""
Agent 核心框架（原生 OpenAI SDK 真实流式输出）
使用 openai.OpenAI 客户端 + stream=True，第一个 token 即时响应。
"""
import json
import os
from typing import Any, Dict, Generator, List, Optional

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


# ── 对话历史管理 ──────────────────────────────────────────────────────────────

class ConversationHistory:
    def __init__(self, system_prompt: str = "", max_turns: int = 30):
        self.system_prompt = system_prompt
        self.max_turns = max_turns
        self.messages: List[dict] = []

    def add_user(self, content: str):
        self.messages.append({"role": "user", "content": content})
        self._trim()

    def add_assistant(self, content: str, tool_calls: list | None = None):
        msg: dict = {"role": "assistant", "content": content or ""}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self.messages.append(msg)
        self._trim()

    def add_tool_result(self, tool_call_id: str, content: str):
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        })
        self._trim()

    def _trim(self):
        user_indices = [i for i, m in enumerate(self.messages) if m["role"] == "user"]
        if len(user_indices) <= self.max_turns:
            return
        cutoff = user_indices[-self.max_turns]
        self.messages = self.messages[cutoff:]

    def get(self) -> List[dict]:
        result = []
        if self.system_prompt:
            result.append({"role": "system", "content": self.system_prompt})
        result.extend(self.messages)
        return result

    def clear(self):
        self.messages.clear()


# ── LangChain 工具 → OpenAI tools 格式转换 ───────────────────────────────────

def _lc_tool_to_openai(tool_obj) -> dict:
    """把 LangChain @tool 对象转换为 OpenAI tools 格式"""
    schema = tool_obj.args_schema.schema() if tool_obj.args_schema else {"properties": {}, "type": "object"}
    return {
        "type": "function",
        "function": {
            "name": tool_obj.name,
            "description": tool_obj.description or "",
            "parameters": {
                "type": "object",
                "properties": schema.get("properties", {}),
                "required": schema.get("required", []),
            },
        },
    }


# ── Agent 主类 ────────────────────────────────────────────────────────────────

class Agent:
    """
    Agent 核心，使用原生 OpenAI SDK 实现真实流式输出。
    工具调用（tool_use）阶段整体收取后执行，纯文本阶段逐 token yield。
    """

    def __init__(
        self,
        db,
        system_prompt: Optional[str] = None,
        model: str = "qwen-plus",
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ):
        self.db = db
        self.system_prompt = system_prompt or ""
        self.conversation = ConversationHistory(system_prompt=self.system_prompt)
        self._tools_lc: Dict[str, Any] = {}           # name → LangChain tool obj
        self._tools_openai: List[dict] = []           # OpenAI tools schema

        self._client = OpenAI(
            api_key=os.getenv("DASHSCOPE_API_KEY", ""),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens

    # ── 工具注册 ──────────────────────────────────────────────────────────────

    def register_tool(self, tool_obj):
        self._tools_lc[tool_obj.name] = tool_obj
        self._tools_openai = [_lc_tool_to_openai(t) for t in self._tools_lc.values()]

    def register_tools(self, tools: list):
        for t in tools:
            self.register_tool(t)

    # ── 公共接口 ──────────────────────────────────────────────────────────────

    def chat(self, user_input: str) -> str:
        """同步完整输出（兼容旧调用）"""
        return "".join(self.stream(user_input))

    def stream(self, user_input: str) -> Generator[str, None, None]:
        """
        真实流式生成器。
        - 有工具调用 → 整体收取，执行工具，yield 提示，继续下一轮
        - 无工具调用 → 逐 token yield，第一个字符即时出现
        """
        self.conversation.add_user(user_input)

        for _round in range(12):  # 最多 12 轮 agentic loop
            messages = self.conversation.get()

            # ── 发起流式请求 ──────────────────────────────────────────────────
            stream_kwargs: dict = dict(
                model=self._model,
                messages=messages,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                stream=True,
                stream_options={"include_usage": False},
            )
            if self._tools_openai:
                stream_kwargs["tools"] = self._tools_openai
                stream_kwargs["tool_choice"] = "auto"

            response_stream = self._client.chat.completions.create(**stream_kwargs)

            # ── 流式收取 ─────────────────────────────────────────────────────
            content_parts: list[str] = []
            tool_calls_map: dict[int, dict] = {}   # index → {id, name, args}
            finish_reason = None

            for chunk in response_stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                finish_reason = choice.finish_reason or finish_reason

                # 文本内容
                if delta.content:
                    content_parts.append(delta.content)
                    # 仅当没有工具调用时才实时 yield（流式体验）
                    if not tool_calls_map:
                        yield delta.content

                # 工具调用 delta
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_map:
                            tool_calls_map[idx] = {"id": tc.id or "", "name": "", "args": ""}
                        existing = tool_calls_map[idx]
                        if tc.id:
                            existing["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                existing["name"] += tc.function.name
                            if tc.function.arguments:
                                existing["args"] += tc.function.arguments

            full_content = "".join(content_parts)

            # ── 判断结果 ──────────────────────────────────────────────────────
            if tool_calls_map:
                # 有工具调用：若之前已 yield 了文本部分，补回 markdown 的 newline
                if full_content and not tool_calls_map:
                    pass  # 已 yield

                # 构建 OpenAI tool_calls 列表（供历史记录）
                openai_tool_calls = []
                for idx in sorted(tool_calls_map.keys()):
                    tc = tool_calls_map[idx]
                    openai_tool_calls.append({
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["args"],
                        },
                    })

                self.conversation.add_assistant(full_content, tool_calls=openai_tool_calls)

                # 执行每个工具
                for tc_info in openai_tool_calls:
                    tool_name = tc_info["function"]["name"]
                    yield f"\n\n⚙️ **正在调用** `{tool_name}`...\n\n"
                    result = self._execute_tool(tool_name, tc_info["function"]["arguments"])
                    self.conversation.add_tool_result(tc_info["id"], result)

                # 继续下一轮让 LLM 基于工具结果回答

            else:
                # 纯文本回答：内容已全部 yield，记录历史后退出
                self.conversation.add_assistant(full_content)
                return

        yield "\n\n[⚠️ 已达到最大工具调用轮数]"

    # ── 工具执行 ──────────────────────────────────────────────────────────────

    def _execute_tool(self, tool_name: str, args_str: str) -> str:
        tool_obj = self._tools_lc.get(tool_name)
        if not tool_obj:
            return f"❌ 未找到工具: {tool_name}"
        try:
            args = json.loads(args_str) if args_str else {}
            result = tool_obj.invoke(args)
            return str(result)
        except Exception as e:
            return f"❌ 工具执行失败 ({tool_name}): {e}"

    def clear_conversation(self):
        self.conversation.clear()

    def get_registered_tools(self) -> List[str]:
        return list(self._tools_lc.keys())