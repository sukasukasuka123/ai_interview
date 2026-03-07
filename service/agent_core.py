# service/agent_core.py
"""
Agent 核心框架（支持流式输出）
ConversationHistory + Agent + agentic loop + streaming
"""
import os
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional

from dotenv import load_dotenv
from langchain_core.messages import (
    AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

load_dotenv()


class ConversationHistory:
    def __init__(self, system_prompt: str = "", max_turns: int = 30):
        self.system_prompt = system_prompt
        self.max_turns = max_turns
        self.messages: List[BaseMessage] = []

    def add_user(self, content: str):
        self.messages.append(HumanMessage(content=content))
        self._trim()

    def add_assistant(self, message: AIMessage):
        self.messages.append(message)
        self._trim()

    def add_tool_result(self, tool_call_id: str, content: str):
        self.messages.append(ToolMessage(content=content, tool_call_id=tool_call_id))
        self._trim()

    def _trim(self):
        human_indices = [i for i, m in enumerate(self.messages) if isinstance(m, HumanMessage)]
        if len(human_indices) <= self.max_turns:
            return
        cutoff_index = human_indices[-self.max_turns]
        self.messages = self.messages[cutoff_index:]

    def get(self) -> List[BaseMessage]:
        if self.system_prompt:
            if not any(isinstance(m, SystemMessage) for m in self.messages):
                return [SystemMessage(content=self.system_prompt)] + self.messages
        return self.messages

    def clear(self):
        self.messages.clear()


class Agent:
    def __init__(
        self,
        db,
        system_prompt: Optional[str] = None,
        model: str = "qwen-plus",
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ):
        self.db = db
        self._tools: Dict[str, Any] = {}
        self.system_prompt = system_prompt or ""
        self.conversation = ConversationHistory(system_prompt=self.system_prompt)
        self._bound_model = None

        self._llm = ChatOpenAI(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key=os.getenv("DASHSCOPE_API_KEY", ""),
            streaming=True,
        )

    def register_tool(self, tool_obj):
        self._tools[tool_obj.name] = tool_obj
        self._bound_model = None

    def register_tools(self, tools: list):
        for t in tools:
            self.register_tool(t)

    def _get_bound_model(self):
        if self._bound_model is None:
            self._bound_model = self._llm.bind_tools(list(self._tools.values()))
        return self._bound_model

    def chat(self, user_input: str, config: Optional[RunnableConfig] = None) -> str:
        """同步完整输出（兼容旧接口）"""
        return "".join(self.stream(user_input, config))

    def stream(self, user_input: str, config: Optional[RunnableConfig] = None) -> Generator[str, None, None]:
        """
        真实流式输出生成器。
        - 有工具调用时：用 invoke 完整收取（工具调用不能中途截断），yield 工具名提示
        - 无工具调用时：用 model.stream() 真正逐 token yield，第一个 token 立即返回
        """
        self.conversation.add_user(user_input)

        for _ in range(10):
            model = self._get_bound_model()
            messages = self.conversation.get()

            # ── 阶段一：流式收取当前轮次的响应 ──────────────────────────────
            # 先尝试流式，同时检测是否有 tool_calls
            # 通过累积 chunks 拼出完整 AIMessage，判断是否需要调工具
            collected_chunks = []
            collected_content = ""
            collected_tool_calls: dict = {}  # index -> tool_call dict

            for chunk in model.stream(messages, config=config):
                # chunk 是 AIMessageChunk
                if chunk.content:
                    collected_content += chunk.content
                    # 只有在没有工具调用的情况下才实时 yield
                    # 此时还不确定是否有工具调用，先缓存
                    collected_chunks.append(chunk.content)

                # 收集 tool_calls delta
                if chunk.tool_call_chunks:
                    for tc_chunk in chunk.tool_call_chunks:
                        idx = tc_chunk.get("index", 0)
                        if idx not in collected_tool_calls:
                            collected_tool_calls[idx] = {
                                "id": tc_chunk.get("id", ""),
                                "name": tc_chunk.get("name", ""),
                                "args": tc_chunk.get("args", ""),
                            }
                        else:
                            existing = collected_tool_calls[idx]
                            if tc_chunk.get("id"):
                                existing["id"] = tc_chunk["id"]
                            if tc_chunk.get("name"):
                                existing["name"] += tc_chunk["name"]
                            if tc_chunk.get("args"):
                                existing["args"] += tc_chunk["args"]

            # ── 阶段二：判断结果类型 ──────────────────────────────────────────
            if collected_tool_calls:
                # 有工具调用：解析并执行
                import json
                tool_calls_list = []
                for idx in sorted(collected_tool_calls.keys()):
                    tc = collected_tool_calls[idx]
                    try:
                        args = json.loads(tc["args"]) if tc["args"] else {}
                    except json.JSONDecodeError:
                        args = {}
                    tool_calls_list.append({
                        "id": tc["id"],
                        "name": tc["name"],
                        "args": args,
                        "type": "tool_call",
                    })

                # 构造 AIMessage 存入历史
                ai_msg = AIMessage(content=collected_content, tool_calls=tool_calls_list)
                self.conversation.add_assistant(ai_msg)

                for tc in tool_calls_list:
                    yield f"\n⚙️ 正在调用工具：**{tc['name']}**...\n"
                    result = self._execute_tool(tc)
                    self.conversation.add_tool_result(tc["id"], result)
                # 继续下一轮，让 LLM 基于工具结果生成最终回答

            else:
                # 无工具调用：纯文本回答，直接 yield 已收集的内容
                # 由于 stream 过程中内容已全部收集，逐块 yield 出去
                ai_msg = AIMessage(content=collected_content)
                self.conversation.add_assistant(ai_msg)
                for chunk_text in collected_chunks:
                    yield chunk_text
                return

        yield "\n[达到最大工具调用次数]"

    def _execute_tool(self, tool_call: Dict[str, Any]) -> str:
        obj = self._tools.get(tool_call["name"])
        if not obj:
            return f"❌ 未找到工具: {tool_call['name']}"
        try:
            result = obj.invoke(tool_call.get("args", {}))
            return str(result)
        except Exception as e:
            return f"❌ 工具执行失败: {e}"

    def clear_conversation(self):
        self.conversation.clear()

    def get_registered_tools(self) -> List[str]:
        return list(self._tools.keys())