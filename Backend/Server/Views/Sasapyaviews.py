# Server/Resources/sasapay_merchant_resource.py

import os
import uuid
import requests
from datetime import datetime, timedelta
from requests.auth import HTTPBasicAuth
import random
from flask import current_app, request
from flask_restful import Resource
from flask_jwt_extended import jwt_required
import socket
from app import db
from Server.Models.SasaPayMerchantConfig import SasaPayMerchantConfig
from Server.Models.Shops import Shops
from Server.Views.Services.sasapay_service import SasaPayPaymentService


sasapay_service = SasaPayPaymentService()


def _now():
    return datetime.utcnow().isoformat()


def _ref(prefix):
    return f"{prefix}{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{str(uuid.uuid4())[:8]}"

# Start
#   ↓
# Get environment (sandbox/production)
#   ↓
# Get merchant configurations
#   ↓
# For each merchant:
#   ├── Get access token (using merchant's credentials)
#   ├── Fetch balance (using token + merchant code)
#   └── Format response
#   ↓
# Aggregate all balances
#   ↓
# Return combined response with:
#   - Total combined balance
#   - Individual merchant balances
#   - Success/failure counts



# ═════════════════════════════════════════════════════════════════════
#  HELPERS — single source of truth for merchant lookups
# ═════════════════════════════════════════════════════════════════════
def _current_environment():
    return os.getenv("SASAPAY_ENVIRONMENT", "sandbox")


def _get_base_url(environment=None):
    environment = environment or _current_environment()
    if environment == "production":
        return os.getenv("SASAPAY_PRODUCTION_BASE_URL", "https://api.sasapay.app")
    return os.getenv("SASAPAY_SANDBOX_BASE_URL", "https://sandbox.sasapay.app")


def _get_active_merchant_configs(environment=None):
    """
    Return every active SasaPayMerchantConfig row for the given environment.

    In sandbox mode we return ONLY the sandbox merchant code (whatever
    SASAPAY_SANDBOX_MERCHANT_CODE points to, default 600980), so that
    running the app locally never accidentally hits production merchants.

    In production mode we return every active row.
    """
    environment = environment or _current_environment()

    if environment == "sandbox":
        sandbox_code = os.getenv("SASAPAY_SANDBOX_MERCHANT_CODE", "600980")
        return SasaPayMerchantConfig.query.filter_by(
            merchant_code=sandbox_code,
            is_active=True,
        ).all()

    return SasaPayMerchantConfig.query.filter_by(is_active=True).all()


def _get_merchant_config_by_code(merchant_code):
    """Fetch a single active config by merchant code."""
    return SasaPayMerchantConfig.query.filter_by(
        merchant_code=str(merchant_code).strip(),
        is_active=True,
    ).first()


def _merchant_to_public_dict(config):
    """Shape a SasaPayMerchantConfig into what the frontend expects."""
    return {
        "code": config.merchant_code,
        "name": config.merchant_name or f"Merchant {config.merchant_code}",
        "location": config.location or "",
        "type": config.merchant_type or "shop",
        "shop_id": config.shop_id,
    }


# ═════════════════════════════════════════════════════════════════════
#  Add / manage merchant configs
# ═════════════════════════════════════════════════════════════════════
class AddSasaPayMerchants(Resource):
    """
    Create OR update a SasaPay merchant config and link it to a shop.

    POST /api/sasapay/merchants/add

    Body (create):
    {
        "shop_id": 2,
        "merchant_code": "570257",
        "merchant_name": "Kuku Zetu - Mirema",
        "location": "Mirema",
        "merchant_type": "shop",
        "client_id": "blxABPMUT...",
        "client_secret": "GdUoJ9Gea...",
        "is_active": true
    }

    Body (update — same shape, merchant_code must already exist):
    {
        "shop_id": 2,
        "merchant_code": "570257",
        "client_id": "NEW_CLIENT_ID",
        "client_secret": "NEW_CLIENT_SECRET",
        ...same fields...
    }

    Returns:
        201 if a new config was created
        200 if an existing config was updated
        400 on validation failure
        404 if the shop doesn't exist
        500 on unexpected error
    """

    @jwt_required()
    def post(self):
        data = request.get_json(silent=True) or {}

        # ── Validation ───────────────────────────────────────────────
        required_fields = [
            "shop_id", "merchant_code", "client_id", "client_secret"
        ]
        missing = [f for f in required_fields if not data.get(f)]
        if missing:
            return {
                "message": "Missing required fields",
                "missing": missing,
            }, 400

        shop_id = data["shop_id"]
        merchant_code = str(data["merchant_code"]).strip()
        client_id = data["client_id"]
        client_secret = data["client_secret"]
        merchant_name = data.get("merchant_name")
        location = data.get("location")
        merchant_type = data.get("merchant_type", "shop")
        is_active = data.get("is_active", True)

        # ── Shop must exist ──────────────────────────────────────────
        shop = Shops.query.get(shop_id)
        if not shop:
            return {
                "message": f"Shop with id {shop_id} not found",
            }, 404

        # ── Merchant type validation ─────────────────────────────────
        valid_types = ["shop", "stockist", "test"]
        if merchant_type not in valid_types:
            return {
                "message": (
                    f"Invalid merchant_type. Must be one of: "
                    f"{', '.join(valid_types)}"
                ),
            }, 400

        # ── Look for existing config ─────────────────────────────────
        existing = SasaPayMerchantConfig.query.filter_by(
            merchant_code=merchant_code
        ).first()

        # ═════════════════════════════════════════════════════════════
        #  UPDATE PATH
        # ═════════════════════════════════════════════════════════════
        if existing:
            try:
                existing.shop_id = shop_id
                existing.merchant_name = merchant_name
                existing.location = location
                existing.merchant_type = merchant_type
                existing.is_active = is_active

                # Encrypts + stores both credentials (Fernet)
                existing.set_credentials(client_id, client_secret)

                db.session.commit()

                current_app.logger.info(
                    f"[SASAPAY] Updated merchant config {merchant_code} "
                    f"for shop {shop_id}"
                )

                return {
                    "message": "SasaPay merchant config updated successfully",
                    "config": existing.to_dict(include_secrets=True),
                }, 200

            except Exception as e:
                db.session.rollback()
                current_app.logger.error(
                    f"[SASAPAY] Failed to update merchant config "
                    f"{merchant_code}: {str(e)}",
                    exc_info=True,
                )
                return {
                    "message": "Failed to update merchant config",
                    "error": str(e),
                }, 500

        # ═════════════════════════════════════════════════════════════
        #  CREATE PATH
        # ═════════════════════════════════════════════════════════════
        try:
            config = SasaPayMerchantConfig(
                shop_id=shop_id,
                merchant_code=merchant_code,
                merchant_name=merchant_name,
                location=location,
                merchant_type=merchant_type,
                is_active=is_active,
            )
            # Encrypts + stores both credentials (Fernet)
            config.set_credentials(client_id, client_secret)

            db.session.add(config)
            db.session.commit()

            current_app.logger.info(
                f"[SASAPAY] Created merchant config {merchant_code} "
                f"for shop {shop_id}"
            )

            return {
                "message": "SasaPay merchant config created successfully",
                "config": config.to_dict(include_secrets=True),
            }, 201

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"[SASAPAY] Failed to create merchant config "
                f"{merchant_code}: {str(e)}",
                exc_info=True,
            )
            return {
                "message": "Failed to create merchant config",
                "error": str(e),
            }, 500




