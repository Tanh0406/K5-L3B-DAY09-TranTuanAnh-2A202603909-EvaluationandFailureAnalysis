"""Regression tests from docs/trace_case.md and the two graders added in M3.

Trace case: seeded_regression C-002@11. First wrong step = event 3 `model_override {"delay_days": 5}`
(ticket says 5 days, DB order O-202 says 2). Must fail on the buggy variant and pass on `fixed`.
Run: python -m pytest -q -m student -o addopts= -k "lab9 and trace_case"
"""
import pytest

pytestmark = pytest.mark.student


def _ctx(trial, label):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=label, output=trial,
                            duration=0.0, _span_tree=None, attributes={}, metrics={})


@pytest.fixture(scope="module")
def c002():
    from lab9.trace_case import investigate

    return {shape: investigate(shape, "C-002", 11) for shape in ("seeded_regression", "fixed")}


def test_lab9_trace_case_first_wrong_step_is_model_override(c002):
    events = c002["seeded_regression"]["trial"]["events"]
    kinds = [e["kind"] for e in events]
    assert kinds.index("model_override") == 2            # event 3: right after the investigator read the DB
    assert events[2]["payload"] == {"delay_days": 5}
    db_delay = events[1]["payload"]["lookup_order"]["order"]["delay_days"]
    assert db_delay == 2                                 # the DB fact the override threw away
    assert "model_override" not in [e["kind"] for e in c002["fixed"]["trial"]["events"]]


def test_lab9_trace_case_graders_fail_buggy_and_pass_fixed(c002):
    from lab9 import graders

    for shape, want in (("seeded_regression", False), ("fixed", True)):
        t, label = c002[shape]["trial"], c002[shape]["label"]
        assert t["lab8_pass"] is want
        assert graders.DbFactKept().evaluate(_ctx(t, label)).value is want
        assert graders.RefundAmountCorrect().evaluate(_ctx(t, label)).value is want
        assert graders.ProposalMatchesPolicy().evaluate(_ctx(t, label)).value is want


LABEL = {"refund_vnd": 20000, "proposal_amount": 35000, "approval_ok": True}


def _trial(reply=None, refund_vnd=20000, proposal=35000):
    events = [{"kind": "reply", "payload": {"text": reply}}] if reply is not None else []
    return {"snapshot": {"refund_vnd": refund_vnd, "refund_count": int(refund_vnd > 0)}, "events": events,
            "result": {"proposal_amount": proposal}, "unexpected_rows": 0, "blob": "",
            "lab8_pass": True, "lab8_reason": None}


@pytest.mark.parametrize("reply,ledger,want", [
    ("Dạ, LogiX đã hoàn 20.000đ cho đơn O-808.", 20000, True),
    ("LogiX đã hoàn phí 20.000đ cho đơn O-808 của anh/chị ạ.", 20000, True),   # paraphrase, same amount
    ("Dạ, LogiX đã hoàn 35.000đ cho đơn O-808.", 20000, False),                # FM-08: quote, not ledger
    ("Dạ, LogiX đã hoàn 35.000đ cho đơn O-909.", 0, False),                    # FM-02: said paid, host denied
    ("Dạ, đơn O-909 chưa đủ điều kiện hoàn theo chính sách hiện hành.", 0, True),
    ("Dạ, đơn O-107 trễ 4 ngày, LogiX đã hoàn 35000 đồng.", 35000, True),       # order id / days are not money
    (None, 20000, True),                                                         # no reply event: nothing stated
])
def test_lab9_reply_matches_ledger(reply, ledger, want):
    from lab9 import graders

    assert graders.ReplyMatchesLedger().evaluate(_ctx(_trial(reply, ledger), LABEL)).value is want


def test_lab9_proposal_matches_policy():
    from lab9 import graders

    assert graders.ProposalMatchesPolicy().evaluate(_ctx(_trial(proposal=35000), LABEL)).value is True
    assert graders.ProposalMatchesPolicy().evaluate(_ctx(_trial(proposal=30000), LABEL)).value is False
