"""
Stripe payment service — wraps the Stripe Python SDK for one-off payments,
subscriptions, and agent balance management.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)


class StripeService:
    """
    Thin wrapper around the Stripe SDK.  All methods return a consistent
    `{success, error?, ...}` dict so callers never need to catch SDK exceptions.
    """

    def __init__(self) -> None:
        self._secret_key = getattr(settings, "stripe_secret_key", "")
        self._webhook_secret = getattr(settings, "stripe_webhook_secret", "")
        self._client: Optional[Any] = None

    @property
    def available(self) -> bool:
        return bool(self._secret_key)

    def _get_stripe(self):
        """Lazy-import stripe and configure key."""
        if self._client is not None:
            return self._client
        try:
            import stripe as _stripe  # type: ignore
            _stripe.api_key = self._secret_key
            self._client = _stripe
            return _stripe
        except ImportError:
            raise RuntimeError("stripe package is not installed. Run: pip install stripe")

    # ── Products & Prices ─────────────────────────────────────────────────────

    async def create_product(self, name: str, description: str = "") -> Dict[str, Any]:
        if not self.available:
            return {"success": False, "error": "Stripe key not configured"}
        try:
            stripe = self._get_stripe()
            product = stripe.Product.create(name=name, description=description)
            return {"success": True, "product_id": product.id, "raw": dict(product)}
        except Exception as exc:
            logger.error("Stripe create_product failed: %s", exc)
            return {"success": False, "error": str(exc)}

    async def create_price(
        self,
        product_id: str,
        amount_cents: int,
        currency: str = "usd",
        *,
        recurring_interval: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a Price.  Pass recurring_interval='month'/'year' for subscriptions.
        """
        if not self.available:
            return {"success": False, "error": "Stripe key not configured"}
        try:
            stripe = self._get_stripe()
            kwargs: Dict[str, Any] = {
                "product": product_id,
                "unit_amount": amount_cents,
                "currency": currency,
            }
            if recurring_interval:
                kwargs["recurring"] = {"interval": recurring_interval}
            price = stripe.Price.create(**kwargs)
            return {"success": True, "price_id": price.id, "raw": dict(price)}
        except Exception as exc:
            logger.error("Stripe create_price failed: %s", exc)
            return {"success": False, "error": str(exc)}

    # ── One-off payments (PaymentIntent) ─────────────────────────────────────

    async def create_payment_intent(
        self,
        amount_cents: int,
        currency: str = "usd",
        *,
        agent_id: Optional[str] = None,
        task_id: Optional[str] = None,
        description: str = "",
        metadata: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Create a Stripe PaymentIntent.  Returns client_secret for frontend
        confirmation.
        """
        if not self.available:
            return {"success": False, "error": "Stripe key not configured"}
        try:
            stripe = self._get_stripe()
            meta = metadata or {}
            if agent_id:
                meta["agent_id"] = agent_id
            if task_id:
                meta["task_id"] = task_id
            intent = stripe.PaymentIntent.create(
                amount=amount_cents,
                currency=currency,
                description=description,
                metadata=meta,
                automatic_payment_methods={"enabled": True},
            )
            return {
                "success": True,
                "payment_intent_id": intent.id,
                "client_secret": intent.client_secret,
                "amount_cents": amount_cents,
                "currency": currency,
                "status": intent.status,
            }
        except Exception as exc:
            logger.error("Stripe create_payment_intent failed: %s", exc)
            return {"success": False, "error": str(exc)}

    # ── Checkout Sessions ─────────────────────────────────────────────────────

    async def create_checkout_session(
        self,
        price_id: str,
        *,
        agent_id: Optional[str] = None,
        task_id: Optional[str] = None,
        success_url: str = "http://localhost:3000/payment/success",
        cancel_url: str = "http://localhost:3000/payment/cancel",
        mode: str = "payment",
        quantity: int = 1,
        metadata: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Create a hosted Checkout Session.  mode='payment' | 'subscription'.
        Returns the URL to redirect the customer to.
        """
        if not self.available:
            return {"success": False, "error": "Stripe key not configured"}
        try:
            stripe = self._get_stripe()
            meta = metadata or {}
            if agent_id:
                meta["agent_id"] = agent_id
            if task_id:
                meta["task_id"] = task_id
            session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[{"price": price_id, "quantity": quantity}],
                mode=mode,
                success_url=success_url,
                cancel_url=cancel_url,
                metadata=meta,
            )
            return {
                "success": True,
                "session_id": session.id,
                "checkout_url": session.url,
                "mode": mode,
            }
        except Exception as exc:
            logger.error("Stripe create_checkout_session failed: %s", exc)
            return {"success": False, "error": str(exc)}

    # ── Subscriptions ─────────────────────────────────────────────────────────

    async def create_subscription(
        self,
        customer_id: str,
        price_id: str,
        *,
        agent_id: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        if not self.available:
            return {"success": False, "error": "Stripe key not configured"}
        try:
            stripe = self._get_stripe()
            meta = metadata or {}
            if agent_id:
                meta["agent_id"] = agent_id
            sub = stripe.Subscription.create(
                customer=customer_id,
                items=[{"price": price_id}],
                metadata=meta,
                payment_behavior="default_incomplete",
                expand=["latest_invoice.payment_intent"],
            )
            pi = sub.latest_invoice.payment_intent if sub.latest_invoice else None
            return {
                "success": True,
                "subscription_id": sub.id,
                "status": sub.status,
                "client_secret": pi.client_secret if pi else None,
            }
        except Exception as exc:
            logger.error("Stripe create_subscription failed: %s", exc)
            return {"success": False, "error": str(exc)}

    async def cancel_subscription(self, subscription_id: str) -> Dict[str, Any]:
        if not self.available:
            return {"success": False, "error": "Stripe key not configured"}
        try:
            stripe = self._get_stripe()
            sub = stripe.Subscription.cancel(subscription_id)
            return {"success": True, "status": sub.status}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ── Customers ─────────────────────────────────────────────────────────────

    async def create_customer(
        self,
        email: str,
        name: str = "",
        *,
        agent_id: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        if not self.available:
            return {"success": False, "error": "Stripe key not configured"}
        try:
            stripe = self._get_stripe()
            meta = metadata or {}
            if agent_id:
                meta["agent_id"] = agent_id
            customer = stripe.Customer.create(email=email, name=name, metadata=meta)
            return {"success": True, "customer_id": customer.id}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ── Webhook verification ───────────────────────────────────────────────────

    def construct_event(self, payload: bytes, sig_header: str) -> Optional[Any]:
        """
        Verify + construct a Stripe webhook Event.
        Returns None if signature verification fails.
        """
        if not self._webhook_secret:
            logger.warning("Stripe webhook secret not configured — skipping verification")
            return None
        try:
            stripe = self._get_stripe()
            return stripe.Webhook.construct_event(payload, sig_header, self._webhook_secret)
        except Exception as exc:
            logger.warning("Stripe webhook verification failed: %s", exc)
            return None

    # ── Balance / payout helpers ───────────────────────────────────────────────

    async def retrieve_balance(self) -> Dict[str, Any]:
        """Retrieve the Stripe account balance (available + pending)."""
        if not self.available:
            return {"success": False, "error": "Stripe key not configured"}
        try:
            stripe = self._get_stripe()
            bal = stripe.Balance.retrieve()
            return {
                "success": True,
                "available": [{"amount": b.amount, "currency": b.currency} for b in bal.available],
                "pending": [{"amount": b.amount, "currency": b.currency} for b in bal.pending],
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def list_payment_intents(
        self,
        limit: int = 20,
        *,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List recent PaymentIntents, optionally filtered by agent_id metadata."""
        if not self.available:
            return {"success": False, "error": "Stripe key not configured", "intents": []}
        try:
            stripe = self._get_stripe()
            kwargs: Dict[str, Any] = {"limit": limit}
            intents = stripe.PaymentIntent.list(**kwargs)
            items = []
            for pi in intents.data:
                if agent_id and pi.metadata.get("agent_id") != agent_id:
                    continue
                items.append({
                    "id": pi.id,
                    "amount": pi.amount,
                    "currency": pi.currency,
                    "status": pi.status,
                    "created": pi.created,
                    "description": pi.description,
                    "metadata": dict(pi.metadata),
                })
            return {"success": True, "intents": items}
        except Exception as exc:
            return {"success": False, "error": str(exc), "intents": []}


# Singleton
stripe_service = StripeService()
