Feature: Telegram 流式回复
  作为 Telegram 用户，我希望发送消息后能立即看到 bot 的响应在逐步生成，
  而非等待数秒后才一次性收到完整回复。

  # ─── Unit 层：验证流式编辑消息的代码逻辑 ──────────────────────────────

  @unit
  Scenario: 流式回复先发占位消息再逐步编辑至完整内容
    Given Telegram bot 已初始化
    And agent 流式返回多个 token
    When 用户 "123" 发送消息 "你好"
    Then bot 应先发送占位消息
    And bot 应编辑该消息至少一次
    And 最终消息应包含完整回复内容

  @unit
  Scenario: 工具调用时编辑消息中显示工具状态
    Given Telegram bot 已初始化
    And agent 流式过程中调用工具 "get_current_weather"
    When 用户 "123" 发送消息 "北京天气"
    Then 编辑过程中应出现工具调用提示
    And 最终消息应包含完整回复内容

  @unit
  Scenario: 大量 token 输出时仍能得到完整可用回复
    Given Telegram bot 已初始化
    And agent 流式快速返回大量 token
    When 用户 "123" 发送消息 "写一段话"
    Then 最终消息应包含完整回复内容
    And 最终消息不应是错误提示

  @unit
  Scenario: 流式异常时最终消息显示错误提示
    Given Telegram bot 已初始化
    And agent 流式过程中抛出异常
    When 用户 "123" 发送消息 "测试"
    Then 最终消息应包含错误提示

  @unit
  Scenario: 流式无任何输出时显示空回复错误
    Given Telegram bot 已初始化
    And agent 流式返回空内容
    When 用户 "123" 发送消息 "测试"
    Then 最终消息应包含空回复错误提示

  @unit
  Scenario: 长回复超过单条消息上限时仍能完整送达
    Given Telegram bot 已初始化
    And agent 流式返回超长内容
    When 用户 "123" 发送消息 "写一篇超长内容"
    Then 长回复应被完整送达
    And 最终消息不应是错误提示
