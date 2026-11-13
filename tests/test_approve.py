import pytest

from engine.approve import Approval, Decision


def test_rejection_requires_reason() -> None:
    with pytest.raises(ValueError, match="reason"):
        Approval(draft_id="d1", decision=Decision.REJECTED, reviewer="mohamed")


def test_approval_requires_reviewer() -> None:
    with pytest.raises(ValueError, match="reviewer"):
        Approval(draft_id="d1", decision=Decision.APPROVED, reviewer=" ")


def test_valid_approval() -> None:
    ok = Approval(draft_id="d1", decision=Decision.APPROVED, reviewer="mohamed")
    assert ok.decision is Decision.APPROVED
