Feature: 定时任务触发执行
  作为 Telegram 用户，我设置的定时提醒到时间后，bot 会自动调用 AI 执行该任务并将结果发送给我。

  @unit
  Scenario: 提醒触发时调用 agent 并推送结果
    Given 用户 "100" 已设置提醒 "喝水"
    When 用户 "100" 的提醒在预定时间触发
    Then bot 应主动向用户 "100" 发送包含任务结果的消息

  @unit
  Scenario: backend 报错时推送错误提示
    Given 用户 "100" 已设置提醒 "查北京天气"
    And backend 处理消息时抛出异常
    When 用户 "100" 的提醒在预定时间触发
    Then bot 应向用户 "100" 发送包含 "出错" 的消息

  @integration
  Scenario Outline: 定时触发时 LLM 自然响应各类任务
    Given Telegram bot 已初始化
    And 用户 "100" 已设置提醒 "<task>"
    When 用户 "100" 的提醒在预定时间触发
    Then bot 应主动向用户 "100" 发送包含任务结果的消息

    Examples:
      | task       |
      | 喝水       |
      | 查北京天气 |
