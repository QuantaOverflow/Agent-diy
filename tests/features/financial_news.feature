Feature: Financial news integration
  As a user
  I want the agent to retrieve A-share financial news when I ask about stocks or markets
  So that I get up-to-date market insights beyond the LLM's training data

  @integration
  Scenario Outline: Agent queries financial news for market topics
    Given a running agent
    When I ask "<question>"
    Then the agent should have queried financial news
    And the response should contain relevant market information

    Examples:
      | question                          |
      | 最近A股市场有什么热点              |
      | 新能源板块最近表现怎么样           |
      | 人工智能概念股最近有什么消息       |

  @integration
  Scenario Outline: Agent retrieves comprehensive information for specific stock queries
    Given a running agent
    When I ask "<question>"
    Then the response should contain relevant stock information

    Examples:
      | question                        |
      | 贵州茅台最近表现怎么样          |
      | 帮我看看比亚迪的最新消息        |
      | 宁德时代最近有什么新闻          |

  @integration
  Scenario Outline: Agent does not query financial news for non-financial questions
    Given a running agent
    When I ask "<question>"
    Then the agent should not have queried financial news

    Examples:
      | question             |
      | 今天天气怎么样       |
      | 帮我写一首诗         |
      | 股票是什么           |
      | 巴菲特是谁           |

  @integration
  Scenario: Agent degrades gracefully when financial news service is unavailable
    Given a running agent with unavailable financial news service
    When I ask "最近股市有什么热点"
    Then the response should not be an error message
    And the response should indicate limited information availability

  @unit
  Scenario Outline: Stock news tool returns structured results for valid symbol
    Given a financial news tool
    When I query stock news for symbol "<symbol>"
    Then the result should contain a list of news items
    And each item should have a title and publish time

    Examples:
      | symbol      |
      | 600519      |
      | 603516.SH   |

  @unit
  Scenario: Semantic search returns up to default limit results
    Given a financial news tool
    When I search for topic "新能源"
    Then the result should contain at most 15 news items

  @unit
  Scenario: Combined query merges and deduplicates results from both sources
    Given a financial news tool
    When I query both stock news and semantic search for ticker "600519" and topic "茅台"
    Then the result should contain news from both sources
    And duplicate news items should appear only once

  @unit
  Scenario: Company name is resolved to ticker before querying stock news
    Given a financial news tool
    When I query stock news for company name "贵州茅台"
    Then the tool should resolve the ticker to "600519"
    And the result should contain stock news for "600519"

  @unit
  Scenario Outline: Tools return empty result when backend is unavailable
    Given a financial news tool with unavailable backend
    When I call "<tool>" with "<param>"
    Then the result should be empty without raising an exception

    Examples:
      | tool            | param  |
      | stock_news      | 600519 |
      | semantic_search | 新能源 |
      | hot_news        |        |
      | lookup          | 茅台   |

  @unit
  Scenario: Stock news tool returns empty when company name has no matching ticker
    Given a financial news tool
    When I query stock news for company name "不存在的公司XYZ"
    Then the result should return an empty news list without error

  @unit
  Scenario Outline: Stock news tool handles invalid symbol gracefully
    Given a financial news tool
    When I query stock news for symbol "<symbol>"
    Then the result should return an empty news list without error

    Examples:
      | symbol  |
      |         |
      | INVALID |

  @unit
  Scenario: Stock news tool accepts symbol alias from model tool call
    Given a financial news tool
    When I query stock news with symbol "603516"
    Then the request should use ticker "603516"
    And the result should contain a list of news items

  @unit
  Scenario: Tools parse list payload from results envelope
    Given a financial news tool
    When stock news backend returns a wrapped results payload
    Then the parsed result should contain a list of news items

  @unit
  Scenario: Empty financial news base url falls back to localhost
    Given FINANCIAL_NEWS_BASE_URL is empty
    When I read financial news base url
    Then the base url should be "http://localhost:8000"

  @unit
  Scenario: Financial news HTTP client ignores proxy environment
    Given a financial news tool
    When I query stock news with ticker "603516" and capture client options
    Then the HTTP client should set trust_env to false