# ═════════════════════════════════════════════════════════════════════
#  Balances
# ═════════════════════════════════════════════════════════════════════
class SasaPayBalanceResource(Resource):
    """Balances for all configured merchants, or one via ?merchant_code=."""

    @jwt_required()
    def get(self):
        env = sasapay_service.environment
        merchant_code_param = request.args.get('merchant_code')

        try:
            if merchant_code_param:
                m = sasapay_service.get_merchant(merchant_code_param)
                merchants = [m] if m else []
                if not merchants:
                    return {
                        "error": f"Merchant {merchant_code_param} not found or not configured",
                        "environment": env
                    }, 404
            else:
                merchants = sasapay_service.get_all_merchants()
                if not merchants:
                    return {
                        "error": f"No merchants configured for {env} environment",
                        "environment": env
                    }, 404

            all_balances = []
            total_combined_balance = 0
            successful = 0
            failed = 0

            for merchant in merchants:
                result = sasapay_service.get_balance(merchant['code'])

                if result.get('status'):
                    d = result['data']
                    total_combined_balance += d.get('total_balance') or 0
                    successful += 1
                    all_balances.append({
                        "merchant_code": merchant['code'],
                        "merchant_name": merchant['name'],
                        "location": merchant.get('location', ''),
                        "type": merchant.get('type', 'shop'),
                        "total_balance": d.get('total_balance', 0),
                        "currency": d.get('currency', 'KES'),
                        "accounts": d.get('accounts', []),
                        "statusCode": d.get('statusCode'),
                        "message": d.get('message')
                    })
                else:
                    failed += 1
                    all_balances.append({
                        "merchant_code": merchant['code'],
                        "merchant_name": merchant['name'],
                        "location": merchant.get('location', ''),
                        "type": merchant.get('type', 'shop'),
                        "error": result.get('message', 'Failed to fetch'),
                        "total_balance": 0
                    })

            return {
                "success": True,
                "environment": env,
                "total_merchants": len(merchants),
                "successful_fetches": successful,
                "failed_fetches": failed,
                "total_combined_balance": total_combined_balance,
                "currency": "KES",
                "merchants": all_balances,
                "timestamp": _now()
            }, 200

        except Exception as e:
            current_app.logger.error(f"SasaPay balance error: {str(e)}")
            return {"error": str(e), "environment": env}, 500


class SasaPaySingleBalanceResource(Resource):
    """Balance for one merchant. ?merchant_code= (defaults: sandbox code, or first active merchant)."""

    @jwt_required()
    def get(self):
        env = sasapay_service.environment
        merchant_code = request.args.get('merchant_code')

        if not merchant_code:
            if env == "production":
                merchants = sasapay_service.get_all_merchants()
                merchant_code = merchants[0]['code'] if merchants else None
            else:
                merchant_code = sasapay_service.sandbox_merchant_code

        merchant = sasapay_service.get_merchant(merchant_code) if merchant_code else None
        if not merchant:
            return {
                "error": "Merchant not found or not configured",
                "merchant_code": merchant_code,
                "environment": env
            }, 404

        result = sasapay_service.get_balance(merchant['code'])
        if not result.get('status'):
            return {
                "error": result.get('message', 'Balance fetch failed'),
                "environment": env,
                "merchant_code": merchant['code']
            }, 400

        d = result['data']
        return {
            "success": True,
            "environment": env,
            "merchant_code": merchant['code'],
            "merchant_name": merchant['name'],
            "currency": d.get('currency', 'KES'),
            "total_balance": d.get('total_balance', 0),
            "accounts": d.get('accounts', []),
            "message": d.get('message'),
            "timestamp": _now()
        }, 200


