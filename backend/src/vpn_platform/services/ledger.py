from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from vpn_platform.db.models import LedgerEntry, TransactionStatus, WalletTransaction


@dataclass(frozen=True)
class LedgerPosting:
    account_code: str
    amount_minor: int
    wallet_id: uuid.UUID | None = None


class LedgerService:
    async def post(
        self,
        db: AsyncSession,
        *,
        kind: str,
        currency: str,
        reference_type: str,
        reference_id: uuid.UUID,
        postings: Sequence[LedgerPosting],
        metadata: Mapping[str, object] | None = None,
    ) -> WalletTransaction:
        if len(currency) != 3 or currency.upper() != currency:
            raise ValueError("currency must be a three-letter uppercase ISO code")
        if len(postings) < 2:
            raise ValueError("a ledger transaction requires at least two postings")
        if any(item.amount_minor == 0 for item in postings):
            raise ValueError("zero ledger postings are forbidden")
        if sum(item.amount_minor for item in postings) != 0:
            raise ValueError("ledger postings must balance to zero")

        transaction = WalletTransaction(
            kind=kind,
            status=TransactionStatus.POSTED,
            currency=currency,
            reference_type=reference_type,
            reference_id=reference_id,
            metadata_json=dict(metadata or {}),
            posted_at=datetime.now(UTC),
        )
        db.add(transaction)
        await db.flush()
        db.add_all(
            [
                LedgerEntry(
                    transaction_id=transaction.id,
                    account_code=posting.account_code,
                    wallet_id=posting.wallet_id,
                    amount_minor=posting.amount_minor,
                )
                for posting in postings
            ]
        )
        return transaction
