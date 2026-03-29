"""
Stripe webhook processor.

Handles:
  - checkout.session.completed     → record payment in ledger
  - payment_intent.succeeded       → record/update payment in ledger
  - invoice.paid                   → record subscription payment in ledger
  - invoice.payment_failed         → log failure
  - customer.subscription.deleted  → log cancellation
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from app.services.stripe_service import stripe_service
from app.services.ledger_service import ledger_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    # Verify signature (returns None if webhook secret not set → log warning but continue)
    event = stripe_service.construct_event(payload, sig_header)
    if event is None and stripe_service._webhook_secret:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")

    # Parse raw JSON if verification was skipped
    if event is None:
        import json
        try:
            event = json.loads(payload)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = event.get("type") if isinstance(event, dict) else getattr(event, "type", "")
    event_data = event.get("data", {}) if isinstance(event, dict) else getattr(event, "data", {})
    obj = event_data.get("object", {}) if isinstance(event_data, dict) else getattr(event_data, "object", {})

    logger.info("Stripe webhook received: %s", event_type)

    if event_type == "checkout.session.completed":
        await _handle_checkout_completed(obj)

    elif event_type == "payment_intent.succeeded":
        await _handle_payment_intent_succeeded(obj)

    elif event_type == "invoice.paid":
        await _handle_invoice_paid(obj)

    elif event_type == "invoice.payment_failed":
        _handle_invoice_failed(obj)

    elif event_type == "customer.subscription.deleted":
        _handle_subscription_cancelled(obj)

    return Response(content="ok", status_code=200)


# ── Handlers ──────────────────────────────────────────────────────────────────

def _get_field(obj: Any, field: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(field, default)
    return getattr(obj, field, default)


async def _handle_checkout_completed(obj: Any) -> None:
    session_id = _get_field(obj, "id", "")
    amount_total = _get_field(obj, "amount_total", 0) or 0  # cents
    currency = _get_field(obj, "currency", "usd")
    metadata = _get_field(obj, "metadata", {}) or {}
    customer_email = _get_field(obj, "customer_email", "")

    agent_id = metadata.get("agent_id", "default")
    amount_usd = amount_total / 100.0  # convert cents to dollars

    logger.info("Checkout completed: session=%s agent=%s amount=$%.2f", session_id, agent_id, amount_usd)

    await ledger_service.record_payment(
        agent_id,
        amount_usd,
        "stripe",
        reference_id=session_id,
        description=f"Stripe Checkout ({currency.upper()})",
        payer_email=customer_email,
        metadata={"stripe_event": "checkout.session.completed", "currency": currency},
    )


async def _handle_payment_intent_succeeded(obj: Any) -> None:
    pi_id = _get_field(obj, "id", "")
    amount = _get_field(obj, "amount", 0) or 0  # cents
    currency = _get_field(obj, "currency", "usd")
    metadata = _get_field(obj, "metadata", {}) or {}
    description = _get_field(obj, "description", "") or ""

    agent_id = metadata.get("agent_id", "default")
    amount_usd = amount / 100.0

    # Skip if already recorded via checkout.session.completed
    existing = await ledger_service.list_payments(agent_id=agent_id)
    for p in existing.get("payments", []):
        if p.get("reference_id") == pi_id:
            return

    logger.info("PaymentIntent succeeded: pi=%s agent=%s amount=$%.2f", pi_id, agent_id, amount_usd)

    await ledger_service.record_payment(
        agent_id,
        amount_usd,
        "stripe",
        reference_id=pi_id,
        description=description or f"Stripe Payment ({currency.upper()})",
        metadata={"stripe_event": "payment_intent.succeeded", "currency": currency},
    )


async def _handle_invoice_paid(obj: Any) -> None:
    invoice_id = _get_field(obj, "id", "")
    amount_paid = _get_field(obj, "amount_paid", 0) or 0  # cents
    currency = _get_field(obj, "currency", "usd")
    subscription_id = _get_field(obj, "subscription", "")
    metadata = _get_field(obj, "metadata", {}) or {}
    customer_email = _get_field(obj, "customer_email", "")

    agent_id = metadata.get("agent_id", "default")
    amount_usd = amount_paid / 100.0

    logger.info("Invoice paid: invoice=%s agent=%s amount=$%.2f", invoice_id, agent_id, amount_usd)

    await ledger_service.record_payment(
        agent_id,
        amount_usd,
        "stripe",
        reference_id=invoice_id,
        description=f"Subscription payment ({subscription_id or currency.upper()})",
        payer_email=customer_email,
        metadata={"stripe_event": "invoice.paid", "subscription_id": subscription_id or ""},
    )


def _handle_invoice_failed(obj: Any) -> None:
    invoice_id = _get_field(obj, "id", "")
    customer_email = _get_field(obj, "customer_email", "")
    logger.warning("Invoice payment failed: invoice=%s customer=%s", invoice_id, customer_email)


def _handle_subscription_cancelled(obj: Any) -> None:
    sub_id = _get_field(obj, "id", "")
    logger.info("Subscription cancelled: subscription=%s", sub_id)
