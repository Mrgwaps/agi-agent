"""
Central ledger service — maintains the canonical agent balance and payment
history by reconciling events from Stripe and virtual marketplaces.

Storage: Redis for fast balance reads + in-process list for MVP.
In production this should be replaced with the PostgreSQL `payments` and
`agent_balances` tables via SQLAlchemy.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# In-memory store for MVP (replace with DB in production)
_payments: List[Dict[str, Any]] = []
_balances: Dict[str, float] = {}  # agent_id → total USD

_lock = asyncio.Lock()


class LedgerService:
    """
    Thin ledger that tracks payments received by agents.

    All amounts are stored in USD (float).  Sources:
    - stripe        — real Stripe PaymentIntent / Invoice payments
    - etsy          — Etsy order reconciliation (read-only)
    - fiverr        — Fiverr order reconciliation (read-only)
    - upwork        — Upwork milestone payments (read-only)
    - mturk         — MTurk HIT payments (read-only)
    - manual        — Manually recorded payments
    """

    # ── Record keeping ─────────────────────────────────────────────────────────

    async def record_payment(
        self,
        agent_id: str,
        amount_usd: float,
        source: str,
        *,
        reference_id: Optional[str] = None,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        payer_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Record an incoming payment and update the agent's balance.

        Args:
            agent_id:     The agent that received the payment.
            amount_usd:   Amount in US dollars.
            source:       Payment source: 'stripe' | 'etsy' | 'fiverr' | 'upwork' | 'mturk' | 'manual'.
            reference_id: External ID (Stripe PaymentIntent id, order id, …).
            description:  Human-readable description.
            metadata:     Arbitrary metadata.
        """
        payment: Dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "agent_id": agent_id,
            "amount_usd": amount_usd,
            "source": source,
            "reference_id": reference_id,
            "description": description,
            "payer_email": payer_email,
            "metadata": metadata or {},
            "created_at": time.time(),
        }
        async with _lock:
            _payments.append(payment)
            _balances[agent_id] = _balances.get(agent_id, 0.0) + amount_usd

        logger.info(
            "Ledger: recorded $%.4f from %s for agent %s (ref=%s)",
            amount_usd,
            source,
            agent_id,
            reference_id,
        )
        return {"success": True, "payment_id": payment["id"], "new_balance_usd": _balances[agent_id]}

    # ── Queries ────────────────────────────────────────────────────────────────

    async def get_balance(self, agent_id: str) -> Dict[str, Any]:
        """Return the current balance for an agent."""
        balance = _balances.get(agent_id, 0.0)
        return {"success": True, "agent_id": agent_id, "balance_usd": round(balance, 4)}

    async def get_all_balances(self) -> Dict[str, Any]:
        """Return balances for all agents."""
        return {
            "success": True,
            "balances": [
                {"agent_id": aid, "balance_usd": round(bal, 4)}
                for aid, bal in _balances.items()
            ],
            "total_usd": round(sum(_balances.values()), 4),
        }

    async def list_payments(
        self,
        *,
        agent_id: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """List payments, optionally filtered by agent or source."""
        result = _payments.copy()
        if agent_id:
            result = [p for p in result if p["agent_id"] == agent_id]
        if source:
            result = [p for p in result if p["source"] == source]
        result.sort(key=lambda p: p["created_at"], reverse=True)
        return {
            "success": True,
            "payments": result[:limit],
            "total_count": len(result),
        }

    async def get_earnings_summary(self, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Return an earnings summary suitable for the dashboard EarningsCard.
        """
        payments = _payments.copy()
        if agent_id:
            payments = [p for p in payments if p["agent_id"] == agent_id]

        total = sum(p["amount_usd"] for p in payments)
        by_source: Dict[str, float] = {}
        for p in payments:
            by_source[p["source"]] = by_source.get(p["source"], 0.0) + p["amount_usd"]

        # Recent 24h
        cutoff = time.time() - 86400
        recent_24h = sum(p["amount_usd"] for p in payments if p["created_at"] >= cutoff)

        # Recent 7d
        cutoff_7d = time.time() - 7 * 86400
        recent_7d = sum(p["amount_usd"] for p in payments if p["created_at"] >= cutoff_7d)

        return {
            "success": True,
            "total_usd": round(total, 4),
            "recent_24h_usd": round(recent_24h, 4),
            "recent_7d_usd": round(recent_7d, 4),
            "by_source": {k: round(v, 4) for k, v in by_source.items()},
            "payment_count": len(payments),
            "last_payment": max((p["created_at"] for p in payments), default=None),
        }

    # ── Marketplace reconciliation stubs ──────────────────────────────────────

    async def reconcile_etsy(self, agent_id: str, orders: List[Dict]) -> Dict[str, Any]:
        """
        Reconcile Etsy orders into the ledger (read-only import).
        Each order: {order_id, amount_usd, description, created_at}
        """
        recorded = 0
        for order in orders:
            ref = order.get("order_id") or order.get("id")
            # Skip if already recorded
            existing = [p for p in _payments if p["reference_id"] == ref and p["source"] == "etsy"]
            if existing:
                continue
            await self.record_payment(
                agent_id,
                float(order.get("amount_usd", 0)),
                "etsy",
                reference_id=ref,
                description=order.get("description", "Etsy order"),
            )
            recorded += 1
        return {"success": True, "reconciled": recorded}

    async def reconcile_fiverr(self, agent_id: str, orders: List[Dict]) -> Dict[str, Any]:
        recorded = 0
        for order in orders:
            ref = order.get("order_id") or order.get("id")
            existing = [p for p in _payments if p["reference_id"] == ref and p["source"] == "fiverr"]
            if existing:
                continue
            await self.record_payment(
                agent_id,
                float(order.get("amount_usd", 0)),
                "fiverr",
                reference_id=ref,
                description=order.get("description", "Fiverr order"),
            )
            recorded += 1
        return {"success": True, "reconciled": recorded}

    async def reconcile_upwork(self, agent_id: str, contracts: List[Dict]) -> Dict[str, Any]:
        recorded = 0
        for contract in contracts:
            ref = contract.get("contract_id") or contract.get("id")
            existing = [p for p in _payments if p["reference_id"] == ref and p["source"] == "upwork"]
            if existing:
                continue
            await self.record_payment(
                agent_id,
                float(contract.get("amount_usd", 0)),
                "upwork",
                reference_id=ref,
                description=contract.get("description", "Upwork milestone"),
            )
            recorded += 1
        return {"success": True, "reconciled": recorded}


# Singleton
ledger_service = LedgerService()
