import json

from app.copilot import FALLBACK_REPLY, Copilot
from app.llm import LLMResponse, ScriptedLLM, ToolCall


def make_copilot(settings, registry, responses):
    llm = ScriptedLLM(responses)
    return Copilot(llm, registry, settings), llm


def test_plain_answer_without_tools(settings, registry, alice_ctx, alice):
    copilot, llm = make_copilot(settings, registry, [LLMResponse("Hello!")])
    result = copilot.respond(alice_ctx, alice, [], "hi")
    assert result.reply == "Hello!"
    assert result.trace == []
    assert [m["role"] for m in result.new_messages] == ["user", "assistant"]


def test_system_prompt_names_only_the_signed_in_customer(settings, registry, alice_ctx, alice, bob):
    copilot, llm = make_copilot(settings, registry, [LLMResponse("ok")])
    copilot.respond(alice_ctx, alice, [], "hi")
    system = llm.requests[0][0]
    assert system["role"] == "system"
    assert alice.customer_number in system["content"]
    assert bob.customer_number not in system["content"]
    assert "$3,000.00" in system["content"]


def test_tool_result_is_fed_back_to_the_model(settings, registry, alice_ctx, alice):
    copilot, llm = make_copilot(
        settings,
        registry,
        [LLMResponse("", [ToolCall("get_accounts", {})]), LLMResponse("You have accounts.")],
    )
    result = copilot.respond(alice_ctx, alice, [], "what accounts do I have?")

    assert result.reply == "You have accounts."
    assert [step.name for step in result.trace] == ["get_accounts"]
    second_request = llm.requests[1]
    tool_message = second_request[-1]
    assert tool_message["role"] == "tool"
    assert tool_message["tool_name"] == "get_accounts"
    numbers = {a["account_number"] for a in json.loads(tool_message["content"])["accounts"]}
    assert numbers == {a.account_number for a in alice.accounts}
    assert second_request[-2]["tool_calls"][0]["function"]["name"] == "get_accounts"


def test_bad_tool_call_returns_error_and_conversation_continues(
    settings, registry, alice_ctx, alice
):
    copilot, _ = make_copilot(
        settings,
        registry,
        [LLMResponse("", [ToolCall("no_such_tool", {})]), LLMResponse("Sorry about that.")],
    )
    result = copilot.respond(alice_ctx, alice, [], "do something")
    assert "Unknown tool" in result.trace[0].result["error"]
    assert result.reply == "Sorry about that."


def test_stops_after_max_tool_rounds(settings, registry, alice_ctx, alice):
    looping = [LLMResponse("", [ToolCall("get_accounts", {})])] * settings.max_tool_rounds
    copilot, llm = make_copilot(settings, registry, looping)
    result = copilot.respond(alice_ctx, alice, [], "loop forever")
    assert result.truncated
    assert result.reply == FALLBACK_REPLY
    assert len(llm.requests) == settings.max_tool_rounds


def test_history_is_passed_through_and_not_mutated(settings, registry, alice_ctx, alice):
    history = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "yes"}]
    copilot, llm = make_copilot(settings, registry, [LLMResponse("ok")])
    copilot.respond(alice_ctx, alice, history, "now")
    assert [m["content"] for m in llm.requests[0][1:]] == ["earlier", "yes", "now"]
    assert len(history) == 2