# ═════════════════════════════════════════════════════════════════════
#  Channel codes
# ═════════════════════════════════════════════════════════════════════
class SasaPayChannelCodesResource(Resource):

    @jwt_required()
    def get(self):
        env = sasapay_service.environment

        if current_app.config.get("SASAPAY_USE_MOCK", False):
            return self._mock_channel_codes(env)

        merchant_code = request.args.get('merchant_code')
        if not merchant_code:
            merchants = sasapay_service.get_all_merchants()
            merchant_code = merchants[0]['code'] if merchants else None

        if not merchant_code or not sasapay_service.get_merchant(merchant_code):
            return {"error": "No configured merchant available", "environment": env}, 404

        try:
            response = sasapay_service.get_channel_codes(merchant_code)

            if response.status_code == 200:
                return {
                    "success": True,
                    "environment": env,
                    "channels": self._format_channel_response(response.json())
                }, 200

            return {
                "error": "Failed to retrieve channel codes",
                "environment": env,
                "status_code": response.status_code,
                "details": response.text
            }, response.status_code

        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"SasaPay channel codes error: {str(e)}")
            return {"error": "Failed to connect to SasaPay", "environment": env, "details": str(e)}, 500
        except Exception as e:
            current_app.logger.error(f"Unexpected error: {str(e)}")
            return {"error": str(e), "environment": env}, 500

    def _format_channel_response(self, response_data):
        if isinstance(response_data, list):
            return response_data
        if isinstance(response_data, dict):
            for key in ("channel_codes", "channels", "data"):
                if key in response_data:
                    return response_data[key]
        return response_data

    def _mock_channel_codes(self, environment):
        channels = [
            {"network_code": "63902", "network_name": "M-PESA", "channel_type": "Mobile Money"},
            {"network_code": "63903", "network_name": "Airtel Money", "channel_type": "Mobile Money"},
            {"network_code": "0", "network_name": "SasaPay Wallet", "channel_type": "Wallet"}
        ]
        if environment == "production":
            channels.append({"network_code": "63904", "network_name": "T-Kash", "channel_type": "Mobile Money"})
        return {
            "success": True,
            "mock": True,
            "environment": environment,
            "warning": f"Mock {environment.upper()} data for testing only",
            "channels": channels
        }, 200


# ═════════════════════════════════════════════════════════════════════
#  Transaction statement
# ═════════════════════════════════════════════════════════════════════
class SasaPayTransactionStatementResource(Resource):
    """Transaction statement for a merchant account (production only)."""

    @jwt_required()
    def get(self):
        env = sasapay_service.environment
        merchant_code = request.args.get('merchant_code')
        account_number = request.args.get('account_number')

        try:
            page = int(request.args.get('page', 1))
            page_size = int(request.args.get('page_size', 50))
        except ValueError:
            return {"error": "page and page_size must be integers"}, 400

        if not merchant_code:
            return {
                "error": "merchant_code is required",
                "available_merchants": [m['code'] for m in sasapay_service.get_all_merchants()]
            }, 400

        if not account_number:
            account_number = merchant_code

        if env != "production":
            return {
                "error": "Transaction statements are only available in PRODUCTION environment",
                "environment": env,
                "message": "Please switch to production to fetch real transaction statements",
                "mock_data_available": True
            }, 400

        if current_app.config.get("SASAPAY_USE_MOCK", False):
            return self._mock_transaction_response(merchant_code, account_number, page, page_size)

        merchant = sasapay_service.get_merchant(merchant_code)
        if not merchant:
            return {
                "error": f"Merchant {merchant_code} not found or not configured",
                "environment": env,
                "available_merchants": [m['code'] for m in sasapay_service.get_all_merchants()]
            }, 404

        try:
            response = sasapay_service.get_transactions(merchant_code, account_number, page, page_size)

            if response.status_code != 200:
                return {
                    "error": "Failed to retrieve transaction statement",
                    "environment": env,
                    "merchant_code": merchant_code,
                    "status_code": response.status_code,
                    "details": response.text
                }, response.status_code

            data = response.json()
            if data.get('status') is True or data.get('statusCode') == '0':
                return {
                    "success": True,
                    "environment": env,
                    "merchant_code": merchant_code,
                    "merchant_name": merchant['name'],
                    "account_number": account_number,
                    "status": data.get('status'),
                    "responseCode": data.get('responseCode'),
                    "message": data.get('message'),
                    "count": data.get('count', 0),
                    "current_page": data.get('current_page', page),
                    "pages": data.get('pages', 1),
                    "links": data.get('links', {}),
                    "transactions": self._format_transaction_response(data),
                    "timestamp": _now()
                }, 200

            return {
                "error": data.get('message', 'Failed to retrieve transactions'),
                "environment": env,
                "merchant_code": merchant_code,
                "statusCode": data.get('statusCode')
            }, 400

        except Exception as e:
            current_app.logger.error(f"SasaPay transaction error for {merchant_code}: {str(e)}")
            return {"error": str(e), "environment": env, "merchant_code": merchant_code}, 500

    def _format_transaction_response(self, response_data):
        if 'data' in response_data and 'transactions' in response_data['data']:
            transaction_list = response_data['data']['transactions']
        else:
            transaction_list = response_data.get('transactions', [])

        transactions = []
        for tx in transaction_list:
            formatted_tx = {
                "id": tx.get('id'),
                "merchant_code": tx.get('merchant_code'),
                "transaction_amount": tx.get('transaction_amount', 0),
                "transaction_charges": tx.get('transaction_charges', 0),
                "transaction_type": tx.get('transaction_type'),
                "transaction_code": tx.get('transaction_code'),
                "transaction_description": tx.get('transaction_description'),
                "transaction_reference": tx.get('transaction_reference'),
                "transaction_date": tx.get('transaction_date'),
                "result_code": tx.get('result_code'),
                "result_description": tx.get('result_description'),
                "reversal_status": tx.get('reversal_status'),
                "created_date": tx.get('created_date')
            }
            pd = tx.get('payment_details')
            if pd:
                formatted_tx['payment_details'] = {
                    "party_B_account_number": pd.get('party_B_account_number'),
                    "party_B_account_name": pd.get('party_B_account_name'),
                    "channel_name": pd.get('channel_name'),
                    "channel_transaction_reference": pd.get('channel_transaction_reference')
                }
            transactions.append(formatted_tx)
        return transactions

    def _mock_transaction_response(self, merchant_code, account_number, page, page_size):
        types = ["TRANSACTION IN", "TRANSACTION OUT"]
        channels = ["M-PESA", "AIRTEL MONEY", "KCB", "Equity Bank", "SasaPay Wallet"]
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)

        mock = []
        for i in range(min(page_size, 50)):
            tx_date = start_date + timedelta(days=random.randint(0, 30))
            tx_type = random.choice(types)
            amount = round(random.uniform(10, 50000), 2)
            mock.append({
                "id": 10000 + i + ((page - 1) * page_size),
                "merchant_code": merchant_code,
                "transaction_amount": amount,
                "transaction_charges": round(amount * 0.01, 2) if tx_type == "TRANSACTION IN" else 0,
                "transaction_type": tx_type,
                "transaction_code": f"SPEJ{random.randint(10000, 99999)}Q7V2PD",
                "transaction_description": f"Payment to {merchant_code}",
                "transaction_reference": f"REF/{merchant_code}/{tx_date.strftime('%Y%m%d')}/{i}",
                "transaction_date": tx_date.strftime("%Y-%m-%d"),
                "payment_details": {
                    "party_B_account_number": account_number,
                    "party_B_account_name": merchant_code,
                    "channel_name": random.choice(channels),
                    "channel_transaction_reference": f"CH{random.randint(10000, 99999)}"
                },
                "result_code": "SP00000",
                "result_description": "Transaction completed successfully",
                "reversal_status": "NOT REVERSED",
                "created_date": tx_date.strftime("%Y-%m-%dT%H:%M:%S+03:00")
            })
        mock.sort(key=lambda x: x['transaction_date'], reverse=True)

        total_count = 137
        total_pages = (total_count + page_size - 1) // page_size
        base = f"/api/v2/waas/transactions/?merchantCode={merchant_code}&accountNumber={account_number}&page_size={page_size}"

        return {
            "success": True,
            "mock": True,
            "environment": "sandbox",
            "merchant_code": merchant_code,
            "account_number": account_number,
            "warning": "MOCK DATA - This is simulated transaction data for testing",
            "status": True,
            "responseCode": "0",
            "message": "Mock Transactions List",
            "count": total_count,
            "current_page": page,
            "pages": total_pages,
            "links": {
                "next": f"{base}&page={page + 1}" if page < total_pages else None,
                "previous": f"{base}&page={page - 1}" if page > 1 else None
            },
            "transactions": mock,
            "timestamp": _now()
        }, 200


