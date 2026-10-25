# Server/Resources/sasapay_callback.py

from flask_restful import Resource
from flask import request, current_app
import json
import re
from datetime import datetime

from sqlalchemy import or_

from app import db
from Server.Models.Sales import Sales
from Server.Models.Paymnetmethods import SalesPaymentMethods
from Server.Models.SoldItems import SoldItem
from Server.Models.ShopstockV2 import ShopStockV2
from Server.Models.LiveStock import LiveStock
from Server.Models.Customers import Customers
from Server.Models.Creditors import Creditors
from Server.Views.Services.journal_service import JournalService

import logging

logger = logging.getLogger(__name__)


def _is_success(cb):
    """ResultCode may arrive as '0' or 0; honour the Paid flag when present."""
    if str(cb.get("ResultCode")).strip() != "0":
        return False
    paid = cb.get("Paid")
    if paid is None:
        return True
    return paid in (True, "true", "True", "1", 1)


def _load_reservation(raw):
    """
    callback_data holds either the raw reservation payload (set at initiation)
    or {"reservation": {...}, "callback": {...}} (set after a callback).
    """
    if not raw:
        return None
    try:
        candidate = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(candidate, dict):
        return None
    if "reservation" in candidate:
        return candidate.get("reservation")
    if "ResultCode" in candidate:  # a bare callback payload, not a reservation
        return None
    return candidate


def _deduct_from_reservations(reservation, sale_id):
    """Deduct exactly what was reserved at initiation. Returns list of shortfall messages."""
    shortfalls = []

    for r in reservation.get("batch_reservations") or []:
        batch = (
            ShopStockV2.query.filter_by(stockv2_id=r["batch_id"])
            .with_for_update().first()
        )
        qty = float(r["deduct_qty"])
        if not batch:
            shortfalls.append(f"batch {r.get('batch_number')} missing")
            continue
        if batch.quantity < qty:
            shortfalls.append(
                f"batch {batch.BatchNumber}: needed {qty}, had {batch.quantity}"
            )
            qty = max(batch.quantity, 0)
        batch.quantity -= qty
        db.session.add(batch)

    for r in reservation.get("livestock_reservations") or []:
        ls = (
            LiveStock.query.filter_by(liveStock_id=r["livestock_id"])
            .with_for_update().first()
        )
        qty = float(r["deduct_qty"])
        if not ls:
            shortfalls.append(f"livestock {r.get('item_name')} missing")
            continue
        if ls.current_quantity < qty:
            shortfalls.append(
                f"livestock {ls.item_name}: needed {qty}, had {ls.current_quantity}"
            )
            qty = max(ls.current_quantity, 0)
        ls.current_quantity -= qty
        ls.clock_out_quantity -= qty
        db.session.add(ls)

    return shortfalls


def _deduct_from_sold_items(sale, sold_items):
    """Fallback when no reservation payload exists: parse SoldItem.BatchNumber."""
    shortfalls = []
    for si in sold_items:
        bn = si.BatchNumber or ""
        remaining = si.quantity

        for m in re.finditer(r"Batch\s+(\S+?)\s*\(([\d.]+)\)", bn):
            if remaining <= 0:
                break
            batch = (
                ShopStockV2.query.filter_by(
                    BatchNumber=m.group(1), shop_id=sale.shop_id, itemname=si.item_name
                ).with_for_update().first()
            )
            qty = float(m.group(2))
            if batch and batch.quantity >= qty:
                batch.quantity -= qty
                remaining -= qty
                db.session.add(batch)
            else:
                shortfalls.append(f"{si.item_name}: batch {m.group(1)} missing/insufficient")

        if remaining > 0:
            ls = LiveStock.query.filter(
                LiveStock.shop_id == sale.shop_id,
                LiveStock.item_name == si.item_name,
            ).with_for_update().first()
            if ls and ls.current_quantity >= remaining:
                ls.current_quantity -= remaining
                ls.clock_out_quantity -= remaining
                db.session.add(ls)
            else:
                shortfalls.append(f"{si.item_name}: livestock missing/insufficient")
    return shortfalls


