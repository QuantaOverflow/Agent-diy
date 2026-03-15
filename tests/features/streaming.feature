Feature: 流式输出
  As a user
  I want the agent to stream responses token by token
  So that I can see progress in real time without waiting for the full reply

  @unit
  Scenario: agent graph 支持 stream_mode="messages" 流式调用
    Given a compiled agent graph
    When I call stream() with stream_mode "messages"
    Then the graph should yield message chunks

  @unit
  Scenario: CLI 逐 token 打印输出而非等待完整响应
    Given a mock streaming agent that yields tokens
    When the CLI processes the stream
    Then each token chunk should be printed immediately

  @unit
  Scenario: 工具调用时 CLI 打印工具状态行
    Given a mock streaming agent that calls a tool
    When the CLI processes the stream
    Then a tool status line should be printed before the final response

  @unit
  Scenario: 空流式输出返回空字符串
    Given a mock streaming agent with empty stream
    When the CLI processes the stream
    Then the streamed response should be empty

  @unit
  Scenario: 非 llm_call 节点 chunk 会被忽略
    Given a mock streaming agent that yields non-llm chunks
    When the CLI processes the stream
    Then non-llm chunks should be ignored

  @e2e
  Scenario Outline: 用户提问时 token 逐步到达
    Given a running streaming agent
    When I stream "<问题>"
    Then output tokens should arrive incrementally
    And the final response should be non-empty

    Examples:
      | 问题           |
      | 给我讲个笑话   |
      | 什么是量子纠缠 |

  @e2e
  Scenario: 工具调用时显示状态且回复含天气信息
    Given a running streaming agent
    When I stream "北京现在天气怎么样"
    Then a tool status line should appear in the output
    And the response should contain weather information
