"""
Payments API — agent payment endpoints backed by Stripe + central ledger.

Routes:
  POST /payments/intent               — Create a PaymentIntent (returns client_secret)
  POST /payments/checkout             — Create a hosted Checkout Session
  POST /agents/{agent_id}/payments/one-off   — One-off payment for a specific agent
  POST /agents/{agent_id}/subscriptions      — Subscription for a specific agent
  GET  /agents/{agent_id}/balance            — Agent balance from ledger
  GET  /agents/{agent_id}/payments           — Agent payment history
  GET  /payments/summary                     — Global earnings summary
  GET  /payments/all-balances               — All agent balances
  GET  /payments/status                     — Stripe availability
"""
from __future__ import annotations

from typing import Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.stripe_service import stripe_service
from app.services.ledger_service import ledger_service

router = APIRouter(tags=["payments"])


# ── Request models ─────────────────────────────────────────────────────────────

class PaymentIntentRequest(BaseModel):
    amount_cents: int
    currency: str = "usd"
    description: str = ""
    agent_id: Optional[str] = None
    task_id: Optional[str] = None
    metadata: Optional[Dict[str, str]] = None


class CheckoutSessionRequest(BaseModel):
    price_id: str
    agent_id: Optional[str] = None
    task_id: Optional[str] = None
    success_url: str = "http://localhost:3000/payment/success"
    cancel_url: str = "http://localhost:3000/payment/cancel"
    mode: str = "payment"
    quantity: int = 1
    metadata: Optional[Dict[str, str]] = None


class OneOffPaymentRequest(BaseModel):
    amount_cents: int
    currency: str = "usd"
    description: str = ""
    task_id: Optional[str] = None
    metadata: Optional[Dict[str, str]] = None


class SubscriptionRequest(BaseModel):
    price_id: str
    customer_id: str
    metadata: Optional[Dict[str, str]] = None


class RecordPaymentRequest(BaseModel):
    amount_usd: float
    source: str = "manual"
    reference_id: Optional[str] = None
    description: str = ""
    payer_email: Optional[str] = None
    metadata: Optional[Dict[str, str]] = None


# ── Generic payment routes ─────────────────────────────────────────────────────

@router.get("/payments/status")
async def payments_status():
    return {
        "stripe_available": stripe_service.available,
        "ledger_available": True,
        "service": "Stripe + Central Ledger",
    }


@router.post("/payments/intent")
async def create_payment_intent(req: PaymentIntentRequest):
    result = await stripe_service.create_payment_intent(
        req.amount_cents,
        req.currency,
        agent_id=req.agent_id,
        task_id=req.task_id,
        description=req.description,
        metadata=req.metadata,
    )
    if not result.get("success"):
        raise HTTPException(status_code=503, detail=result.get("error", "Stripe error"))
    return result


@router.post("/payments/checkout")
async def create_checkout_session(req: CheckoutSessionRequest):
    result = await stripe_service.create_checkout_session(
        req.price_id,
        agent_id=req.agent_id,
        task_id=req.task_id,
        success_url=req.success_url,
        cancel_url=req.cancel_url,
        mode=req.mode,
        quantity=req.quantity,
        metadata=req.metadata,
    )
    if not result.get("success"):
        raise HTTPException(status_code=503, detail=result.get("error", "Stripe error"))
    return result


@router.get("/payments/summary")
async def payments_summary():
    return await ledger_service.get_earnings_summary()


@router.get("/payments/all-balances")
async def all_balances():
    return await ledger_service.get_all_balances()


@router.get("/payments/list")
async def list_payments(agent_id: Optional[str] = None, source: Optional[str] = None, limit: int = 50):
    return await ledger_service.list_payments(agent_id=agent_id, source=source, limit=limit)


# ── Agent-scoped routes ────────────────────────────────────────────────────────

@router.post("/agents/{agent_id}/payments/one-off")
async def agent_one_off_payment(agent_id: str, req: OneOffPaymentRequest):
    """
    Create a one-off PaymentIntent for an agent.
    Returns client_secret for frontend Stripe.js confirmation.
    """
    result = await stripe_service.create_payment_intent(
        req.amount_cents,
        req.currency,
        agent_id=agent_id,
        task_id=req.task_id,
        description=req.description,
        metadata=req.metadata,
    )
    if not result.get("success"):
        raise HTTPException(status_code=503, detail=result.get("error", "Stripe error"))
    return result


@router.post("/agents/{agent_id}/subscriptions")
async def agent_subscription(agent_id: str, req: SubscriptionRequest):
    """Create a recurring subscription for an agent."""
    result = await stripe_service.create_subscription(
        req.customer_id,
        req.price_id,
        agent_id=agent_id,
        metadata=req.metadata,
    )
    if not result.get("success"):
        raise HTTPException(status_code=503, detail=result.get("error", "Stripe error"))
    return result


@router.get("/agents/{agent_id}/balance")
async def agent_balance(agent_id: str):
    """Return the agent's current ledger balance."""
    return await ledger_service.get_balance(agent_id)


@router.get("/agents/{agent_id}/payments")
async def agent_payments(agent_id: str, limit: int = 50):
    """Return the agent's payment history."""
    return await ledger_service.list_payments(agent_id=agent_id, limit=limit)


@router.post("/agents/{agent_id}/payments/record")
async def record_agent_payment(agent_id: str, req: RecordPaymentRequest):
    """
    Manually record a payment (e.g. from an external marketplace) into the ledger.
    """
    result = await ledger_service.record_payment(
        agent_id,
        req.amount_usd,
        req.source,
        reference_id=req.reference_id,
        description=req.description,
        payer_email=req.payer_email,
        metadata=req.metadata,
    )
    if not result.get("success"):
        raise HTTPException(status_code=500, detail="Ledger error")
    return result