class SasaPayCallbackResource(Resource):
    """
    SasaPay C2B callback. Confirms the pending sale, deducts reserved stock,
    posts the journal. Always returns 200 so SasaPay doesn't retry forever.
    """

    def post(self):
        try:
            callback_data = request.get_json(silent=True)
            current_app.logger.info(f"[SASAPAY] Callback received: {callback_data}")

            if not callback_data or "ResultCode" not in callback_data:
                current_app.logger.error("[SASAPAY] Invalid callback data")
                return {"status": "error", "message": "Invalid callback data"}, 200

            # ── Extract fields (SasaPay uses several names for the same thing) ──
            checkout_request_id = callback_data.get("CheckoutRequestID")
            result_code = str(callback_data.get("ResultCode")).strip()
            result_desc = callback_data.get("ResultDesc")
            received_amount = callback_data.get("TransAmount") or callback_data.get("Amount")
            transaction_code = (
                callback_data.get("TransactionCode")
                or callback_data.get("TransactionReference")
                or callback_data.get("SasaPayTransactionID")
            )
            merchant_code = callback_data.get("MerchantCode")
            customer_name = callback_data.get("CustomerName")
            customer_number = (
                callback_data.get("CustomerMobile") or callback_data.get("CustomerNumber")
            )

            if not checkout_request_id:
                current_app.logger.error("[SASAPAY] Missing CheckoutRequestID")
                return {"status": "error", "message": "Missing CheckoutRequestID"}, 200

            payment_method = SalesPaymentMethods.query.filter_by(
                checkout_request_id=checkout_request_id
            ).first()
            if not payment_method:
                current_app.logger.error(
                    f"[SASAPAY] Payment method not found for: {checkout_request_id}"
                )
                return {"status": "error", "message": "Transaction not found"}, 200

            sale = Sales.query.get(payment_method.sale_id)
            if not sale:
                current_app.logger.error(
                    f"[SASAPAY] Sale not found for ID: {payment_method.sale_id}"
                )
                return {"status": "error", "message": "Sale not found"}, 200

            # ── Idempotency ──────────────────────────────────────────
            if (
                payment_method.callback_received_at is not None
                and payment_method.payment_status in ("success", "failed")
            ):
                current_app.logger.info(
                    f"[SASAPAY] Duplicate callback for {checkout_request_id} "
                    f"(status={payment_method.payment_status}); ignored."
                )
                return {
                    "status": "success",
                    "message": "Callback already processed (idempotent)",
                    "result_code": payment_method.result_code,
                    "sale_id": sale.sales_id,
                    "sale_status": sale.status,
                }, 200

            # ── Merchant sanity check ────────────────────────────────
            expected_merchant_code = getattr(payment_method, "merchant_code", None)
            if expected_merchant_code and merchant_code:
                if str(expected_merchant_code) != str(merchant_code):
                    current_app.logger.warning(
                        f"[SASAPAY] Merchant mismatch for {checkout_request_id}: "
                        f"expected {expected_merchant_code}, got {merchant_code}"
                    )
                    return {"status": "error", "message": "Merchant mismatch"}, 200

            # ── Read reservation BEFORE overwriting callback_data ────
            reservation_data = _load_reservation(payment_method.callback_data)

            success = _is_success(callback_data)

            payment_method.sasapay_transaction_id = transaction_code
            payment_method.payment_status = "success" if success else "failed"
            payment_method.callback_received_at = datetime.utcnow()
            payment_method.result_code = result_code
            payment_method.result_desc = result_desc
            # keep the reservation alongside the callback payload
            payment_method.callback_data = json.dumps({
                "reservation": reservation_data,
                "callback": callback_data,
            })

            # ═════════════ SUCCESS ═════════════
            if success:
                current_app.logger.info(f"[SASAPAY] Payment successful for sale {sale.sales_id}")

                # Real M-Pesa/SasaPay code replaces our own reference so that
                # reconciliation against the statement can match on it.
                if transaction_code:
                    payment_method.transaction_code = str(transaction_code).strip().upper()

                if received_amount:
                    try:
                        if abs(float(received_amount) - float(payment_method.amount_paid or 0)) > 1:
                            current_app.logger.warning(
                                f"[SASAPAY] Amount mismatch sale {sale.sales_id}: "
                                f"expected {payment_method.amount_paid}, received {received_amount}"
                            )
                    except (TypeError, ValueError):
                        pass

                if customer_name:
                    sale.customer_name = customer_name
                if customer_number:
                    sale.customer_number = customer_number
                if customer_name or customer_number:
                    customer = Customers.query.filter_by(sales_id=sale.sales_id).first()
                    if customer:
                        if customer_name:
                            customer.customer_name = customer_name
                        if customer_number:
                            customer.customer_number = customer_number
                        db.session.add(customer)

                # Totals: count paid + discount, ignore pending/failed rows
                valid_payment = or_(
                    SalesPaymentMethods.payment_status.is_(None),
                    SalesPaymentMethods.payment_status == "success",
                )
                db.session.flush()
                total_paid = (
                    db.session.query(db.func.coalesce(db.func.sum(SalesPaymentMethods.amount_paid), 0))
                    .filter(SalesPaymentMethods.sale_id == sale.sales_id)
                    .filter(valid_payment)
                    .scalar()
                )
                total_discount = (
                    db.session.query(db.func.coalesce(db.func.sum(SalesPaymentMethods.discount), 0))
                    .filter(SalesPaymentMethods.sale_id == sale.sales_id)
                    .filter(valid_payment)
                    .scalar()
                )
                sold_items_total = (
                    db.session.query(db.func.coalesce(db.func.sum(SoldItem.total_price), 0))
                    .filter(SoldItem.sales_id == sale.sales_id)
                    .scalar()
                )

                balance = round(
                    max(0.0, float(sold_items_total) - float(total_paid) - float(total_discount)), 2
                )
                sale.balance = 0 if balance <= 0.01 else balance
                sale.status = "paid" if sale.balance == 0 else "partially_paid"
                sale.note = (
                    f"Payment confirmed via SasaPay. "
                    f"Transaction: {transaction_code or checkout_request_id}"
                )
                sale.timestamp = datetime.utcnow()
                db.session.add(sale)

                # ── Stock ────────────────────────────────────────────
                sold_items = SoldItem.query.filter_by(sales_id=sale.sales_id).all()

                if reservation_data and (
                    reservation_data.get("batch_reservations")
                    or reservation_data.get("livestock_reservations")
                ):
                    shortfalls = _deduct_from_reservations(reservation_data, sale.sales_id)
                else:
                    shortfalls = _deduct_from_sold_items(sale, sold_items)

                if shortfalls:
                    current_app.logger.warning(
                        f"[SASAPAY] Stock shortfall on sale {sale.sales_id}: {shortfalls}"
                    )
                    sale.note += " | STOCK SHORTFALL: " + "; ".join(shortfalls)

                # ── Journal (savepoint so a failure can't poison the commit) ──
                try:
                    creditor_id = reservation_data.get("creditor_id") if reservation_data else None
                    sold_items_with_details = [{
                        "item_name": i.item_name,
                        "quantity": i.quantity,
                        "metric": i.metric,
                        "unit_price": i.unit_price,
                        "total_price": i.total_price,
                        "Purchase_account": i.Purchase_account,
                        "Cost_of_sale": i.Cost_of_sale,
                    } for i in sold_items]

                    with db.session.begin_nested():
                        JournalService.post_sale_journal(
                            sale=sale,
                            sold_items=sold_items_with_details,
                            shop_id=sale.shop_id,
                            creditor_id=creditor_id,
                            amount_paid=payment_method.amount_paid,
                        )
                    current_app.logger.info(
                        f"[SASAPAY] Journal posted for sale {sale.sales_id} (creditor_id={creditor_id})"
                    )
                except Exception as journal_err:
                    current_app.logger.error(
                        f"[SASAPAY] Journal posting FAILED for sale {sale.sales_id}: {journal_err}",
                        exc_info=True,
                    )
                    payment_method.journal_posting_error = str(journal_err)

            # ═════════════ FAILURE ═════════════
            else:
                current_app.logger.warning(
                    f"[SASAPAY] Payment failed for sale {sale.sales_id}: "
                    f"{result_desc} (Code: {result_code})"
                )
                sale.status = "failed"
                sale.note = f"Payment failed: {result_desc}"
                sale.timestamp = datetime.utcnow()
                payment_method.failure_reason = result_desc
                db.session.add(sale)

                # Reverse the creditor credit added at initiation
                creditor_id = reservation_data.get("creditor_id") if reservation_data else None
                total_amount = float(reservation_data.get("total_amount") or 0) if reservation_data else 0
                if creditor_id and total_amount:
                    creditor = Creditors.query.get(creditor_id)
                    if creditor:
                        creditor.total_credit = max(0, (creditor.total_credit or 0) - total_amount)
                        creditor.credit_amount = max(0, (creditor.credit_amount or 0) - total_amount)
                        db.session.add(creditor)

            db.session.commit()

            return {
                "status": "success",
                "message": "Callback processed successfully",
                "result_code": result_code,
                "sale_id": sale.sales_id,
                "sale_status": sale.status,
            }, 200

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"[SASAPAY] Callback processing error: {str(e)}", exc_info=True
            )
            return {"status": "error", "message": str(e)}, 200