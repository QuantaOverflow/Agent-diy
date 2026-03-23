Feature: 定时提醒
  作为 Telegram 用户，我希望通过自然语言设置定时提醒，
  bot 在指定的北京时间自动执行任务（如查天气、查股票）并主动推送结果。
  提醒存储在内存中，bot 重启后需要重新设置。
  本 feature 仅覆盖 Telegram bot 路径，不覆盖 Web UI 的主动提醒通知能力。

  # ─── Unit 层：验证确定性代码逻辑 ───────────────────────────────────────

  @unit
  Scenario Outline: 设置提醒后 bot 返回确认并存储该提醒
    Given Telegram bot 已初始化
    When Telegram 收到用户 "100" 的消息 "<message>"
    Then bot 应向用户 "100" 发送包含 "提醒" 的消息
    And 用户 "100" 应有 1 个已设置的提醒

    Examples:
      | message                       |
      | 每天早上9点帮我查北京天气     |
      | 每天晚上8点推送今日股市总结   |

  @unit
  Scenario: 支持一次性相对时间提醒
    Given Telegram bot 已初始化
    When Telegram 收到用户 "100" 的消息 "一分钟后提醒我睡觉"
    Then bot 应向用户 "100" 发送包含 "提醒" 的消息
    And 用户 "100" 应有 1 个已设置的提醒

  @unit
  Scenario: 提醒在预定时间触发时 bot 主动推送任务结果
    Given Telegram bot 已初始化
    And 用户 "100" 已设置提醒 "查北京天气"
    When 用户 "100" 的提醒在预定时间触发
    Then bot 应主动向用户 "100" 发送包含任务结果的消息

  @unit
  Scenario: list_reminders 工具返回已有提醒
    Given 用户 "100" 有一个提醒 "查北京天气"
    When 调用 list_reminders 工具查询用户 "100" 的提醒
    Then 结果应包含 "天气"

  @unit
  Scenario: list_reminders 工具在无提醒时返回空
    When 调用 list_reminders 工具查询用户 "200" 的提醒
    Then 结果应为空列表

  @unit
  Scenario: cancel_reminder 工具取消后提醒被移除
    Given 用户 "100" 有一个提醒 "查北京天气"
    When 调用 cancel_reminder 工具取消用户 "100" 的提醒 "1"
    Then 用户 "100" 应有 0 个已设置的提醒

  @unit
  Scenario: 提醒触发时任务执行失败 bot 主动向用户发送错误消息
    Given Telegram bot 已初始化
    And 用户 "100" 已设置提醒 "查北京天气"
    And backend 处理消息时抛出异常
    When 用户 "100" 的提醒在预定时间触发
    Then bot 应向用户 "100" 发送包含 "出错" 的消息

  @unit
  Scenario: cancel_reminder 工具取消不存在的提醒时返回错误提示
    When 调用 cancel_reminder 工具取消用户 "100" 的提醒 "999"
    Then 结果应提示提醒不存在

  @unit
  Scenario: 用户不能取消其他用户的提醒
    Given 用户 "100" 有一个提醒 "查北京天气"
    When 调用 cancel_reminder 工具取消用户 "200" 的提醒 "1"
    Then 结果应提示提醒不存在
    And 用户 "100" 应有 1 个已设置的提醒

  @unit
  Scenario: 调度注册失败时 add 应回滚提醒数据
    Given 提醒调度注册会失败
    When 用户 "100" 在 "09:00" 添加提醒 "查北京天气"
    Then 提醒添加应失败
    And 用户 "100" 应有 0 个已设置的提醒

  @unit
  Scenario: 不同用户的提醒互相隔离
    Given Telegram bot 已初始化
    And 用户 "100" 已设置提醒 "查北京天气"
    When Telegram 收到用户 "200" 的消息 "查看我的提醒"
    Then bot 应向用户 "200" 发送包含 "没有" 的消息

  @integration
  Scenario: 用户未指定时间时 bot 反问
    Given Telegram bot 已初始化
    When Telegram 收到用户 "100" 的消息 "提醒我查北京天气"
    Then bot 的回复应包含反问时间的内容
    And 用户 "100" 应有 0 个已设置的提醒

  # ─── Integration 层：验证 LLM 自然语言理解能力 ──────────────────────────

  @integration
  Scenario Outline: LLM 正确识别自然语言中的设置提醒意图
    Given Telegram bot 已初始化
    When Telegram 收到用户 "100" 的消息 "<message>"
    Then bot 的回复应提及 "提醒"
    And 用户 "100" 应有 1 个已设置的提醒

    Examples:
      | message                              |
      | 每天早上九点帮我查一下北京的天气     |
      | 每天晚上8点给我推一下今天的股市情况  |

  @integration
  Scenario: LLM 正确识别查看提醒意图
    Given Telegram bot 已初始化
    And 用户 "100" 已设置提醒 "查北京天气"
    When Telegram 收到用户 "100" 的消息 "我设置了哪些提醒？"
    Then bot 的回复应提及 "天气"

  @integration
  Scenario: LLM 正确识别取消提醒意图
    Given Telegram bot 已初始化
    And 用户 "100" 已设置提醒 "查北京天气"
    When Telegram 收到用户 "100" 的消息 "取消天气提醒"
    Then bot 应向用户 "100" 发送包含 "取消" 的消息
    And 用户 "100" 应有 0 个已设置的提醒
