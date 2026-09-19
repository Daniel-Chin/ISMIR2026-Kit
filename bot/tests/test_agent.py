"""Agent loop tests with a scripted fake Anthropic client."""

from types import SimpleNamespace

from worker import agent

PAYLOAD = {"text": "papers on dynamic time warping?", "user_id": "U1"}


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def tool_use_block(name, args, block_id="tu_1"):
    return SimpleNamespace(type="tool_use", name=name, input=args, id=block_id)


class FakeClient:
    """Returns scripted responses in order; records requests."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []
        self.messages = self  # client.messages.create(...)

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(content=self._responses.pop(0))


GOOD_ANSWER = (
    "*<https://example.org/poster_4.html|Reformulating Soft DTW>* "
    "(based on the abstract) — discuss in <#C0AAA>."
)


def test_tool_loop_then_grounded_answer(snapshot):
    client = FakeClient(
        [
            [tool_use_block("search_papers", {"query": "dtw", "k": 3, "item_type": None})],
            [text_block(GOOD_ANSWER)],
        ]
    )
    result = agent.answer(PAYLOAD, snapshot, client=client)
    assert result == GOOD_ANSWER
    # second request carried the tool result wrapped as data
    tool_result = client.requests[1]["messages"][2]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert "<catalogue_data>" in tool_result["content"]


def test_ungrounded_answer_retried_then_accepted(snapshot):
    client = FakeClient(
        [
            [tool_use_block("search_papers", {"query": "dtw", "k": 3, "item_type": None})],
            [text_block("It's a great paper, no links needed.")],  # fails grounding
            [text_block(GOOD_ANSWER)],  # corrective retry
        ]
    )
    assert agent.answer(PAYLOAD, snapshot, client=client) == GOOD_ANSWER
    corrective = client.requests[2]["messages"][-1]["content"]
    assert "failed validation" in corrective


def test_grounding_failure_twice_falls_back(snapshot):
    client = FakeClient(
        [
            [tool_use_block("search_papers", {"query": "dtw", "k": 3, "item_type": None})],
            [text_block("no links 1")],
            [text_block("no links 2")],
        ]
    )
    assert agent.answer(PAYLOAD, snapshot, client=client) == agent.NOT_FOUND


def test_tool_rounds_capped(snapshot):
    looping = [tool_use_block("search_papers", {"query": "x", "k": 3, "item_type": None})]
    client = FakeClient(
        [
            looping,
            looping,
            looping,
            [text_block(GOOD_ANSWER)],  # forced final at the cap
        ]
    )
    assert agent.answer(PAYLOAD, snapshot, client=client) == GOOD_ANSWER
    assert len(client.requests) == 4  # 3 tool rounds + final
