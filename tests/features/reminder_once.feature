Feature: 一次性定时提醒
  作为 Telegram 用户，我可以设置在指定时间后触发一次的提醒，
  触发后提醒自动删除，不再重复。

  @unit
  Scenario: 一次性提醒触发后从 store 中移除
    Given 用户 "100" 已设置一次性提醒 "喝水"
    When 用户 "100" 的提醒在预定时间触发
    Then 用户 "100" 应有 0 个已设置的提醒

  @unit
  Scenario: 一次性任务触发时调用 agent 并发结果
    Given 用户 "100" 已设置一次性提醒 "查北京天气"
    When 用户 "100" 的提醒在预定时间触发
    Then bot 应主动向用户 "100" 发送包含任务结果的消息

  @integration
  Scenario Outline: LLM 正确解析相对时间并设置一次性提醒
    Given Telegram bot 已初始化
    When Telegram 收到用户 "100" 的消息 "<message>"
    Then 用户 "100" 应有 1 个已设置的提醒

    Examples:
      | message           |
      | 5分钟后提醒我喝水 |
      | 1分钟后帮我查天气 |
