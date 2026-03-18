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

  @unit
  Scenario: 编辑消息遇到 Telegram 限流时仍能给出可用最终回复
    Given Telegram bot 已初始化
    And agent 流式快速返回大量 token
    And Telegram 编辑消息会触发一次限流
    When 用户 "123" 发送消息 "继续"
    Then 最终消息应包含完整回复内容
    And 最终消息不应是错误提示

  @unit
  Scenario: 上游仅返回一次性完整文本时仍应成功回复
    Given Telegram bot 已初始化
    And agent 仅返回一次性完整文本
    When 用户 "123" 发送消息 "fallback"
    Then 最终消息应包含完整回复内容
    And 最终消息不应是错误提示

  # ─── 组件集成层：验证 parse_stream_chunk 解析逻辑 ─────────────────────

  @unit
  Scenario Outline: parse_stream_chunk 正确解析 LangGraph stream chunk
    Given 一个 langgraph_node 为 "<node>" 的 stream chunk，类型为 "<chunk_type>"
    When 解析该 chunk
    Then 解析结果应为 "<event_type>" 事件，内容为 "<content>"

    Examples:
      | node     | chunk_type | event_type | content            |
      | llm_call | token      | token      | 你好               |
      | llm_call | tool_call  | tool_call  | get_current_weather |

  @unit
  Scenario Outline: parse_stream_chunk 忽略非 llm_call 节点或空内容
    Given 一个 langgraph_node 为 "<node>" 的 stream chunk，类型为 "<chunk_type>"
    When 解析该 chunk
    Then 解析结果应为 None

    Examples:
      | node  | chunk_type    |
      | tools | token         |
      | other | token         |
      | llm_call | empty_content |

  # ─── 组件集成层：验证 InProcessAgentBackend.stream_reply Queue 桥接 ───

  @unit
  Scenario: InProcessAgentBackend 将 agent stream 转换为 StreamEvent 序列
    Given 一个 mock agent 的 stream 返回 token 和工具调用 chunks
    When 通过 InProcessAgentBackend 调用 stream_reply
    Then 应依次产出 tool_call 和 token 类型的 StreamEvent

  @unit
  Scenario: InProcessAgentBackend 正确传递 agent stream 中的异常
    Given 一个 mock agent 的 stream 过程中抛出异常
    When 通过 InProcessAgentBackend 调用 stream_reply
    Then stream_reply 应抛出该异常

  @unit
  Scenario: InProcessAgentBackend 处理空 stream
    Given 一个 mock agent 的 stream 返回空序列
    When 通过 InProcessAgentBackend 调用 stream_reply
    Then stream_reply 应产出零个事件

  # ─── 全链路集成：mock agent.stream → InProcessAgentBackend → Telegram ─

  @unit
  Scenario: 全链路：mock agent stream 经 InProcessAgentBackend 到 Telegram 编辑消息
    Given Telegram bot 使用 InProcessAgentBackend 和可流式的 mock agent
    When 用户 "456" 通过 Telegram 发送消息 "集成测试"
    Then bot 应先发送占位消息
    And bot 应编辑该消息至少一次
    And 最终消息应包含 mock agent 的完整输出
