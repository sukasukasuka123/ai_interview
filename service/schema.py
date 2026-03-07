# service/schema.py


class SchemaInitializer:
    def __init__(self, db):
        self.db = db

    def initialize(self):
        # ── 岗位表 ───────────────────────────────────────────────────────────
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS job_position (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                description TEXT,
                tech_stack  TEXT NOT NULL DEFAULT '[]',
                created_at  TEXT NOT NULL
            )
        """)

        # ── 题库（新结构：id, classify, level, content, answer） ─────────────
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS question_bank (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                classify TEXT NOT NULL DEFAULT '通用',
                level    TEXT NOT NULL DEFAULT '中级',
                content  TEXT NOT NULL,
                answer   TEXT NOT NULL DEFAULT ''
            )
        """)
        self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_qb_classify_level
            ON question_bank (classify, level)
        """)

        # ── 学生表 ───────────────────────────────────────────────────────────
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS student (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                email      TEXT,
                created_at TEXT NOT NULL
            )
        """)

        # ── 面试会话 ─────────────────────────────────────────────────────────
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS interview_session (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id      INTEGER NOT NULL,
                job_position_id INTEGER NOT NULL,
                status          TEXT NOT NULL DEFAULT 'ongoing',
                started_at      TEXT NOT NULL,
                finished_at     TEXT,
                overall_score   REAL,
                report          TEXT,
                FOREIGN KEY (student_id)      REFERENCES student(id),
                FOREIGN KEY (job_position_id) REFERENCES job_position(id)
            )
        """)

        # ── 面试轮次（每一问一答） ────────────────────────────────────────────
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS interview_turn (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id     INTEGER NOT NULL,
                turn_index     INTEGER NOT NULL,
                question_text  TEXT NOT NULL,
                student_answer TEXT NOT NULL DEFAULT '',
                ai_followup    TEXT,
                scores         TEXT,
                audio_path     TEXT,
                created_at     TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES interview_session(id)
            )
        """)

        # ── RAG 知识库分块 ────────────────────────────────────────────────────
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_chunk (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                job_position_id INTEGER NOT NULL DEFAULT 0,
                source          TEXT NOT NULL,
                chunk_text      TEXT NOT NULL,
                chunk_index     INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL
            )
        """)
        self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_kc_position
            ON knowledge_chunk (job_position_id)
        """)

        self._seed_positions()
        self._seed_questions()

    def _seed_positions(self):
        existing = self.db.fetchone("SELECT COUNT(*) FROM job_position")[0]
        if existing > 0:
            return

        import json
        from datetime import datetime
        now = datetime.now().isoformat()

        positions = [
            (
                "Java 后端工程师",
                "面向服务端开发方向，考察 Java 基础、Spring 生态、数据库、分布式系统等",
                json.dumps(["Java", "Spring Boot", "MySQL", "Redis", "MyBatis",
                            "消息队列", "分布式", "JVM", "多线程"], ensure_ascii=False),
                now,
            ),
            (
                "前端开发工程师",
                "面向 Web 前端方向，考察 JavaScript、框架、工程化、性能优化等",
                json.dumps(["JavaScript", "TypeScript", "Vue", "React",
                            "HTML/CSS", "Webpack", "浏览器原理", "网络"], ensure_ascii=False),
                now,
            ),
        ]
        self.db.executemany(
            "INSERT INTO job_position (name, description, tech_stack, created_at) VALUES (?,?,?,?)",
            positions,
        )

    def _seed_questions(self):
        existing = self.db.fetchone("SELECT COUNT(*) FROM question_bank")[0]
        if existing > 0:
            return

        questions = [
            # Java 基础
            ("Java基础", "初级", "Java 中 == 和 equals() 的区别是什么？",
             "== 比较的是引用地址（基本类型比值），equals() 默认也是比较引用，但 String、Integer 等类重写了 equals() 来比较内容。建议比较对象内容时始终使用 equals()，并注意 null 判断。"),
            ("Java基础", "初级", "什么是自动装箱和拆箱？有什么注意事项？",
             "自动装箱是基本类型自动转换为包装类（int→Integer），拆箱是反过来。注意：Integer 缓存 -128~127，此范围内 == 比较为 true；频繁拆装箱会影响性能；拆箱时若对象为 null 会抛 NullPointerException。"),
            ("Java基础", "中级", "请解释 Java 的 volatile 关键字的作用和原理。",
             "volatile 保证：1) 可见性——对 volatile 变量的写操作立即刷新到主内存，读操作从主内存读取；2) 有序性——禁止指令重排（通过内存屏障实现）。不保证原子性，如 i++ 仍是非原子的。适用于状态标志位、double-checked locking 等场景。"),
            ("Java基础", "高级", "详细说明 Java 内存模型（JMM）及 happens-before 原则。",
             "JMM 定义了多线程程序中变量的读写规则。happens-before 是 JMM 的核心，规定了操作间的可见性和顺序：1) 程序顺序规则；2) 监视器锁规则（解锁 happens-before 加锁）；3) volatile 规则；4) 线程启动/终止规则；5) 传递性。只要 A happens-before B，A 的结果对 B 可见。"),

            # JVM
            ("JVM", "中级", "简述 JVM 垃圾回收算法及常见收集器。",
             "算法：1) 标记-清除（有碎片）2) 复制算法（无碎片，内存利用率低，适合新生代）3) 标记-整理（无碎片，适合老年代）4) 分代收集（综合使用）。收集器：Serial/SerialOld（单线程）、Parallel/ParallelOld（多线程吞吐量优先）、CMS（并发低延迟，有碎片）、G1（分 Region，兼顾吞吐和延迟）、ZGC（超低延迟，停顿<10ms）。"),
            ("JVM", "高级", "G1 GC 的工作原理是什么？与 CMS 有何区别？",
             "G1 将堆划分为等大的 Region，逻辑上分新生代/老年代但不连续。工作流程：初始标记→并发标记→最终标记→筛选回收（优先回收垃圾最多的 Region）。优势：可预测停顿时间、无内存碎片、大堆表现好。vs CMS：G1 整体停顿更可控，CMS 并发阶段占 CPU 多；G1 在高内存（>6GB）场景更适合。"),

            # Spring Boot
            ("Spring", "初级", "Spring Boot 的自动配置原理是什么？",
             "@SpringBootApplication 包含 @EnableAutoConfiguration，通过 SpringFactoriesLoader 读取所有 jar 包的 META-INF/spring.factories（Spring Boot 3.x 改为 spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports），加载自动配置类，再通过 @ConditionalOnClass、@ConditionalOnMissingBean 等条件注解按需生效，实现零配置开箱即用。"),
            ("Spring", "中级", "Spring 事务的传播行为有哪些？什么情况下事务会失效？",
             "传播行为：REQUIRED（默认，加入或新建）、REQUIRES_NEW（始终新建）、NESTED（嵌套）、SUPPORTS、NOT_SUPPORTED、NEVER、MANDATORY。失效场景：1) 方法非 public；2) 同类内部调用（绕过 AOP 代理）；3) 异常被 catch 吞掉；4) 抛出非 RuntimeException 但未配置 rollbackFor；5) 数据库引擎不支持事务（如 MyISAM）。"),
            ("Spring", "高级", "Spring AOP 的实现原理是什么？JDK 动态代理和 CGLIB 的区别？",
             "Spring AOP 基于代理模式：目标类实现接口时默认用 JDK 动态代理（通过反射生成接口实现类），否则用 CGLIB（生成目标类的子类字节码）。Spring Boot 2.x 后默认用 CGLIB。JDK 代理只能代理接口方法，CGLIB 不能代理 final 类/方法。AspectJ 是编译期/加载期织入，功能更强大但配置复杂。"),

            # MySQL
            ("MySQL", "初级", "MySQL 中 InnoDB 和 MyISAM 的区别是什么？",
             "InnoDB：支持事务（ACID）、外键、行级锁、MVCC，有崩溃恢复能力，适合高并发写场景，是默认引擎。MyISAM：不支持事务和外键，表级锁，读性能略高，适合读多写少场景，不支持崩溃恢复。现代项目几乎都用 InnoDB。"),
            ("MySQL", "中级", "解释 MySQL 的 MVCC 机制及其如何解决读写冲突。",
             "MVCC（多版本并发控制）通过 undo log 保存数据历史版本，每个事务有 Read View（快照）。读操作（快照读）不加锁，直接读取符合当前事务可见性的数据版本，实现读写不互斥。可见性判断：事务 ID < Read View 最小活跃事务 ID 则可见；在活跃列表中则不可见；通过 undo log 链找到合适版本。RC 每次读取生成新 Read View，RR 只在首次读时生成。"),
            ("MySQL", "高级", "如何分析和优化一条慢 SQL？",
             "步骤：1) EXPLAIN 查看执行计划（关注 type: 最优 const/eq_ref/ref，避免 ALL；Extra 中 Using filesort/temporary 需优化）；2) 检查索引使用情况，是否命中、是否回表；3) 优化手段：建合适索引、调整查询条件顺序（最左前缀）、避免索引失效（函数运算、类型转换、%前缀）、大表分页用覆盖索引+子查询、拆分复杂 JOIN；4) 分析数据分布，考虑索引下推、MRR 等优化。"),

            # Redis
            ("Redis", "初级", "Redis 支持哪些数据结构？各自的使用场景是什么？",
             "String：缓存、计数器、分布式锁；Hash：对象存储（用户信息）；List：消息队列、最新列表；Set：去重集合、共同好友；ZSet（有序集合）：排行榜、带权重的优先队列；Bitmap：签到、在线状态；HyperLogLog：UV 统计（有误差）；Stream：消息流；Geo：地理位置。"),
            ("Redis", "中级", "Redis 的持久化方式有哪些？如何选择？",
             "RDB：定时快照，文件小，恢复快，数据可能丢失（上次快照后的写操作）。AOF：记录写命令，默认每秒 fsync，数据更安全，文件较大，通过 rewrite 压缩。混合持久化（Redis 4.0+）：AOF 文件包含 RDB 快照+增量 AOF，兼顾速度和完整性。选择：高可靠用 AOF 或混合；允许少量丢失且重启快用 RDB；生产环境建议两者都开。"),
            ("Redis", "高级", "如何实现 Redis 分布式锁？有哪些注意事项？",
             "基础实现：SET key value NX EX timeout（原子操作，value 用唯一标识防止误删）。释放时用 Lua 脚本保证原子性：if get(key)==value then del(key)。注意事项：1) 锁超时要>业务执行时间（可用 Watchdog 续期）；2) 单点 Redis 故障问题——可用 Redlock 算法（向多数节点加锁）；3) 锁可重入问题；4) 主从切换时主节点宕机可能导致锁丢失。生产建议用 Redisson。"),

            # 前端 JavaScript
            ("JavaScript", "初级", "请解释 JavaScript 中的事件冒泡和事件捕获。",
             "DOM 事件传播分三阶段：捕获（从 window 到目标）→目标→冒泡（从目标到 window）。addEventListener 第三个参数 true 为捕获，false（默认）为冒泡。stopPropagation() 阻止传播，preventDefault() 阻止默认行为。事件委托利用冒泡：将子元素事件监听绑在父元素上，减少监听器数量，适合动态列表。"),
            ("JavaScript", "中级", "详细解释 JavaScript 的原型链和继承机制。",
             "每个对象有 [[Prototype]]（通过 __proto__ 访问），函数有 prototype 属性。访问属性时沿原型链向上查找直到 null。继承方式：ES6 class extends（推荐，本质是原型继承的语法糖）；组合继承（call + prototype）；Object.create() 等。注意：instanceof 检查原型链；Object.getPrototypeOf() 是标准获取原型方式。"),
            ("JavaScript", "高级", "请详细解释 JavaScript 的事件循环（Event Loop）机制。",
             "JS 单线程，通过事件循环处理异步。执行顺序：1) 执行调用栈中的同步代码；2) 清空微任务队列（Promise.then、queueMicrotask、MutationObserver）；3) 执行一个宏任务（setTimeout、setInterval、I/O、UI rendering）；4) 回到步骤2。重要：每个宏任务后都要清空微任务队列。Node.js 的事件循环还有 libuv 的各个阶段（timers/I/O/check等）。"),

            # 前端 Vue/React
            ("Vue/React", "初级", "Vue3 和 Vue2 响应式系统的区别是什么？",
             "Vue2 用 Object.defineProperty 拦截 getter/setter，缺点：无法监听新增/删除属性和数组下标变化，需 $set/$delete。Vue3 改用 Proxy，优点：可监听任意属性增删、数组下标、Map/Set 等；惰性递归（只在访问时才深层代理）；性能更好。Vue3 的 ref/reactive 基于 Proxy + track/trigger 依赖追踪系统实现细粒度更新。"),
            ("Vue/React", "中级", "React Hooks 的使用规则和常见陷阱有哪些？",
             "规则：1) 只在函数组件或自定义 Hook 的顶层调用；2) 不在循环/条件/嵌套函数中调用（保证调用顺序固定）。常见陷阱：1) useEffect 依赖数组遗漏导致闭包陈旧值（stale closure）；2) 无限循环——effect 中修改了 dep；3) useCallback/useMemo 过度使用；4) 直接修改 state 对象（应创建新对象）；5) 组件卸载后 setState 警告（需在 effect 中清理副作用）。"),

            # 网络
            ("计算机网络", "初级", "HTTP 和 HTTPS 的区别是什么？TLS 握手过程是怎样的？",
             "HTTP 明文传输，HTTPS = HTTP + TLS/SSL 加密。TLS 握手（TLS 1.2）：1) Client Hello（支持的加密套件、随机数）；2) Server Hello + 证书；3) 客户端验证证书，生成预主密钥用服务端公钥加密发送；4) 双方用三个随机数生成会话密钥；5) 切换加密通信。TLS 1.3 简化为 1-RTT，性能更好。"),
            ("计算机网络", "中级", "HTTP/1.1、HTTP/2、HTTP/3 的主要区别是什么？",
             "HTTP/1.1：持久连接，但有队头阻塞（同一连接串行）。HTTP/2：多路复用（一个 TCP 连接多个流）、头部 HPACK 压缩、服务器推送、二进制分帧，但 TCP 层仍有队头阻塞。HTTP/3：基于 QUIC（UDP），彻底解决队头阻塞，连接迁移（IP 变化不断连），0-RTT 重连，是未来趋势。"),

            # 数据结构算法
            ("数据结构与算法", "初级", "简述常见排序算法的时间复杂度和适用场景。",
             "冒泡/选择/插入：O(n²)，小数据集。快速排序：平均 O(nlogn)，不稳定，最常用。归并排序：O(nlogn)，稳定，适合链表和外部排序。堆排序：O(nlogn)，不稳定，适合 TopK 问题。计数/桶/基数排序：O(n+k)，适合整数或范围已知的数据。Java Arrays.sort 对基本类型用双轴快排，对对象用 TimSort（归并+插入排序混合）。"),
            ("数据结构与算法", "中级", "什么是红黑树？它有哪些性质？在 Java 中的应用？",
             "红黑树是自平衡 BST，性质：1) 节点红或黑；2) 根节点黑；3) 叶节点（NIL）黑；4) 红节点的子节点必为黑；5) 任意节点到叶子节点的路径包含相同数量的黑节点。保证最长路径不超过最短路径 2 倍，查找/插入/删除均 O(logn)。Java 应用：TreeMap/TreeSet 底层、HashMap 链表长度>8 时转为红黑树。"),
        ]

        self.db.executemany(
            "INSERT INTO question_bank (classify, level, content, answer) VALUES (?,?,?,?)",
            questions,
        )