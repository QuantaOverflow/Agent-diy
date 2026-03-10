Feature: Web search
  As a user
  I want the agent to search the web when needed
  So that I get accurate and up-to-date information

  @e2e
  Scenario Outline: Agent searches for real-time information
    Given a running agent
    When I ask "<question>"
    Then the agent should have searched the web
    And the response should be relevant to the topic

    Examples:
      | question             |
      | 最近有什么科技新闻   |
      | 现在黄金价格是多少   |
      | 2026年春节是哪天     |

  @e2e
  Scenario Outline: Agent searches when user explicitly requests
    Given a running agent
    When I ask "<question>"
    Then the agent should have searched the web
    And the response should be relevant to the topic

    Examples:
      | question                       |
      | 帮我搜一下最新的 iPhone 价格   |
      | 查一下今天的油价               |
      | 帮我搜一下北京的天气           |

  @e2e
  Scenario Outline: Agent does not search for casual or knowledge questions
    Given a running agent
    When I ask "<question>"
    Then the agent should not have searched the web

    Examples:
      | question               |
      | 你好                   |
      | 帮我写一首关于春天的诗 |
      | 1加1等于几             |

  @e2e
  Scenario: Agent falls back to knowledge when search service is unavailable
    Given a running agent with unavailable search service
    When I ask "最近有什么新闻"
    Then the response should not be an error message
