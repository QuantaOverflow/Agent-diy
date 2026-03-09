Feature: Multi-turn conversation
  As a user
  I want to have a multi-turn conversation with the agent
  So that the agent remembers context from earlier messages

  Scenario: Agent remembers user's name across turns
    Given an agent with memory
    When I say "Hi, my name is Alice"
    And I receive a response
    And I say "What is my name?"
    Then the response should mention "Alice"

  Scenario: Separate conversations are isolated
    Given an agent with memory
    When I start a conversation with thread "t1" saying "My name is Bob"
    And I start a conversation with thread "t2" saying "What is my name?"
    Then the response for thread "t2" should not mention "Bob"
