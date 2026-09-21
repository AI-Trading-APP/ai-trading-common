from ai_trading_common.provider_routing import (
    AccountState,
    ProviderAccount,
    ProviderAccountPool,
)


def test_selects_lowest_priority_eligible_account():
    pool = ProviderAccountPool(
        [
            ProviderAccount("gcp-02", "gemini", priority=2),
            ProviderAccount("gcp-01", "gemini", priority=1),
        ]
    )
    assert pool.select("gemini").id == "gcp-01"


def test_reserve_causes_failover_to_next_account():
    pool = ProviderAccountPool(
        [
            ProviderAccount("gcp-01", "gemini", priority=1, budget_usd=300, reserve_usd=25),
            ProviderAccount("gcp-02", "gemini", priority=2, budget_usd=300, reserve_usd=25),
        ]
    )
    assert pool.select("gemini", spent_by_account={"gcp-01": 275}).id == "gcp-02"


def test_exhausted_account_is_skipped():
    pool = ProviderAccountPool(
        [
            ProviderAccount("gcp-01", "gemini", priority=1, state=AccountState.EXHAUSTED),
            ProviderAccount("gcp-02", "gemini", priority=2),
        ]
    )
    assert pool.select("gemini").id == "gcp-02"


def test_state_transition_and_disable():
    pool = ProviderAccountPool([ProviderAccount("gcp-01", "gemini")])
    pool.with_state("gcp-01", AccountState.EXHAUSTED)
    assert pool.list()[0].state == AccountState.EXHAUSTED
    pool.disable("gcp-01")
    assert not pool.list()[0].enabled


def test_no_eligible_account_raises():
    pool = ProviderAccountPool([ProviderAccount("gcp-01", "gemini", enabled=False)])
    try:
        pool.select("gemini")
    except LookupError as exc:
        assert "gemini" in str(exc)
    else:
        raise AssertionError("expected LookupError")
