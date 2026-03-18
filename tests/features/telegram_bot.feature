Feature: Telegram Bot 接入
  作为用户，我希望通过 Telegram bot 与 agent 进行自然语言交互，
  bot 能理解我的意图并调用对应功能（星座运势、天气、网络搜索等），
  且每个用户拥有独立的对话上下文。

  # ─── Unit 层：验证确定性代码逻辑 ───────────────────────────────────────

  @unit
  Scenario: 用户消息映射到独立的会话标识
    Given Telegram bot 已初始化
    When Telegram 收到用户 "111" 的消息 "你好"
    And Telegram 收到用户 "222" 的消息 "你好"
    Then 两个请求应使用不同的会话标识

  @unit
  Scenario: 缺少 bot token 时启动失败
    Given TELEGRAM_BOT_TOKEN 环境变量未配置
    When 尝试启动 Telegram bot
    Then 应抛出配置缺失错误

  @unit
  Scenario: agent 返回内容作为 Telegram 消息发送
    Given Telegram bot 已初始化
    And backend 对任意消息返回 "这是回复内容"
    When Telegram 收到用户 "123" 的消息 "测试"
    Then bot 应向用户 "123" 发送文本 "这是回复内容"

  @unit
  Scenario: agent 抛出异常时 bot 回复错误提示
    Given Telegram bot 已初始化
    And backend 处理消息时抛出异常
    When Telegram 收到用户 "123" 的消息 "测试"
    Then bot 应向用户 "123" 发送包含 "出错" 的消息

  # ─── E2E 层：验证 LLM 能力与功能路由 ──────────────────────────────────

  @e2e
  Scenario Outline: 用户通过 Telegram 进行自由对话
    Given Telegram bot 已初始化
    When Telegram 收到用户 "100" 的消息 "<message>"
    Then bot 的回复应与消息内容相关

    Examples:
      | message          |
      | 你是谁？         |
      | 帮我写一首短诗   |

  @e2e
  Scenario Outline: 用户通过 Telegram 查询星座运势
    Given Telegram bot 已初始化
    And Gmail credentials are configured
    When Telegram 收到用户 "100" 的消息 "<message>"
    Then bot 的回复应包含星座运势内容
    And bot 的回复应为中文

    Examples:
      | message                    |
      | 今天白羊座运势怎么样？     |
      | 帮我查一下双子座今日运势   |

  @e2e
  Scenario Outline: 用户通过 Telegram 查询天气
    Given Telegram bot 已初始化
    When Telegram 收到用户 "100" 的消息 "<message>"
    Then bot 的回复应包含天气信息

    Examples:
      | message                |
      | 北京今天天气怎么样？   |
      | 上海明天会下雨吗？     |

  @e2e
  Scenario Outline: 用户通过 Telegram 触发网络搜索
    Given Telegram bot 已初始化
    When Telegram 收到用户 "100" 的消息 "<message>"
    Then bot 的回复应与搜索话题相关

    Examples:
      | message                      |
      | 搜一下最近 AI 领域新进展     |
      | 帮我查查 DeepSeek 最新动态   |

  @e2e
  Scenario: 多轮对话保持上下文
    Given Telegram bot 已初始化
    When Telegram 收到用户 "100" 的消息 "我叫小明"
    And Telegram 收到用户 "100" 的消息 "你还记得我叫什么名字吗？"
    Then bot 的回复应提及 "小明"

  @unit
  Scenario: bot 重启后丢弃启动前的积压消息
    Given Telegram bot 已初始化
    And bot 的启动时间为 "2026-03-17 10:00:00 UTC"
    When 收到一条发送时间为 "2026-03-17 09:58:00 UTC" 的 Telegram 文本消息
    Then agent 不应被调用
    And bot 不应发送任何回复

  @unit
  Scenario: bot 正常处理启动后收到的消息
    Given Telegram bot 已初始化
    And bot 的启动时间为 "2026-03-17 10:00:00 UTC"
    When 收到一条发送时间为 "2026-03-17 10:01:00 UTC" 的 Telegram 文本消息
    Then backend 应被调用一次

  @unit
  Scenario: 网络抖动后 bot 仍可处理后续消息
    Given Telegram bot 已初始化
    And bot 的启动时间为 "2026-03-17 10:00:00 UTC"
    And 第一条消息发送回复将连续失败三次，第二条消息发送成功
    When 收到一条发送时间为 "2026-03-17 10:01:00 UTC" 的 Telegram 文本消息
    And 收到一条发送时间为 "2026-03-17 10:02:00 UTC" 的 Telegram 文本消息
    Then backend 应被调用两次
    And 第二条消息应成功发送回复

  @e2e
  Scenario: 不同用户对话上下文互不干扰
    Given Telegram bot 已初始化
    When Telegram 收到用户 "101" 的消息 "我的名字是 Alice"
    And Telegram 收到用户 "102" 的消息 "我叫什么名字？"
    Then 用户 "102" 的回复不应提及 "Alice"