# ═════════════════════════════════════════════════════════════════════
#  Diagnostics
# ═════════════════════════════════════════════════════════════════════
def _run_connection_test(merchant_code):
    """Token + balance check for one merchant. Never returns secrets or tokens."""
    steps = []

    try:
        sasapay_service.invalidate_token(merchant_code)
        token = sasapay_service._get_access_token(merchant_code, force_refresh=True)
        steps.append({
            "test_name": "Token Generation",
            "success": True,
            "details": {"token_length": len(token), "url": sasapay_service.token_url}
        })
    except Exception as e:
        steps.append({
            "test_name": "Token Generation",
            "success": False,
            "details": {"error": str(e), "url": sasapay_service.token_url}
        })
        return steps

    result = sasapay_service.get_balance(merchant_code)
    details = {"url": sasapay_service.balance_url, "merchant_code": merchant_code}
    if result.get('status'):
        d = result['data']
        details.update({
            "org_account_balance": d.get('total_balance'),
            "currency": d.get('currency'),
            "accounts": len(d.get('accounts', []))
        })
    else:
        details["error"] = result.get('message')
    steps.append({
        "test_name": f"Balance Fetch (Merchant: {merchant_code})",
        "success": bool(result.get('status')),
        "details": details
    })
    return steps


class TestSasaPayConnection(Resource):
    """Verify SasaPay token generation + balance for a merchant (?merchant_code=)."""

    @jwt_required()
    def get(self):
        env = sasapay_service.environment
        merchant_code = request.args.get('merchant_code')

        if not merchant_code:
            if env == "production":
                merchants = sasapay_service.get_all_merchants()
                merchant_code = merchants[0]['code'] if merchants else None
            else:
                merchant_code = sasapay_service.sandbox_merchant_code

        if not merchant_code or not sasapay_service.get_merchant(merchant_code):
            return {"error": "Merchant not configured", "environment": env}, 404

        results = {
            "test_time": _now(),
            "environment": env,
            "tests": _run_connection_test(merchant_code)
        }
        results["overall_success"] = all(t.get("success") for t in results["tests"])
        return results, 200 if results["overall_success"] else 500


class TestSasaPaySingleMerchant(Resource):
    """Live test for a single merchant code."""

    @jwt_required()
    def get(self, merchant_code):
        env = sasapay_service.environment

        if not sasapay_service.get_merchant(merchant_code):
            return {
                "error": f"Merchant {merchant_code} not found or not configured",
                "environment": env
            }, 404

        steps = _run_connection_test(merchant_code)
        success = all(s.get("success") for s in steps)
        return {
            "merchant_code": merchant_code,
            "environment": env,
            "timestamp": _now(),
            "success": success,
            "steps": steps
        }, 200 if success else 500


class TestNetworkConnectivity(Resource):
    """Network connectivity checks to SasaPay."""

    @jwt_required()
    def get(self):
        host = sasapay_service.host.replace("https://", "").replace("http://", "")
        results = {"tests": [], "timestamp": _now()}

        try:
            socket.gethostbyname(host)
            results["tests"].append({"test": "DNS Resolution", "status": "PASS", "message": f"{host} resolves"})
        except Exception as e:
            results["tests"].append({"test": "DNS Resolution", "status": "FAIL", "error": str(e)})

        try:
            response = requests.get(sasapay_service.host, timeout=10)
            results["tests"].append({
                "test": "HTTPS Connectivity",
                "status": "PASS",
                "status_code": response.status_code,
                "message": "Can reach SasaPay"
            })
        except Exception as e:
            results["tests"].append({"test": "HTTPS Connectivity", "status": "FAIL", "error": str(e)})

        return results, 200


