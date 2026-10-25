# Server/Views/SasaPayStatementSales.py

import logging
from datetime import datetime, timedelta

from flask import request, current_app
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app import db
from Server.Models.Sales import Sales
from Server.Models.StockItems import StockItems
from Server.Models.LiveStock import LiveStock
from Server.Models.SoldItems import SoldItem
from Server.Models.Paymnetmethods import SalesPaymentMethods
from Server.Models.Users import Users
from Server.Models.InventoryV2 import InventoryV2
from Server.Models.ShopstockV2 import ShopStockV2
from Server.Models.SasaPayMerchantConfig import SasaPayMerchantConfig
from Server.Models.SasaPayStatementClaim import SasaPayStatementClaim
from Server.Views.Services.sasapay_service import SasaPayPaymentService
from Server.Views.Services.journal_service import JournalService
from Server.Views.Utils.customer_utils import CustomerService

logger = logging.getLogger(__name__)

sasapay_service = SasaPayPaymentService()

DISCOUNT_THRESHOLD_PCT = 3.0   # items may exceed the paid amount by up to this %
OVERPAY_TOLERANCE = 1.0        # KES the paid amount may exceed the items total


# ─────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────
def _today_eat():
    return (datetime.utcnow() + timedelta(hours=3)).date()


def _user_may_access_shop(user_id, shop_id):
    user = Users.query.get(user_id)
    if not user:
        return False
    if user.role != "clerk":
        return True
    emp = getattr(user, "employees", None)
    shop = getattr(emp, "shops", None) if emp else None
    return bool(shop and shop.shops_id == shop_id)


def _resolve_merchant(shop_id):
    """Returns (merchant_code, error_tuple_or_None)."""
    env = sasapay_service.environment
    if env != "production":
        return None, ({
            "error": "Statements are only available in PRODUCTION environment",
            "environment": env,
        }, 400)
    cfg = SasaPayMerchantConfig.get_for_shop(shop_id)
    if not cfg:
        return None, ({"error": f"No active SasaPay merchant configured for shop {shop_id}"}, 404)
    return cfg.merchant_code, None


def _is_incoming_success(tx):
    """Money IN, completed, not reversed. Adjust here if real statement values differ."""
    if "IN" not in (tx["type"] or "").split():
        return False
    rc = str(tx["result_code"] or "").strip().upper()
    if rc and rc not in ("SP00000", "0"):
        return False
    if str(tx["reversal_status"] or "").strip().upper() == "REVERSED":
        return False
    return bool(tx["code"])


def _claimed_map(merchant_code, codes):
    """{transaction_code: sale_id} from the claims table + any sale already holding the code."""
    claimed = {}
    if not codes:
        return claimed

    for c in SasaPayStatementClaim.query.filter(
        SasaPayStatementClaim.merchant_code == merchant_code,
        SasaPayStatementClaim.transaction_code.in_(codes),
    ).all():
        claimed[c.transaction_code] = c.sale_id

    # Legacy / STK-push / manually typed codes
    rows = (
        db.session.query(func.upper(SalesPaymentMethods.transaction_code), SalesPaymentMethods.sale_id)
        .filter(func.upper(SalesPaymentMethods.transaction_code).in_(codes))
        .all()
    )
    for code, sale_id in rows:
        claimed.setdefault(code, sale_id)
    return claimed


