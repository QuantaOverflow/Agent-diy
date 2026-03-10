Feature: Weather query
  As a user
  I want to ask the agent about the weather
  So that I get real-time weather information for a city

  @e2e
  Scenario Outline: Agent returns weather for a specified city
    Given a running agent
    When I ask "<question>"
    Then the response should contain weather information

    Examples:
      | question             |
      | 北京天气怎么样       |
      | 天津天气如何         |
      | 上海今天什么天气     |

  @e2e
  Scenario: Agent defaults to Beijing when no city specified
    Given a running agent
    When I ask "今天天气怎么样"
    Then the response should contain weather information
    And the response should mention "北京"

  @e2e
  Scenario Outline: Agent returns weather forecast for future time
    Given a running agent
    When I ask "<question>"
    Then the response should contain weather forecast information
    And the response should not be a guess from current weather

    Examples:
      | question                 |
      | 今晚天气如何             |
      | 明天北京天气怎么样       |
      | 后天上海什么天气         |

  @e2e
  Scenario: Non-weather question does not trigger weather query
    Given a running agent
    When I ask "你好"
    Then the response should not contain weather information