# ═════════════════════════════════════════════════════════════════════
#  Transfers
# ═════════════════════════════════════════════════════════════════════
class SasaPayBusinessToBeneficiaryResource(Resource):

    @jwt_required()
    def post(self):
        """Transfer funds from one merchant to another merchant's beneficiary account."""
        data = request.get_json(silent=True) or {}

        required_fields = [
            'sender_merchant_code', 'receiver_merchant_code',
            'beneficiary_account_number', 'amount', 'callback_url'
        ]
        missing = [f for f in required_fields if f not in data]
        if missing:
            return {
                "error": f"Missing required fields: {', '.join(missing)}",
                "required_fields": required_fields
            }, 400

        env = sasapay_service.environment
        sender_code = data['sender_merchant_code']
        receiver_code = data['receiver_merchant_code']
        beneficiary = data['beneficiary_account_number']
        callback_url = data['callback_url']
        reference = data.get('transaction_reference') or _ref("B2B")

        try:
            amount = float(data['amount'])
            fee = float(data.get('transaction_fee', 0))
        except (TypeError, ValueError):
            return {"error": "amount and transaction_fee must be numbers"}, 400

        sender = sasapay_service.get_merchant(sender_code)
        if not sender:
            return {
                "error": f"Sender merchant {sender_code} not found or not configured",
                "environment": env
            }, 404

        try:
            url = f"{sasapay_service.api_root}/transfers/business-to-beneficiary"
            payload = {
                "TransactionReference": reference,
                "SenderMerchantCode": sender_code,
                "ReceiverMerchantCode": receiver_code,
                "BeneficiaryAccountNumber": beneficiary,
                "Amount": amount,
                "TransactionFee": fee,
                "Reason": data.get('reason', ''),
                "CallBackUrl": callback_url
            }

            response = sasapay_service._request('POST', url, sender_code, json=payload)

            if response.status_code == 200:
                body = response.json()
                if body.get('status') is True:
                    return {
                        "success": True,
                        "sender_merchant_code": sender_code,
                        "sender_merchant_name": sender['name'],
                        "receiver_merchant_code": receiver_code,
                        "beneficiary_account_number": beneficiary,
                        "amount": amount,
                        "currency": "KES",
                        "transaction_reference": reference,
                        "checkout_request_id": body.get('checkoutRequestId'),
                        "merchant_request_id": body.get('merchantRequestID'),
                        "message": body.get('message', 'Transaction is being processed'),
                        "environment": env,
                        "status": "pending",
                        "timestamp": _now()
                    }, 200

                return {
                    "success": False,
                    "sender_merchant_code": sender_code,
                    "error": body.get('message', 'B2B transfer failed'),
                    "environment": env
                }, 400

            current_app.logger.error(f"B2B transfer failed: HTTP {response.status_code} - {response.text}")
            return {
                "success": False,
                "error": f"SasaPay API returned {response.status_code}",
                "details": response.text,
                "environment": env
            }, response.status_code

        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"Network error: {str(e)}")
            return {"error": "Failed to connect to SasaPay", "details": str(e), "environment": env}, 500
        except Exception as e:
            current_app.logger.error(f"Unexpected error: {str(e)}")
            return {"error": str(e), "environment": env}, 500


class SasaPayTransferResource(Resource):
    """Initiate a B2C transfer from a merchant account to a phone number."""

    @jwt_required()
    def post(self):
        data = request.get_json(silent=True)
        if not data:
            return {"error": "Missing request body", "message": "Please provide transfer details"}, 400

        required_fields = ['merchant_code', 'amount', 'receiver_number', 'reason']
        missing = [f for f in required_fields if f not in data]
        if missing:
            return {
                "error": "Missing required fields",
                "missing_fields": missing,
                "required_fields": required_fields
            }, 400

        env = sasapay_service.environment
        merchant_code = data['merchant_code']
        currency = data.get('currency', 'KES')

        try:
            amount = float(data['amount'])
        except (TypeError, ValueError):
            return {"error": "amount must be a number"}, 400
        if amount <= 0:
            return {"error": "amount must be greater than 0"}, 400

        merchant = sasapay_service.get_merchant(merchant_code)
        if not merchant:
            return {"error": f"Merchant {merchant_code} not found or not configured", "environment": env}, 404

        reference = _ref("B2C")

        try:
            result = sasapay_service.initiate_b2c_payment(
                sender_merchant_code=merchant_code,
                transaction_reference=reference,
                amount=amount,
                receiver_number=data['receiver_number'],
                reason=data['reason'],
                callback_url=data.get('callback_url'),
                channel=data.get('channel', '0')
            )

            if not result.get('status'):
                return {
                    "error": "Transfer failed",
                    "message": result.get('message', 'Could not initiate B2C transfer'),
                    "details": result.get('response'),
                    "environment": env
                }, 400

            d = result['data']
            return {
                "success": True,
                "transaction": {
                    "status": True,
                    "b2c_request_id": d.get('B2CRequestID'),
                    "conversation_id": d.get('ConversationID'),
                    "originator_conversation_id": d.get('OriginatorConversationID'),
                    "response_code": d.get('ResponseCode'),
                    "response_description": d.get('ResponseDescription'),
                    "transaction_charges": d.get('TransactionCharges') or '0.00',
                    "transaction_reference": reference
                },
                "merchant": {"code": merchant_code, "name": merchant['name']},
                "payment": {
                    "amount": amount,
                    "currency": currency,
                    "receiver_number": d.get('receiver_number')
                },
                "timestamp": _now()
            }, 200

        except Exception as e:
            current_app.logger.error(f"B2C transfer error: {str(e)}")
            return {"error": "Transfer processing error", "message": str(e), "environment": env}, 500


