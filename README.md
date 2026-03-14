# AI 模拟面试与能力提升平台

> 锐捷网络企业命题 · 开发者协作手册

---

## 目录

- [项目总览](#1-项目总览)
- [快速启动](#2-快速启动)
- [核心调用链](#3-核心调用链)
- [数据库结构](#4-数据库结构)
- [UI 组件规范](#5-ui-组件规范)
- [工具权限体系](#6-工具权限体系skillset)
- [开发与提交规范](#7-开发与提交规范)
- [FAQ](#8-常见问题-faq)

---

## 1. 项目总览

### 1.1 赛题背景

本项目为「面试与能力提升软件」竞赛作品。

核心场景：
- 学生通过模拟面试，练习技术岗位面试题
- AI 面试官从题库抽题 → 学生回答 → 多维度评分 → 个性化提升建议
- 老师上传课程资料后，AI 可基于课程内容出题，实现「课程答辩式面试」

### 1.2 架构一览

| 层次 | 技术栈 | 说明 |
|------|--------|------|
| UI 层 | PySide6 6.6 | 桌面端，四个主面板 |
| 引擎层 | Python 3.11 | InterviewEngine / HelperEngine |
| Agent 层 | agent_core.py | 流式 + 工具调用框架 |
| 工具层 | LangChain Core | 按 SkillSet 权限分发，懒加载 |
| 大模型 | Qwen (DashScope) | qwen3-omni-flash |
| 知识库 | 阿里云百炼 RAG | KnowledgeCore 封装，多库独立实例 |
| 存储 | SQLite (WAL 模式) | 本地单文件 |

### 1.3 目录结构

```
ai_interview/
├── main.py                          # 启动入口，组装引擎和 UI
├── .env                             # 密钥配置（不提交 Git）
├── .env.example                     # 密钥模板
├── requirements.txt
│
├── service/
│   ├── db.py                        # SQLite 连接管理（单例）
│   ├── schema.py                    # 建表 & 种子数据
│   ├── agent_core.py                # Agent 框架（流式 + 工具调用）
│   ├── interview_engine.py          # 面试流程引擎
│   ├── helper_engine.py             # AI 助手引擎
│   ├── evaluator.py                 # 多维度评分
│   └── tools/
│       ├── __init__.py
│       ├── registry.py              # 工具注册中心（懒加载）
│       ├── permissions.py           # ToolGroup + SkillSet 定义
│       ├── db_tools.py              # 题库/历史/岗位工具
│       ├── search_tools.py          # 博查/Wikipedia 联网搜索
│       └── knowledge/               # 知识库能力子模块
│           ├── __init__.py
│           ├── KnowledgeCore.py     # 百炼 RAG SDK 封装（多库通用）
│           ├── create_knowledge_search_tool.py  # search_knowledge_base
│           └── create_ds_course_tool.py         # search_ds_course
│
└── UI/
    ├── components.py                # 统一组件库（Theme / ChatBubble 等）
    ├── interview_panel.py           # 面试主界面
    ├── quiz_panel.py                # 题库练习
    ├── history_panel.py             # 历史成长曲线
    └── agent_panel.py               # AI 知识助手
```

---

## 2. 快速启动

### 2.1 环境要求

| 依赖 | 版本 | 备注 |
|------|------|------|
| Python | 3.11+ | 低版本缺少 `match/case`，不兼容 |

> ⚠️ `torch` 建议单独先装：
> ```bash
> pip install torch==2.10.0 --index-url https://download.pytorch.org/whl/cpu
> pip install -r requirements.txt
> ```

### 2.2 安装步骤

1. 克隆仓库
2. 复制 `.env.example` 为 `.env`，填入密钥（见 2.3）
3. 安装依赖

### 2.3 .env 配置

> ⚠️ **所有 Key 均不要提交 Git**，`.gitignore` 已包含 `.env`

![相关示例](./.env_example)
```env
# ── 核心（必填）──────────────────────────────────────────────────────────────
DASHSCOPE_API_KEY="sk-xxx"

# ── 知识库 ID（在百炼控制台创建知识库后，复制 Index ID 填入）────────────────
# 技术知识库：Java/Spring/MySQL/Redis/前端等，AI 助手使用
TECH_KB_ID="xxxxxxxxxxxxxxxxx"
# 数据结构课程知识库：课程讲义/场景素材，面试引擎出题使用
DS_COURSE_KB_ID="xxxxxxxxxxxxxxxxx"

# ── 百炼官方 SDK 模式（三件套，比 HTTP 模式更稳定，建议配置）────────────────
BAILOU_WORKSPACE_ID="xxxxxxxxxxxxxxxxxxxx"
ALIBABA_CLOUD_ACCESS_KEY_ID="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
ALIBABA_CLOUD_ACCESS_KEY_SECRET="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

# ── 联网搜索（可选，不填则跳过 web_search 工具）─────────────────────────────
BOCHA_API_KEY="xxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
TAVILY_API_KEY="xxxxxxxxxxxxxxxxxx"
```

**配置优先级：**
- 最低要求：`DASHSCOPE_API_KEY`，HTTP 模式启动（知识库 ID 可为空，对应工具自动跳过）
- 加上百炼三件套：切换官方 SDK 模式，更稳定
- `TECH_KB_ID` / `DS_COURSE_KB_ID` 缺失时，对应工具跳过加载，不会崩溃

---

## 3. 核心调用链

### 3.1 面试流程

```
UI/interview_panel.py
  └─ InterviewWorker（QThread）
       ├─ engine.start_session()              → 写 DB，构建 InterviewHistory
       ├─ engine.get_first_question_stream()  → Agent.stream()（含工具调用）→ LLM
       ├─ engine.submit_answer_stream()       → 评分 + Agent.stream() → LLM
       └─ engine.finish_session_stream()      → 生成报告 → LLM
```

### 3.2 AI 助手流程

```
UI/agent_panel.py
  └─ helper_engine.stream(user_input)
       └─ Agent.stream()
            └─ 工具调用时 → registry → 对应工具函数
```

### 3.3 InterviewEngine 工具调用机制

面试官每次出题/追问走 `Agent.stream()`（带工具），LLM 可主动调用：
- `draw_questions_from_bank` 抽题
- `search_ds_course` 检索课程素材

调用前把 `InterviewHistory` 同步进 `Agent.conversation`，调用后把结果写回 `InterviewHistory`，保持每个 session 的对话状态独立。

### 3.4 Qt 跨线程信号协议

| Token | 含义 |
|-------|------|
| `__EVAL__:{json}` | 评分结果，UI 渲染 ScoreCardBubble |
| `__IS_FINISHED__` | 本轮是最后一题，UI 禁用输入框 |
| `__FINISHED__` | 无更多未答题目（兜底） |
| `__SCORE__:{float}` | 报告总分 |
| `__ERROR__:{msg}` | 内部错误 |

---

## 4. 数据库结构

| 表名 | 用途 | 关键字段 |
|------|------|----------|
| `job_position` | 面试岗位定义 | `id`, `name`, `tech_stack`（JSON） |
| `question_bank` | 本地种子题库 | `classify`, `level`, `content`, `answer` |
| `student` | 学生信息 | `id`, `name` |
| `interview_session` | 面试会话 | `student_id`, `job_position_id`, `status`, `overall_score`, `report` |
| `interview_turn` | 每轮问答 | `session_id`, `turn_index`, `question_text`, `student_answer`, `scores`（JSON）, `audio_path` |

---

## 5. UI 组件规范

> ⚠️ 所有新增 UI 代码必须从 `UI/components.py` 引入主题色，禁止硬编码颜色值。

| 组件 | 用途 |
|------|------|
| `Theme`（别名 `T`） | 颜色常量 |
| `ButtonFactory` | 按钮工厂（primary/solid/ghost） |
| `ChatBubble` | 聊天气泡（支持 Markdown） |
| `ScoreCardBubble` | 评分卡片 |
| `TypingIndicator` | AI 打字等待动画 |
| `StreamSignals` | 跨线程信号（流式输出用） |
| `GLOBAL_QSS` | 全局样式表 |

新增面板检查清单：
- [ ] 继承 `QWidget`
- [ ] `__init__` 中调用 `self.setStyleSheet(GLOBAL_QSS + ...)`
- [ ] 颜色全部用 `T.XXX`
- [ ] 按钮全部用 `ButtonFactory`
- [ ] 耗时操作用 `QThread` + `Signal`，不阻塞主线程

---

## 6. 工具权限体系（SkillSet）

### 当前 SkillSet

| 集合 | 工具数 | 场景 |
|------|--------|------|
| `INTERVIEW_SKILLS` | 4 | 面试引擎：COMMON_GROUP + DS_COURSE_GROUP |
| `READONLY_SKILLS` | 5 | 只读查询：题库 + 技术知识库 |
| `ASSISTANT_SKILLS` | 8 | AI 助手全量 |
| `ADMIN_SKILLS` | 8 | 管理员（预留） |

### 当前工具清单

| 工具名 | 所属 Group | 使用方 |
|--------|-----------|--------|
| `get_job_position_info` | COMMON | 两个引擎 |
| `draw_questions_from_bank` | COMMON | 两个引擎 |
| `get_question_bank_stats` | COMMON | 两个引擎 |
| `search_question_bank` | QUIZ | HelperEngine |
| `search_knowledge_base` | RAG | HelperEngine |
| `search_ds_course` | DS_COURSE | InterviewEngine |
| `web_search` | SEARCH | HelperEngine |
| `search_wikipedia` | SEARCH | HelperEngine |
| `get_student_interview_history` | HISTORY | HelperEngine |
| `get_student_id_by_name` | HISTORY | HelperEngine |

---

## 7. 开发与提交规范

### 分支策略

```
main          ← 保持可运行，只接受经过测试的合并
feature/*     ← 功能开发
hotfix/*      ← 紧急修复
release_test  ← 发布前测试
```

### Commit 格式

```
feat(interview): 面试官支持工具调用抽题
fix(kb): 修复 HTTP 模式空响应体解析异常
refactor(tools): KnowledgeCore 认证信息统一从 env 读取
docs: 更新 README 目录结构和 .env 配置说明
```

### .gitignore 必须包含

```gitignore
.env
*.db
__pycache__/
*.pyc
```

### 提交前自检

- [ ] `python main.py` 能正常打开窗口
- [ ] 完整面试流程：选岗 → 回答 → 结束 → 报告
- [ ] 题库面板分页/排序/搜索正常
- [ ] AI 助手工具调用正常

---

## 8. 常见问题 FAQ

**Q: 启动报知识库相关错误？**
检查 `.env` 中 `TECH_KB_ID` / `DS_COURSE_KB_ID` 是否填写。未填写时对应工具会跳过加载（打印 warning），不影响其他功能。

**Q: 面试官不出题 / 返回空字符串？**
用 curl 验证 `DASHSCOPE_API_KEY` 是否有效：
```bash
curl https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions \
  -H "Authorization: Bearer $DASHSCOPE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3-omni-flash","messages":[{"role":"user","content":"hi"}]}'
```

**Q: 知识库检索返回「未找到相关内容」？**
确认百炼控制台知识库状态为「就绪」，文档上传后索引需等待 5-30 分钟。

**Q: `QComboBox` 下拉列表背景变黑？**
确认面板的 `setStyleSheet` 包含了 `GLOBAL_QSS`。

**Q: 博查搜索显示「未加载」？**
`BOCHA_API_KEY` 未配置是正常现象，web_search 工具跳过，不影响其他功能。

---

*如有问题群里 @ 队长或提 Issue。Good luck! 🚀*