# ─────────────────────────────────────────────────────────────────────
#  GET: transactions for a shop + day, with claimed flag
# ─────────────────────────────────────────────────────────────────────
class SasaPayUnclaimedStatement(Resource):
    """
    GET /sasapay/statement/unclaimed?shop_id=2&date=2026-10-22[&include_claimed=false]
    """

    @jwt_required()
    def get(self):
        try:
            shop_id = int(request.args.get("shop_id", ""))
        except ValueError:
            return {"error": "shop_id is required and must be an integer"}, 400

        date_str = request.args.get("date")
        try:
            day = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else _today_eat()
        except ValueError:
            return {"error": "Invalid date format. Use YYYY-MM-DD."}, 400

        if not _user_may_access_shop(get_jwt_identity(), shop_id):
            return {"error": "You cannot view statements for this shop"}, 403

        include_claimed = request.args.get("include_claimed", "true").lower() != "false"

        merchant_code, err = _resolve_merchant(shop_id)
        if err:
            return err

        try:
            rows = sasapay_service.fetch_statement_range(merchant_code, day, day)
        except Exception as e:
            current_app.logger.error(f"[SASAPAY] Statement fetch failed for {merchant_code}: {e}")
            return {"error": "Could not fetch SasaPay statement", "details": str(e)}, 502

        incoming = [r for r in rows if _is_incoming_success(r)]
        claimed = _claimed_map(merchant_code, [r["code"] for r in incoming])

        transactions = []
        for r in sorted(incoming, key=lambda x: x["datetime"], reverse=True):
            is_claimed = r["code"] in claimed
            if is_claimed and not include_claimed:
                continue
            transactions.append({
                "transaction_code": r["code"],
                "amount": r["amount"],
                "datetime": r["datetime"].strftime("%Y-%m-%d %H:%M:%S"),
                "channel": r["channel"],
                "reference": r["reference"],
                "description": r["description"],
                "payment_details": r["payment_details"],
                "claimed": is_claimed,
                "claimed_sale_id": claimed.get(r["code"]),
            })

        unclaimed = [t for t in transactions if not t["claimed"]]
        return {
            "shop_id": shop_id,
            "merchant_code": merchant_code,
            "date": day.isoformat(),
            "summary": {
                "total": len(transactions),
                "claimed": len(transactions) - len(unclaimed),
                "unclaimed": len(unclaimed),
                "unclaimed_amount": round(sum(t["amount"] for t in unclaimed), 2),
            },
            "transactions": transactions,
        }, 200