class SasaPayTransferStatusResource(Resource):
    """
    Check the status of a B2C transfer.
    Query params: merchant_code (required), transaction_id (or in the URL).
    """

    @jwt_required()
    def get(self, transaction_id=None):
        merchant_code = request.args.get('merchant_code')
        transaction_id = transaction_id or request.args.get('transaction_id')

        if not merchant_code:
            return {"error": "merchant_code is required"}, 400
        if not transaction_id:
            return {"error": "transaction_id is required"}, 400

        env = sasapay_service.environment

        if not sasapay_service.get_merchant(merchant_code):
            return {"error": f"Merchant {merchant_code} not found", "environment": env}, 404

        try:
            response = sasapay_service.check_b2c_status(merchant_code, transaction_id)

            if response.status_code == 200:
                return {
                    "success": True,
                    "transaction_status": response.json(),
                    "merchant_code": merchant_code,
                    "environment": env,
                    "timestamp": _now()
                }, 200

            return {
                "error": "Status check failed",
                "status_code": response.status_code,
                "message": response.text
            }, response.status_code

        except Exception as e:
            current_app.logger.error(f"Status check error: {str(e)}")
            return {"error": str(e)}, 500


class SasaPayTransferFundsResource(Resource):
    """
    Unified endpoint to move funds OUT of one of your SasaPay merchant
    accounts. POST body must include 'transfer_type':

      - "paybill"  -> requires: paybill_number, account_reference
      - "till"     -> requires: till_number
      - "merchant" -> requires: receiver_merchant_code
      - "b2c"      -> requires: receiver_number
      - "b2b"      -> requires: receiver_merchant_code

    Common fields: sender_merchant_code, amount
    Optional: transaction_reference, callback_url, reason
    """

    @jwt_required()
    def post(self):
        data = request.get_json(silent=True) or {}

        transfer_type = (data.get('transfer_type') or '').lower().strip()
        valid_types = {'paybill', 'till', 'merchant', 'b2c', 'b2b'}

        if transfer_type not in valid_types:
            return {
                "error": f"Invalid or missing 'transfer_type'. Must be one of: {sorted(valid_types)}"
            }, 400

        sender_merchant_code = data.get('sender_merchant_code')
        amount = data.get('amount')

        if not sender_merchant_code:
            return {"error": "sender_merchant_code is required"}, 400
        if amount is None:
            return {"error": "amount is required"}, 400

        try:
            amount = float(amount)
        except (TypeError, ValueError):
            return {"error": "amount must be a number"}, 400
        if amount <= 0:
            return {"error": "amount must be greater than 0"}, 400

        if not sasapay_service.get_merchant(sender_merchant_code):
            return {
                "error": f"Sender merchant {sender_merchant_code} not found or not configured",
                "environment": sasapay_service.environment
            }, 404

        transaction_reference = data.get('transaction_reference') or _ref(transfer_type.upper())
        callback_url = data.get('callback_url')
        reason = data.get('reason', 'Funds transfer')

        current_app.logger.info(
            f"[TRANSFER] type={transfer_type} sender={sender_merchant_code} "
            f"amount={amount} ref={transaction_reference}"
        )

        handlers = {
            'paybill': self._handle_paybill,
            'till': self._handle_till,
            'merchant': self._handle_merchant,
            'b2c': self._handle_b2c,
            'b2b': self._handle_b2b,
        }

        try:
            result = handlers[transfer_type](
                data, sender_merchant_code, transaction_reference, amount, callback_url, reason
            )
        except ValueError as ve:
            return {"error": str(ve)}, 400
        except Exception as e:
            current_app.logger.error(f"[TRANSFER] Unhandled exception: {str(e)}")
            return {"error": f"Transfer failed: {str(e)}"}, 500

        response = {
            "success": result.get('status', False),
            "transfer_type": transfer_type,
            "sender_merchant_code": sender_merchant_code,
            "amount": amount,
            "currency": "KES",
            "transaction_reference": transaction_reference,
            "timestamp": _now()
        }

        if result.get('status'):
            response["data"] = result.get('data')
        else:
            response["error"] = result.get('message', 'Transfer failed')
            if result.get('response'):
                response["details"] = result.get('response')

        return response, 200 if result.get('status') else 400

    def _handle_paybill(self, data, sender, ref, amount, callback_url, reason):
        paybill_number = data.get('paybill_number')
        account_reference = data.get('account_reference')
        if not paybill_number:
            raise ValueError("paybill_number is required for transfer_type='paybill'")
        if not account_reference:
            raise ValueError("account_reference is required for transfer_type='paybill'")

        return sasapay_service.pay_paybill(
            sender_merchant_code=sender,
            transaction_reference=ref,
            amount=amount,
            paybill_number=paybill_number,
            account_reference=account_reference,
            callback_url=callback_url,
            reason=reason,
            channel=data.get('channel', '63902')
        )

    def _handle_till(self, data, sender, ref, amount, callback_url, reason):
        till_number = data.get('till_number')
        if not till_number:
            raise ValueError("till_number is required for transfer_type='till'")

        return sasapay_service.pay_till(
            sender_merchant_code=sender,
            transaction_reference=ref,
            amount=amount,
            till_number=till_number,
            account_reference=data.get('account_reference', till_number),
            callback_url=callback_url,
            reason=reason,
            channel=data.get('channel', '63902')
        )

    def _handle_merchant(self, data, sender, ref, amount, callback_url, reason):
        receiver = data.get('receiver_merchant_code')
        if not receiver:
            raise ValueError("receiver_merchant_code is required for transfer_type='merchant'")

        return sasapay_service.transfer_to_merchant(
            sender_merchant_code=sender,
            transaction_reference=ref,
            amount=amount,
            receiver_merchant_code=receiver,
            account_reference=data.get('account_reference', receiver),
            callback_url=callback_url,
            reason=reason
        )

    def _handle_b2c(self, data, sender, ref, amount, callback_url, reason):
        receiver_number = data.get('receiver_number')
        if not receiver_number:
            raise ValueError("receiver_number is required for transfer_type='b2c'")

        return sasapay_service.initiate_b2c_payment(
            sender_merchant_code=sender,
            transaction_reference=ref,
            amount=amount,
            receiver_number=receiver_number,
            reason=reason,
            callback_url=callback_url,
            channel=data.get('channel', '0')
        )

    def _handle_b2b(self, data, sender, ref, amount, callback_url, reason):
        receiver = data.get('receiver_merchant_code')
        if not receiver:
            raise ValueError("receiver_merchant_code is required for transfer_type='b2b'")

        return sasapay_service.initiate_b2b_transfer(
            sender_merchant_code=sender,
            transaction_reference=ref,
            amount=amount,
            receiver_merchant_code=receiver,
            account_reference=data.get('account_reference', receiver),
            receiver_account_type=data.get('receiver_account_type', 'PAYBILL'),
            network_code=data.get('network_code', '0'),
            callback_url=callback_url,
            reason=reason
        )


