"""Provider/account routing primitives for AI workloads.

This module deliberately does not depend on provider SDKs.  It selects an
already-authorized account/project; the consuming service owns the actual
Gemini/Claude/Codex transport and credentials.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class AccountState(str, Enum):
    ACTIVE = "active"
    READY = "ready"
    DEGRADED = "degraded"
    EXHAUSTED = "exhausted"
    DISABLED = "disabled"
    COOLDOWN = "cooldown"


@dataclass(frozen=True, slots=True)
class ProviderAccount:
    id: str
    provider: str
    project_id: str | None = None
    location: str | None = None
    priority: int = 100
    budget_usd: float | None = None
    reserve_usd: float = 0.0
    enabled: bool = True
    state: AccountState = AccountState.READY

    def can_accept(self, spent_usd: float = 0.0) -> bool:
        if not self.enabled or self.state in {
            AccountState.DISABLED,
            AccountState.EXHAUSTED,
            AccountState.COOLDOWN,
        }:
            return False
        if self.budget_usd is None:
            return True
        return spent_usd < max(0.0, self.budget_usd - self.reserve_usd)


class ProviderAccountPool:
    """Deterministic, budget-aware selection of authorized provider accounts."""

    def __init__(self, accounts: Iterable[ProviderAccount]) -> None:
        self._accounts = {account.id: account for account in accounts}

    def list(self, provider: str | None = None) -> list[ProviderAccount]:
        accounts = self._accounts.values()
        if provider:
            accounts = (a for a in accounts if a.provider == provider)
        return sorted(accounts, key=lambda a: (a.priority, a.id))

    def select(
        self,
        provider: str,
        *,
        spent_by_account: dict[str, float] | None = None,
        preferred_account: str | None = None,
    ) -> ProviderAccount:
        spent_by_account = spent_by_account or {}
        candidates = [
            account
            for account in self.list(provider)
            if account.can_accept(spent_by_account.get(account.id, 0.0))
        ]
        if preferred_account:
            candidates.sort(key=lambda a: (a.id != preferred_account, a.priority, a.id))
        if not candidates:
            raise LookupError(f"No healthy/budget-eligible account for provider={provider!r}")
        return candidates[0]

    def with_state(self, account_id: str, state: AccountState) -> None:
        account = self._accounts.get(account_id)
        if account is None:
            raise KeyError(account_id)
        self._accounts[account_id] = ProviderAccount(
            **{**account.__dict__, "state": state}
        )

    def disable(self, account_id: str) -> None:
        account = self._accounts.get(account_id)
        if account is None:
            raise KeyError(account_id)
        self._accounts[account_id] = ProviderAccount(
            id=account.id,
            provider=account.provider,
            project_id=account.project_id,
            location=account.location,
            priority=account.priority,
            budget_usd=account.budget_usd,
            reserve_usd=account.reserve_usd,
            enabled=False,
            state=AccountState.DISABLED,
        )
