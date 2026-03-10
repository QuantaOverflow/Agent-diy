Feature: Time query
  As a user
  I want to ask the agent for the current time
  So that I get an accurate answer in China timezone

  @e2e
  Scenario Outline: Agent answers time queries in various phrasings
    Given a running agent
    When I ask "<question>"
    Then the response should contain the current hour in China timezone

    Examples:
      | question         |
      | 现在几点了       |
      | 当前时间是多少   |
      | what time is it  |
      | 几点了           |

  @e2e
  Scenario: Non-time question does not return time
    Given a running agent
    When I ask "你好"
    Then the response should not contain a time string