# ═════════════════════════════════════════════════════════════════════
#  Batch operations
# ═════════════════════════════════════════════════════════════════════
class SasaPayBatchTransferResource(Resource):
    """
    Transfer funds from MULTIPLE merchant accounts into ONE receiving merchant.

    POST body:
      {
        "sender_merchant_codes": ["570257", "577960"],
        "receiver_merchant_code": "577666",
        "amount": 15000,
        "allocation_strategy": "equal" | "balance",   # default "equal"
        "reason": "...",
        "callback_url": "..."
      }

    equal   -> split evenly (rounding remainder goes to the last sender)
    balance -> pull from each sender in order, up to its balance, until covered
    """

    @jwt_required()
    def post(self):
        data = request.get_json(silent=True) or {}

        sender_codes = data.get('sender_merchant_codes')
        receiver_code = data.get('receiver_merchant_code')
        amount = data.get('amount')
        strategy = (data.get('allocation_strategy') or 'equal').lower().strip()
        reason = data.get('reason', 'Batch merchant transfer')
        callback_url = data.get('callback_url')

        if not sender_codes or not isinstance(sender_codes, list):
            return {"error": "sender_merchant_codes must be a non-empty list"}, 400

        sender_codes = [str(c).strip() for c in sender_codes if str(c).strip()]
        if not sender_codes:
            return {"error": "sender_merchant_codes must be a non-empty list"}, 400
        if not receiver_code:
            return {"error": "receiver_merchant_code is required"}, 400
        receiver_code = str(receiver_code).strip()
        if receiver_code in sender_codes:
            return {"error": "receiver_merchant_code cannot also be a sender"}, 400
        if len(set(sender_codes)) != len(sender_codes):
            return {"error": "sender_merchant_codes contains duplicates"}, 400
        if amount is None:
            return {"error": "amount is required"}, 400

        try:
            amount = round(float(amount), 2)
        except (TypeError, ValueError):
            return {"error": "amount must be a number"}, 400
        if amount <= 0:
            return {"error": "amount must be greater than 0"}, 400
        if strategy not in {'equal', 'balance'}:
            return {"error": "allocation_strategy must be 'equal' or 'balance'"}, 400

        # Every merchant involved must be configured
        unknown = [c for c in sender_codes + [receiver_code] if not sasapay_service.get_merchant(c)]
        if unknown:
            return {
                "error": f"Merchants not found or not configured: {unknown}",
                "environment": sasapay_service.environment
            }, 404

        current_app.logger.info(
            f"[BATCH TRANSFER] senders={sender_codes} receiver={receiver_code} "
            f"total_amount={amount} strategy={strategy}"
        )

        try:
            if strategy == 'equal':
                allocations = self._allocate_equal(sender_codes, amount)
            else:
                allocations, shortfall, balances = self._allocate_by_balance(sender_codes, amount)
                if shortfall > 0:
                    return {
                        "error": f"Combined available balance of selected merchants is short by KES {shortfall:,.2f}",
                        "requested_amount": amount,
                        "allocatable_amount": round(amount - shortfall, 2),
                        "balances": balances
                    }, 400
        except Exception as e:
            current_app.logger.error(f"[BATCH TRANSFER] Allocation error: {str(e)}")
            return {"error": f"Failed to compute allocation: {str(e)}"}, 500

        legs = []
        successful_amount = 0.0

        for sender_code, leg_amount in allocations:
            if leg_amount <= 0:
                continue

            leg_reference = f"BATCH{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{str(uuid.uuid4())[:6]}"

            try:
                result = sasapay_service.transfer_to_merchant(
                    sender_merchant_code=sender_code,
                    transaction_reference=leg_reference,
                    amount=leg_amount,
                    receiver_merchant_code=receiver_code,
                    account_reference=receiver_code,
                    callback_url=callback_url,
                    reason=reason
                )
            except Exception as e:
                result = {'status': False, 'message': str(e)}

            ok = bool(result.get('status'))
            if ok:
                successful_amount += leg_amount

            legs.append({
                "sender_merchant_code": sender_code,
                "amount": leg_amount,
                "transaction_reference": leg_reference,
                "success": ok,
                "data": result.get('data') if ok else None,
                "error": None if ok else result.get('message', 'Transfer failed')
            })

        overall = len(legs) > 0 and all(leg["success"] for leg in legs)

        return {
            "success": overall,
            "receiver_merchant_code": receiver_code,
            "requested_amount": amount,
            "allocated_amount": round(successful_amount, 2),
            "currency": "KES",
            "allocation_strategy": strategy,
            "legs": legs,
            "timestamp": _now()
        }, 200 if overall else 207  # 207 = partial success

    def _allocate_equal(self, sender_codes, amount):
        n = len(sender_codes)
        share = round(amount / n, 2)
        allocations = [(code, share) for code in sender_codes[:-1]]
        last_share = round(amount - round(share * (n - 1), 2), 2)
        allocations.append((sender_codes[-1], last_share))
        return allocations

    def _allocate_by_balance(self, sender_codes, amount):
        """Returns (allocations, shortfall, balances_debug)."""
        remaining = amount
        allocations = []
        balances = {}

        for code in sender_codes:
            balance = self._get_merchant_balance(code)
            balances[code] = balance

            if remaining <= 0:
                allocations.append((code, 0))
                continue

            take = round(min(balance, remaining), 2)
            allocations.append((code, take))
            remaining = round(remaining - take, 2)

        return allocations, max(remaining, 0), balances

    def _get_merchant_balance(self, merchant_code):
        result = sasapay_service.get_balance(merchant_code)
        if result.get('status'):
            try:
                return float(result['data'].get('total_balance') or 0)
            except (TypeError, ValueError):
                return 0.0
        current_app.logger.warning(
            f"[BATCH TRANSFER] Could not fetch balance for {merchant_code}: {result.get('message')}"
        )
        return 0.0