# ─────────────────────────────────────────────────────────────────────
#  POST: add a sale against one or more statement transactions
# ─────────────────────────────────────────────────────────────────────
class AddSaleFromStatement(Resource):
    """
    POST /sasapay/statement/sale
    {
      "shop_id": 2,
      "transaction_codes": ["SPEJ12345Q7V2PD", "SPEJ67890A1B2CD"],   # one or more
      "date": "2026-10-22",                 # the statement day the rows were picked from
      "customer_name": "", "customer_number": "",
      "delivery": false, "promocode": "", "register_for_loyalty": false,
      "items": [{item_name, quantity, metric, unit_price, total_price}, ...]
    }
    Amounts, codes, payment method and status come from the verified statement rows.
    One sale can claim several transactions; each transaction can only be claimed once.
    """

    @jwt_required()
    def post(self):
        data = request.get_json(silent=True) or {}
        current_user_id = get_jwt_identity()
        new_sale = None

        # ===== VALIDATION =====
        required = ["shop_id", "date", "items"]
        missing = [f for f in required if f not in data]
        if "transaction_codes" not in data and "transaction_code" not in data:
            missing.append("transaction_codes")
        if missing:
            return {"message": "Missing required fields", "missing": missing}, 400

        try:
            shop_id = int(data["shop_id"])
            tx_day = datetime.strptime(data["date"], "%Y-%m-%d").date()

            raw_codes = data.get("transaction_codes")
            if raw_codes is None:
                raw_codes = [data["transaction_code"]]
            if isinstance(raw_codes, str):
                raw_codes = [raw_codes]
            if not isinstance(raw_codes, list) or not raw_codes:
                return {"message": "transaction_codes must be a non-empty list"}, 400

            tx_codes = []
            for c in raw_codes:
                code = str(c).strip().upper()
                if code and code not in tx_codes:   # de-duplicate, keep order
                    tx_codes.append(code)
            if not tx_codes:
                return {"message": "transaction_codes must be a non-empty list"}, 400

            customer_name = (data.get("customer_name") or "").strip()
            customer_number = (data.get("customer_number") or "").strip()
            delivery = bool(data.get("delivery", False))
            promocode = data.get("promocode", "")
            register_for_loyalty = data.get("register_for_loyalty", False)

            if not isinstance(data["items"], list) or not data["items"]:
                return {"message": "Items must be a non-empty list"}, 400

            items = []
            items_total = 0.0
            for item in data["items"]:
                fields = ["item_name", "quantity", "metric", "unit_price", "total_price"]
                if not all(f in item for f in fields):
                    return {
                        "message": "Missing required item fields",
                        "missing": [f for f in fields if f not in item],
                    }, 400

                metric = item["metric"].strip().lower()
                if metric not in ["item", "kg", "ltrs"]:
                    return {
                        "message": f"Invalid metric '{metric}' for item '{item['item_name']}'. Must be one of: item, kg, ltrs",
                        "invalid_item": item,
                    }, 400

                stock_item = StockItems.query.filter_by(item_name=item["item_name"]).first()
                if not stock_item:
                    logger.warning(f"Item '{item['item_name']}' not found in StockItems")
                is_service = bool(stock_item and stock_item.stock_item_type == "Service")

                items.append({
                    "item_name": item["item_name"],
                    "quantity": float(item["quantity"]),
                    "metric": metric,
                    "unit_price": float(item["unit_price"]),
                    "total_price": float(item["total_price"]),
                    "item_id": stock_item.id if stock_item else None,
                    "is_service": is_service,
                })
                items_total += float(item["total_price"])

        except (ValueError, KeyError, TypeError) as e:
            return {"message": f"Invalid data format: {str(e)}"}, 400

        if not _user_may_access_shop(current_user_id, shop_id):
            return {"message": "You cannot record sales for this shop"}, 403

        # ===== VERIFY THE STATEMENT TRANSACTIONS (server is the source of truth) =====
        merchant_code, err = _resolve_merchant(shop_id)
        if err:
            return err

        try:
            day_rows = sasapay_service.fetch_statement_range(merchant_code, tx_day, tx_day)
        except Exception as e:
            current_app.logger.error(f"[SASAPAY] Statement verify failed: {e}")
            return {"message": "Could not verify transactions with SasaPay", "error": str(e)}, 502

        valid_by_code = {r["code"]: r for r in day_rows if _is_incoming_success(r)}
        not_found = [c for c in tx_codes if c not in valid_by_code]
        if not_found:
            return {
                "message": f"Not found as successful incoming payments on {tx_day} for this shop: {', '.join(not_found)}",
                "not_found": not_found,
            }, 404

        already = _claimed_map(merchant_code, tx_codes)
        if already:
            return {
                "message": f"Already have a sale recorded against them: {', '.join(already.keys())}",
                "claimed": {code: sale_id for code, sale_id in already.items()},
            }, 409

        txs = [valid_by_code[c] for c in tx_codes]

        # ===== AMOUNT vs ITEMS (sum of all selected transactions) =====
        paid_amount = round(sum(t["amount"] for t in txs), 2)
        items_total = round(items_total, 2)
        diff = round(items_total - paid_amount, 2)
        discount = 0.0

        if diff > 0:
            pct = (diff / items_total) * 100 if items_total > 0 else 100
            if pct > DISCOUNT_THRESHOLD_PCT:
                return {
                    "message": f"Items total ({items_total}) is more than the transactions total ({paid_amount}). Reduce the items or select more transactions.",
                    "items_total": items_total,
                    "transactions_total": paid_amount,
                }, 400
            discount = diff
        elif -diff > OVERPAY_TOLERANCE:
            return {
                "message": f"Transactions total ({paid_amount}) is more than the items total ({items_total}). Add the missing items or deselect a transaction.",
                "items_total": items_total,
                "transactions_total": paid_amount,
            }, 400

        sale_datetime = min(t["datetime"] for t in txs)

        # ===== STOCK PROCESSING =====
        stock_errors = []
        batch_deductions = []
        livestock_deductions = []
        sold_items = []
        purchase_account = 0.0

        try:
            for item in items:
                if item["is_service"]:
                    sold_items.append({
                        "item_name": item["item_name"],
                        "quantity": item["quantity"],
                        "metric": item["metric"],
                        "unit_price": item["unit_price"],
                        "total_price": item["total_price"],
                        "BatchNumber": "Service Item - No Stock Deduction",
                        "stockv2_id": None,
                        "item_id": item["item_id"],
                        "Cost_of_sale": item["total_price"],
                        "Purchase_account": 0.0,
                        "LivestockDeduction": 0.0,
                        "is_service": True,
                    })
                    batch_deductions.append({
                        "item_name": item["item_name"],
                        "item_id": item["item_id"],
                        "deductions": [("Service Item", 0)],
                        "is_service": True,
                    })
                    continue

                batches = ShopStockV2.query.filter(
                    ShopStockV2.itemname == item["item_name"],
                    ShopStockV2.shop_id == shop_id,
                    ShopStockV2.quantity > 0,
                ).order_by(ShopStockV2.BatchNumber).with_for_update().all()

                remaining = item["quantity"]
                item_batches = []
                item_stock_ids = []
                item_purchase = 0.0
                item_livestock = 0.0

                for batch in batches:
                    if remaining <= 0:
                        break
                    deduct = min(batch.quantity, remaining)
                    batch.quantity -= deduct
                    remaining -= deduct
                    item_batches.append((batch.BatchNumber, deduct))
                    item_stock_ids.append(str(batch.stockv2_id))

                    inventory = InventoryV2.query.filter_by(inventoryV2_id=batch.inventoryv2_id).first()
                    if inventory:
                        item_purchase += inventory.unitCost * deduct
                    db.session.add(batch)

                if remaining > 0:
                    ls = LiveStock.query.filter(
                        LiveStock.shop_id == shop_id,
                        func.lower(LiveStock.item_name) == item["item_name"].lower(),
                    ).with_for_update().first()
                    if ls and ls.current_quantity > 0:
                        deduct = min(ls.current_quantity, remaining)
                        ls.current_quantity -= deduct
                        ls.clock_out_quantity -= deduct
                        remaining -= deduct
                        item_livestock = deduct
                        db.session.add(ls)
                        livestock_deductions.append({
                            "item_name": item["item_name"],
                            "quantity": deduct,
                            "original_current": ls.current_quantity + deduct,
                            "new_current": ls.current_quantity,
                        })

                if remaining > 0:
                    stock_errors.append(
                        f"Insufficient stock for {item['item_name']}. Needed {item['quantity']}, available {item['quantity'] - remaining}"
                    )
                    continue

                if item_batches:
                    batch_deductions.append({
                        "item_name": item["item_name"],
                        "item_id": item["item_id"],
                        "deductions": item_batches,
                        "is_service": False,
                    })
                purchase_account += item_purchase

                sold_items.append({
                    "item_name": item["item_name"],
                    "quantity": item["quantity"],
                    "metric": item["metric"],
                    "unit_price": item["unit_price"],
                    "total_price": item["total_price"],
                    "BatchNumber": ", ".join(f"{bn} ({q})" for bn, q in item_batches) if item_batches else "From Livestock",
                    "stockv2_id": item_stock_ids[0] if item_stock_ids else None,
                    "item_id": item["item_id"],
                    "Cost_of_sale": item["total_price"],
                    "Purchase_account": item_purchase,
                    "LivestockDeduction": item_livestock,
                    "is_service": False,
                })

            if stock_errors:
                db.session.rollback()
                return {"message": "Stock processing failed", "errors": stock_errors}, 400

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"[SASAPAY-STMT] Stock processing failed: {e}", exc_info=True)
            return {"message": "Stock processing failed", "error": str(e)}, 500

        # ===== CREATE SALE + CLAIMS (one DB transaction) =====
        customer_result = None
        try:
            new_sale = Sales(
                user_id=current_user_id,
                shop_id=shop_id,
                customer_name=customer_name,
                customer_number=customer_number,
                status="paid",
                delivery=delivery,
                created_at=sale_datetime,
                balance=0,
                promocode=promocode,
                note=f"Recorded against SasaPay transaction(s): {', '.join(tx_codes)}",
            )
            db.session.add(new_sale)
            db.session.flush()

            # Unique (merchant_code, transaction_code): the loser of a race fails here
            for t in txs:
                db.session.add(SasaPayStatementClaim(
                    merchant_code=merchant_code,
                    transaction_code=t["code"],
                    sale_id=new_sale.sales_id,
                    shop_id=shop_id,
                    amount=round(t["amount"], 2),
                    claimed_by=current_user_id,
                ))
            db.session.flush()

            for item in sold_items:
                tp = float(item["total_price"])
                db.session.add(SoldItem(
                    sales_id=new_sale.sales_id,
                    item_name=item["item_name"],
                    quantity=item["quantity"],
                    metric=item["metric"],
                    unit_price=item["unit_price"],
                    total_price=tp,
                    BatchNumber=item["BatchNumber"],
                    stockv2_id=item.get("stockv2_id"),
                    item_id=item.get("item_id"),
                    Cost_of_sale=item["Cost_of_sale"],
                    Purchase_account=item.get("Purchase_account", 0.0),
                    LivestockDeduction=item.get("LivestockDeduction", 0.0),
                    round_off=round(tp - int(tp), 2),
                    is_service=item.get("is_service", False),
                ))

            # One payment row per transaction, each with its real code
            for idx, t in enumerate(txs):
                db.session.add(SalesPaymentMethods(
                    sale_id=new_sale.sales_id,
                    payment_method="sasapay",
                    amount_paid=round(t["amount"], 2),
                    discount=discount if idx == 0 else 0,
                    transaction_code=t["code"],
                    sasapay_transaction_id=t["code"],
                    merchant_code=merchant_code,
                    payment_status="success",
                    created_at=t["datetime"],
                ))

            if customer_name or customer_number:
                try:
                    customer_result = CustomerService.add_or_update_customer(
                        customer_name=customer_name,
                        customer_number=customer_number,
                        shop_id=shop_id,
                        sales_id=new_sale.sales_id,
                        user_id=current_user_id,
                        items=[i["item_name"] for i in items],
                        amount_paid=paid_amount,
                        payment_method="sasapay",
                        created_at=sale_datetime,
                        register_for_loyalty=register_for_loyalty,
                    )
                except Exception as e:
                    logger.error(f"Failed to process customer: {e}")

            db.session.commit()

        except IntegrityError:
            db.session.rollback()
            return {"message": "One or more of these transactions was just claimed by another sale"}, 409
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"[SASAPAY-STMT] Sale creation failed: {e}", exc_info=True)
            return {
                "message": "Transaction failed",
                "error": str(e),
                "debug_info": {"sale_id": new_sale.sales_id if new_sale else "Not created"},
            }, 500

        # ===== JOURNAL (sale already committed) =====
        try:
            JournalService.post_sale_journal(
                sale=new_sale,
                sold_items=sold_items,
                shop_id=shop_id,
                creditor_id=None,
                amount_paid=paid_amount,
            )
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Journal posting failed for sale {new_sale.sales_id}: {e}")

        response = {
            "message": "Sale recorded against SasaPay transaction(s)",
            "sale_id": new_sale.sales_id,
            "transactions": [
                {
                    "transaction_code": t["code"],
                    "amount": round(t["amount"], 2),
                    "datetime": t["datetime"].strftime("%Y-%m-%d %H:%M:%S"),
                }
                for t in txs
            ],
            "financial": {
                "total": items_total,
                "paid": paid_amount,
                "discount": discount,
                "balance": 0,
                "purchase_cost": purchase_account,
            },
            "items": {"count": len(items), "details": sold_items},
            "stock_deductions": {"shop_stock": batch_deductions, "livestock": livestock_deductions},
            "customer": None,
        }
        if customer_result:
            c = customer_result["customer"]
            response["customer"] = {
                "customer_id": c.customer_id,
                "customer_name": c.customer_name,
                "is_new_customer": customer_result["is_new"],
                "points_earned": customer_result["points_earned"],
                "loyalty_points": c.loyalty_points or 0,
                "loyalty_tier": c.loyalty_tier or "Bronze",
                "is_loyalty_registered": c.is_loyalty_registered or False,
            }
        return response, 201