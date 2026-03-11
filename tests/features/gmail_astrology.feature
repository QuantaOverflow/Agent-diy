Feature: Gmail astrology digest
  As a user
  I want the agent to read and summarize my daily astrology subscription email
  So that I get astrological insights in Chinese without opening my inbox

  The email comes from authority-astrology@mail.beehiiv.com and contains:
  - Today's Horoscope: current planetary event overview
  - Cosmic Musings: deeper cosmic energy interpretation
  - Today's Affirmation: a short affirmation quote

  Background:
    Given Gmail credentials are configured

  @e2e
  Scenario Outline: Agent summarizes today's astrology email in Chinese
    Given a running agent
    When I ask "<question>"
    Then the response should contain astrology content
    And the response should be in Chinese
    And the response should indicate which date the email is from

    Examples:
      | question                   |
      | 今天的星座运势怎么样       |
      | 给我总结一下今天的星座邮件 |

  @e2e
  Scenario: Agent answers about a specific section of the email
    Given a running agent
    When I ask "今天的星座格言是什么"
    Then the response should contain astrology content
    And the response should be in Chinese

  @e2e
  Scenario: Non-astrology question does not trigger email reading
    Given a running agent
    When I ask "你好"
    Then the response should not contain astrology content

  @e2e
  Scenario: Agent fetches astrology email for a specified past date
    Given a running agent
    When I ask "昨日星座运势"
    Then the response should contain astrology content
    And the response should be in Chinese
    And the response should indicate which date the email is from

  @e2e
  Scenario: Agent informs user when no email exists for the requested date
    Given a running agent
    When I ask "2024年1月1日的星座运势"
    Then the response should inform that no email was found for that date

  @unit
  Scenario: Tool extracts all three sections from a well-formed email body
    Given an email body containing all three astrology sections
    When the tool parses the email body
    Then the horoscope section should not be empty
    And the cosmic musings section should not be empty
    And the affirmation section should not be empty

  @unit
  Scenario: Tool returns unavailable when credentials are missing
    Given Gmail credentials are not configured
    When I call the astrology email tool
    Then the tool result should indicate service unavailable

  @unit
  Scenario: Tool returns not-found when no email exists for the given date
    Given Gmail returns no emails for the requested date
    When I call the astrology email tool with date "2024-01-01"
    Then the tool result should indicate no email was found for that date