class SasaPayBatchUtilityFundingResource(Resource):
    """
    Fund MULTIPLE merchants' UTILITY accounts in one call. Each merchant's
    working balance moves INTO its own utility account (money never crosses
    between merchants). SasaPay debits B2C payments from the UTILITY account.

    POST body — two supported shapes:

      (A) {"allocations": [{"merchant_code": "570257", "amount": 9.02}, ...], "reason": "..."}
      (B) {"merchant_codes": ["570257", "577960"], "amount": 5000, "reason": "..."}
    """

    @jwt_required()
    def post(self):
        data = request.get_json(silent=True) or {}

        reason = data.get('reason', 'Batch utility funding')
        allocations = data.get('allocations')
        merchant_codes = data.get('merchant_codes')
        amount = data.get('amount')

        try:
            if allocations is not None:
                if not isinstance(allocations, list) or not allocations:
                    return {"error": "allocations must be a non-empty list"}, 400

                normalised = []
                seen = set()
                for entry in allocations:
                    if not isinstance(entry, dict):
                        return {"error": "each allocation must be an object"}, 400

                    code = str(entry.get('merchant_code') or '').strip()
                    if not code:
                        return {"error": "each allocation needs a merchant_code"}, 400
                    if code in seen:
                        return {"error": f"duplicate merchant_code: {code}"}, 400
                    seen.add(code)

                    try:
                        amt = round(float(entry.get('amount')), 2)
                    except (TypeError, ValueError):
                        return {"error": f"invalid amount for merchant {code}"}, 400
                    if amt <= 0:
                        return {"error": f"amount must be > 0 for merchant {code}"}, 400

                    normalised.append((code, amt))

            elif merchant_codes is not None and amount is not None:
                if not isinstance(merchant_codes, list) or not merchant_codes:
                    return {"error": "merchant_codes must be a non-empty list"}, 400

                merchant_codes = [str(c).strip() for c in merchant_codes if str(c).strip()]
                if not merchant_codes:
                    return {"error": "merchant_codes must be a non-empty list"}, 400
                if len(set(merchant_codes)) != len(merchant_codes):
                    return {"error": "merchant_codes contains duplicates"}, 400

                try:
                    amt = round(float(amount), 2)
                except (TypeError, ValueError):
                    return {"error": "amount must be a number"}, 400
                if amt <= 0:
                    return {"error": "amount must be greater than 0"}, 400

                normalised = [(code, amt) for code in merchant_codes]

            else:
                return {
                    "error": "Provide either 'allocations' (per-merchant amounts) "
                             "or 'merchant_codes' + 'amount'"
                }, 400

        except Exception as e:
            current_app.logger.error(f"[BATCH UTILITY FUNDING] Payload error: {str(e)}")
            return {"error": f"Invalid payload: {str(e)}"}, 400

        unknown = [c for c, _ in normalised if not sasapay_service.get_merchant(c)]
        if unknown:
            return {
                "error": f"Merchants not found or not configured: {unknown}",
                "environment": sasapay_service.environment
            }, 404

        current_app.logger.info(
            f"[BATCH UTILITY FUNDING] merchants={[c for c, _ in normalised]} legs={len(normalised)}"
        )

        legs = []
        successful_count = 0
        total_moved = 0.0

        for merchant_code, leg_amount in normalised:
            try:
                result = sasapay_service.move_to_utility_account(
                    merchant_code=merchant_code,
                    amount=leg_amount
                )
            except Exception as e:
                result = {'status': False, 'message': str(e)}

            ok = bool(result.get('status'))
            if ok:
                successful_count += 1
                total_moved += leg_amount

            legs.append({
                "merchant_code": merchant_code,
                "amount": leg_amount,
                "success": ok,
                "data": result.get('data') if ok else None,
                "error": None if ok else result.get('message', 'Fund movement failed')
            })

        overall = len(legs) > 0 and all(leg["success"] for leg in legs)

        return {
            "success": overall,
            "merchant_count": len(normalised),
            "successful_count": successful_count,
            "failed_count": len(legs) - successful_count,
            "total_moved": round(total_moved, 2),
            "currency": "KES",
            "reason": reason,
            "legs": legs,
            "timestamp": _now()
        }, 200 if overall else 207  # 207 = partial success