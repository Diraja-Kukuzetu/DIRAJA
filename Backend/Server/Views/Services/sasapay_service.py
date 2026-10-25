# Server/Views/Services/sasapay_service.py

import os
import re
import json
import time
import logging
from datetime import datetime

import requests
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)


class SasaPayPaymentService:
    """
    SasaPay API client.

    Credentials source:
      - production: SasaPayMerchantConfig table (Fernet-encrypted)
      - sandbox:    SASAPAY_SANDBOX_CLIENT_ID / SASAPAY_SANDBOX_CLIENT_SECRET env vars
                    (the sandbox has a single shared test merchant)

    All DB access happens at call time, so every method must run inside
    a Flask app context (i.e. inside a request).
    """

    def __init__(self):
        self.environment = os.getenv("SASAPAY_ENVIRONMENT", "sandbox").lower().strip()

        # ===== BASE URLs (normalised: works whether or not env var ends in /api/v1) =====
        if self.environment == "production":
            raw = os.getenv("SASAPAY_PRODUCTION_BASE_URL", "https://api.sasapay.app")
        else:
            raw = os.getenv("SASAPAY_SANDBOX_BASE_URL", "https://sandbox.sasapay.app")
        raw = raw.rstrip("/")
        if raw.endswith("/api/v1"):
            raw = raw[: -len("/api/v1")]

        self.host = raw                      # https://api.sasapay.app
        self.base_url = raw                  # legacy alias (host only)
        self.api_root = f"{raw}/api/v1"      # https://api.sasapay.app/api/v1

        self.token_url = f"{self.api_root}/auth/token/"
        self.payment_url = f"{self.api_root}/payments/request-payment/"
        self.status_url = f"{self.api_root}/payments/status/"
        self.process_url = f"{self.api_root}/payments/process-payment/"
        self.b2b_url = f"{self.api_root}/payments/b2b/"
        self.b2c_url = f"{self.api_root}/payments/b2c/"
        self.balance_url = f"{self.api_root}/payments/check-balance/"
        self.fund_movement_url = f"{self.api_root}/transactions/fund-movement/"
        self.transactions_url = f"{self.host}/api/v2/waas/transactions/"

        self.sandbox_merchant_code = os.getenv("SASAPAY_SANDBOX_MERCHANT_CODE", "600980")

        # Token cache: {merchant_code: (token, expires_at_epoch)}
        self._token_cache = {}
        self.default_token_ttl = 3600

        # ===== NETWORK CODE MAPPING =====
        self.network_mapping = {
            'safaricom': '63902',
            'mpesa': '63902',
            'm-pesa': '63902',
            'airtel': '63903',
            'airtel money': '63903',
            'telkom': '63904',
            't-kash': '63904',
            'tkash': '63904',
            'equitel': '63905',
            'sasapay': '0'
        }

        logger.info(
            f"[SASAPAY] Service initialised | env={self.environment} | api_root={self.api_root}"
        )

    # ─────────────────────────────────────────────────────────────────
    #  Merchant / credential lookup (DB-backed)
    # ─────────────────────────────────────────────────────────────────
    def _sandbox_merchant(self, merchant_code=None):
        client_id = os.getenv("SASAPAY_SANDBOX_CLIENT_ID")
        client_secret = os.getenv("SASAPAY_SANDBOX_CLIENT_SECRET")
        if not client_id or not client_secret:
            logger.error("[SASAPAY] Sandbox credentials missing in env")
            return None
        return {
            "code": str(merchant_code or self.sandbox_merchant_code),
            "name": "SasaPay Sandbox Merchant",
            "location": "Sandbox",
            "type": "test",
            "base_url": self.api_root,
            "client_id": client_id,
            "client_secret": client_secret,
        }

    def _merchant_from_config(self, cfg):
        """Turn a SasaPayMerchantConfig row into the merchant dict used everywhere."""
        try:
            client_id = cfg.get_client_id()
            client_secret = cfg.get_client_secret()
        except Exception as e:
            # Usually a wrong/rotated SASAPAY_ENCRYPTION_KEY
            logger.error(
                f"[SASAPAY] Could not decrypt credentials for merchant "
                f"{cfg.merchant_code}: {type(e).__name__}"
            )
            return None

        if not client_id or not client_secret:
            logger.error(f"[SASAPAY] Merchant {cfg.merchant_code} has no stored credentials")
            return None

        return {
            "code": cfg.merchant_code,
            "name": cfg.merchant_name or cfg.merchant_code,
            "location": cfg.location or "",
            "type": cfg.merchant_type or "shop",
            "base_url": self.api_root,
            "client_id": client_id,
            "client_secret": client_secret,
            "shop_id": cfg.shop_id,
        }

    def get_merchant(self, merchant_code):
        """
        Return the merchant dict (with decrypted credentials) or None.
        Sandbox: always the shared sandbox credentials.
        Production: active row in sasapay_merchant_configs.
        """
        if merchant_code is None:
            return None
        code = str(merchant_code).strip()

        if self.environment != "production":
            return self._sandbox_merchant(code)

        from Server.Models.SasaPayMerchantConfig import SasaPayMerchantConfig
        cfg = SasaPayMerchantConfig.get_by_merchant_code(code)
        if not cfg:
            logger.error(f"[SASAPAY] No active merchant config in DB for {code}")
            return None
        return self._merchant_from_config(cfg)

    def get_all_merchants(self):
        """All usable merchants for the current environment."""
        if self.environment != "production":
            m = self._sandbox_merchant()
            return [m] if m else []

        from Server.Models.SasaPayMerchantConfig import SasaPayMerchantConfig
        merchants = []
        for cfg in SasaPayMerchantConfig.list_active():
            m = self._merchant_from_config(cfg)
            if m:
                merchants.append(m)
            else:
                logger.warning(f"[SASAPAY] Skipping merchant {cfg.merchant_code}: unusable credentials")
        return merchants

    def _get_merchant_credentials(self, merchant_code):
        merchant = self.get_merchant(merchant_code)
        if not merchant:
            raise Exception(
                f"Merchant {merchant_code} is not configured for "
                f"{self.environment} environment"
            )
        return merchant["client_id"], merchant["client_secret"]

    # ─────────────────────────────────────────────────────────────────
    #  Helpers
    # ─────────────────────────────────────────────────────────────────
    def _get_merchant_callback_url(self, merchant_code):
        """
        Callback URL resolution order:
          1. SASAPAY_MERCHANT_<code>_CALLBACK_URL (optional override)
          2. SASAPAY_CALLBACK_URL
          3. BASE_URL + /api/diraja/sasapay/callback
        """
        callback_url = (
            os.getenv(f"SASAPAY_MERCHANT_{merchant_code}_CALLBACK_URL")
            or os.getenv("SASAPAY_CALLBACK_URL")
        )
        if not callback_url:
            base_url = os.getenv("BASE_URL", "https://app.kukuzetu.co.ke")
            callback_url = f"{base_url}/api/diraja/sasapay/callback"

        if not callback_url.endswith('/sasapay/callback'):
            if callback_url.endswith('/api/diraja'):
                callback_url = f"{callback_url}/sasapay/callback"
            elif callback_url.endswith('/api/diraja/'):
                callback_url = f"{callback_url}sasapay/callback"
            elif not callback_url.endswith('callback'):
                callback_url = f"{callback_url}/api/diraja/sasapay/callback"

        return callback_url

    def _format_phone_number(self, phone_number):
        """Format phone number to 254XXXXXXXXX"""
        if not phone_number:
            return None
        phone_number = re.sub(r'\D', '', str(phone_number))
        if phone_number.startswith('0'):
            phone_number = '254' + phone_number[1:]
        elif not phone_number.startswith('254'):
            phone_number = '254' + phone_number
        return phone_number

    def _get_network_code(self, network_input):
        """Get network code from various input formats"""
        if not network_input:
            return '63902'  # default M-PESA

        network_input = str(network_input).lower().strip()

        if network_input in ['63902', '63903', '63904', '63905', '63907', '0']:
            return network_input

        for key, code in self.network_mapping.items():
            if key in network_input or network_input in key:
                return code

        logger.warning(f"[SASAPAY] Unknown network '{network_input}', defaulting to M-PESA (63902)")
        return '63902'

    # ─────────────────────────────────────────────────────────────────
    #  Auth
    # ─────────────────────────────────────────────────────────────────
    def _get_access_token(self, merchant_code, force_refresh=False):
        """Get access token (GET + Basic Auth) using this merchant's DB credentials."""
        cache_key = f"{self.environment}:{merchant_code}"

        if not force_refresh:
            cached = self._token_cache.get(cache_key)
            if cached and time.time() < cached[1]:
                return cached[0]

        client_id, client_secret = self._get_merchant_credentials(merchant_code)

        try:
            response = requests.get(
                self.token_url,
                auth=HTTPBasicAuth(client_id, client_secret),
                params={'grant_type': 'client_credentials'},
                headers={'Accept': 'application/json'},
                timeout=30
            )
        except Exception as e:
            logger.error(f"[SASAPAY AUTH] Request error for merchant {merchant_code}: {e}")
            raise

        if response.status_code == 200:
            token_data = response.json()
            access_token = token_data.get('access_token')
            if not access_token:
                raise Exception(f"No access token in response for merchant {merchant_code}")

            try:
                ttl = int(token_data.get('expires_in') or self.default_token_ttl)
            except (TypeError, ValueError):
                ttl = self.default_token_ttl
            self._token_cache[cache_key] = (access_token, time.time() + max(ttl - 60, 30))
            logger.info(f"[SASAPAY AUTH] Token obtained for merchant {merchant_code}")
            return access_token

        if response.status_code == 401:
            raise Exception(f"Invalid credentials for merchant {merchant_code}")

        raise Exception(
            f"Token request failed ({response.status_code}) for merchant {merchant_code}: "
            f"{response.text[:300]}"
        )

    def invalidate_token(self, merchant_code):
        self._token_cache.pop(f"{self.environment}:{merchant_code}", None)

    def auth_headers(self, merchant_code):
        return {
            'Authorization': f'Bearer {self._get_access_token(merchant_code)}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

    def _request(self, method, url, merchant_code, **kwargs):
        """Authenticated request; refreshes the token once on a 401."""
        kwargs.setdefault('timeout', 30)
        response = requests.request(method, url, headers=self.auth_headers(merchant_code), **kwargs)
        if response.status_code == 401:
            self.invalidate_token(merchant_code)
            self._get_access_token(merchant_code, force_refresh=True)
            response = requests.request(method, url, headers=self.auth_headers(merchant_code), **kwargs)
        return response

    # ─────────────────────────────────────────────────────────────────
    #  Balance / statements / status
    # ─────────────────────────────────────────────────────────────────
    def get_balance(self, merchant_code):
        """
        Returns {'status': True, 'data': {...}} or {'status': False, 'message': str}
        """
        try:
            response = self._request(
                'GET', self.balance_url, merchant_code,
                params={"MerchantCode": merchant_code}
            )
            if response.status_code != 200:
                logger.error(f"[SASAPAY] Balance HTTP {response.status_code} for {merchant_code}")
                return {
                    'status': False,
                    'message': f'Balance fetch failed: HTTP {response.status_code}',
                    'response': response.text[:300]
                }

            body = response.json()
            if str(body.get('statusCode')) != '0':
                return {'status': False, 'message': body.get('message') or 'Balance fetch failed'}

            data = body.get('data', {}) or {}
            return {
                'status': True,
                'data': {
                    'currency': data.get('CurrencyCode', 'KES'),
                    'total_balance': data.get('OrgAccountBalance', 0),
                    'accounts': data.get('Accounts', []),
                    'message': body.get('message', 'Account Balances'),
                    'statusCode': body.get('statusCode')
                }
            }
        except Exception as e:
            logger.error(f"[SASAPAY] Balance error for {merchant_code}: {e}")
            return {'status': False, 'message': str(e)}

    def get_transactions(self, merchant_code, account_number, page=1, page_size=50):
        response = self._request(
            'GET', self.transactions_url, merchant_code,
            params={
                "merchantCode": merchant_code,
                "accountNumber": account_number,
                "page": page,
                "page_size": page_size
            }
        )
        return response

    # ─────────────────────────────────────────────────────────────────
    #  Statement fetching (shared by reconciliation + statement sales)
    # ─────────────────────────────────────────────────────────────────
    @staticmethod
    def _parse_statement_dt(raw):
        if not raw:
            return None
        raw = str(raw)[:19].replace("T", " ")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
        return None

    def _normalise_statement_tx(self, tx):
        dt = (
            self._parse_statement_dt(tx.get("created_date"))
            or self._parse_statement_dt(tx.get("transaction_date") or tx.get("Date"))
        )
        if not dt:
            return None
        pd = tx.get("payment_details") or {}
        try:
            amount = float(tx.get("transaction_amount", tx.get("Amount", 0)) or 0)
        except (TypeError, ValueError):
            amount = 0.0
        return {
            "code": str(tx.get("transaction_code") or tx.get("Code") or "").strip().upper(),
            "amount": amount,
            "type": str(tx.get("transaction_type") or "").upper(),
            "datetime": dt,
            "date": dt.date(),
            "reference": tx.get("transaction_reference") or tx.get("Reference"),
            "description": tx.get("transaction_description"),
            "channel": pd.get("channel_name") or tx.get("Channel"),
            "result_code": tx.get("result_code"),
            "result_description": tx.get("result_description") or tx.get("Status"),
            "reversal_status": tx.get("reversal_status"),
            "payment_details": pd,
        }

    def fetch_statement_range(self, merchant_code, start_date, end_date,
                              page_size=100, max_pages=100):
        """
        Paginate the merchant statement (newest first) and return normalised rows
        with start_date <= date <= end_date. Raises Exception on HTTP failure.
        """
        results = []
        page = 1
        while page <= max_pages:
            resp = self.get_transactions(
                merchant_code, merchant_code, page=page, page_size=page_size
            )
            if resp.status_code != 200:
                raise Exception(
                    f"Statement fetch failed (HTTP {resp.status_code}): {resp.text[:200]}"
                )

            body = resp.json()
            data = body.get("data")
            raw_txs = (
                data.get("transactions") if isinstance(data, dict) else body.get("transactions")
            ) or []
            if not raw_txs:
                break

            page_min = None
            for tx in raw_txs:
                n = self._normalise_statement_tx(tx)
                if not n:
                    continue
                page_min = n["date"] if page_min is None else min(page_min, n["date"])
                if start_date <= n["date"] <= end_date:
                    results.append(n)

            if page_min and page_min < start_date:
                break
            if page >= int(body.get("pages", 1) or 1):
                break
            page += 1

        return results

    def get_channel_codes(self, merchant_code):
        return self._request(
            'GET', f"{self.api_root}/payments/channel-codes/", merchant_code
        )

    def check_b2c_status(self, merchant_code, transaction_id):
        return self._request(
            'POST', self.status_url, merchant_code,
            json={"MerchantCode": merchant_code, "B2CRequestID": transaction_id}
        )

    # ─────────────────────────────────────────────────────────────────
    #  C2B payment request
    # ─────────────────────────────────────────────────────────────────
    def initiate_payment(self, merchant_code, transaction_reference, amount,
                         sender_account_number, receiver_merchant_code,
                         account_reference, network_code, callback_url, reason):
        """Initiate a SasaPay C2B payment request."""
        try:
            actual_merchant_code = merchant_code
            if self.environment == "sandbox":
                actual_merchant_code = self.sandbox_merchant_code

            if not callback_url:
                callback_url = self._get_merchant_callback_url(actual_merchant_code)

            formatted_phone = self._format_phone_number(sender_account_number)
            if not formatted_phone:
                return {'status': False, 'message': 'Invalid phone number format'}

            network_code = self._get_network_code(network_code)

            payment_data = {
                "MerchantCode": actual_merchant_code,
                "NetworkCode": network_code,
                "PhoneNumber": formatted_phone,
                "Amount": str(float(amount)),
                "Currency": "KES",
                "AccountReference": account_reference,
                "TransactionDesc": reason,
                "CallBackURL": callback_url
            }

            logger.info(
                f"[SASAPAY] C2B request | ref={transaction_reference} merchant={actual_merchant_code} "
                f"amount={amount} network={network_code}"
            )

            response = self._request('POST', self.payment_url, actual_merchant_code, json=payment_data)
            logger.info(f"[SASAPAY] C2B response {response.status_code}: {response.text[:500]}")

            if response.status_code in [200, 201]:
                result = response.json()
                return {
                    'status': True,
                    'data': {
                        'CheckoutRequestID': result.get('CheckoutRequestID'),
                        'MerchantRequestID': result.get('MerchantRequestID'),
                        'ResponseCode': result.get('ResponseCode'),
                        'ResponseDescription': result.get('ResponseDescription'),
                        'CustomerMessage': result.get('CustomerMessage'),
                        'PaymentGateway': result.get('PaymentGateway'),
                        'our_transaction_reference': transaction_reference
                    }
                }

            return {
                'status': False,
                'message': f'Payment initiation failed: {response.status_code}',
                'response': response.text
            }

        except Exception as e:
            logger.error(f"[SASAPAY] Exception initiating payment {transaction_reference}: {e}")
            return {'status': False, 'message': f'Error initiating payment: {str(e)}'}

    # ─────────────────────────────────────────────────────────────────
    #  B2B (SasaPay merchant -> SasaPay merchant)
    # ─────────────────────────────────────────────────────────────────
    def initiate_b2b_transfer(self, sender_merchant_code, transaction_reference, amount,
                              receiver_merchant_code, account_reference,
                              receiver_account_type="PAYBILL", network_code="0",
                              callback_url=None, reason="Internal merchant transfer"):
        """
        Move funds from one SasaPay merchant account to ANOTHER SasaPay merchant
        account. For external paybills/tills use pay_paybill() / pay_till().
        Authenticates as the SENDER merchant.
        """
        try:
            if not callback_url:
                callback_url = self._get_merchant_callback_url(sender_merchant_code)

            network_code = self._get_network_code(network_code)

            b2b_data = {
                "MerchantCode": sender_merchant_code,
                "MerchantTransactionReference": transaction_reference,
                "Currency": "KES",
                "Amount": float(amount),
                "ReceiverMerchantCode": receiver_merchant_code,
                "AccountReference": account_reference,
                "ReceiverAccountType": receiver_account_type,
                "NetworkCode": network_code,
                "CallBackURL": callback_url,
                "Reason": reason
            }

            logger.info(
                f"[SASAPAY] B2B request | ref={transaction_reference} "
                f"{sender_merchant_code} -> {receiver_merchant_code} amount={amount}"
            )

            response = self._request('POST', self.b2b_url, sender_merchant_code, json=b2b_data)
            logger.info(f"[SASAPAY] B2B response {response.status_code}: {response.text[:500]}")

            if response.status_code in [200, 201]:
                result = response.json()
                if result.get('status') is False:
                    return {
                        'status': False,
                        'message': result.get('detail') or result.get('message') or 'B2B transfer rejected',
                        'response': json.dumps(result)
                    }
                return {
                    'status': True,
                    'data': {
                        'B2BRequestID': result.get('B2BRequestID'),
                        'ConversationID': result.get('ConversationID'),
                        'OriginatorConversationID': result.get('OriginatorConversationID'),
                        'TransactionCharges': result.get('TransactionCharges'),
                        'ResponseCode': result.get('ResponseCode'),
                        'ResponseDescription': result.get('ResponseDescription'),
                        'our_transaction_reference': transaction_reference
                    }
                }

            return {
                'status': False,
                'message': f'B2B transfer failed: {response.status_code}',
                'response': response.text
            }

        except Exception as e:
            logger.error(f"[SASAPAY] Exception in B2B {transaction_reference}: {e}")
            return {'status': False, 'message': f'Error initiating B2B transfer: {str(e)}'}

    def transfer_to_merchant(self, sender_merchant_code, transaction_reference,
                             amount, receiver_merchant_code, account_reference,
                             callback_url=None, reason="Merchant to merchant transfer"):
        """Thin wrapper around initiate_b2b_transfer() for your own merchant-to-merchant moves."""
        return self.initiate_b2b_transfer(
            sender_merchant_code=sender_merchant_code,
            transaction_reference=transaction_reference,
            amount=amount,
            receiver_merchant_code=receiver_merchant_code,
            account_reference=account_reference,
            receiver_account_type="PAYBILL",
            callback_url=callback_url,
            reason=reason
        )

    # ─────────────────────────────────────────────────────────────────
    #  B2C family (paybill / till / phone)
    # ─────────────────────────────────────────────────────────────────
    def _send_b2c(self, label, sender_merchant_code, transaction_reference, b2c_data, extra):
        """Shared B2C POST + response mapping."""
        try:
            logger.info(
                f"[SASAPAY] {label} request | ref={transaction_reference} "
                f"merchant={sender_merchant_code} amount={b2c_data.get('Amount')} "
                f"receiver={b2c_data.get('ReceiverNumber')}"
            )

            response = self._request('POST', self.b2c_url, sender_merchant_code, json=b2c_data)
            logger.info(f"[SASAPAY] {label} response {response.status_code}: {response.text[:500]}")

            if response.status_code in [200, 201]:
                result = response.json()
                if result.get('status') is False:
                    return {
                        'status': False,
                        'message': result.get('detail') or result.get('message') or f'{label} rejected',
                        'response': json.dumps(result)
                    }
                data = {
                    'B2CRequestID': result.get('B2CRequestID'),
                    'ConversationID': result.get('ConversationID'),
                    'OriginatorConversationID': result.get('OriginatorConversationID'),
                    'ResponseCode': result.get('ResponseCode'),
                    'ResponseDescription': result.get('ResponseDescription') or result.get('detail'),
                    'TransactionCharges': result.get('TransactionCharges'),
                    'our_transaction_reference': transaction_reference,
                }
                data.update(extra)
                return {'status': True, 'data': data}

            return {
                'status': False,
                'message': f'{label} failed: {response.status_code}',
                'response': response.text
            }

        except Exception as e:
            logger.error(f"[SASAPAY] Exception in {label} {transaction_reference}: {e}")
            return {'status': False, 'message': f'Error initiating {label}: {str(e)}'}

    def pay_paybill(self, sender_merchant_code, transaction_reference, amount,
                    paybill_number, account_reference, callback_url=None,
                    reason="Paybill payment", channel="63902"):
        """Pay an EXTERNAL PAYBILL (KPLC, DSTV, etc) via the B2C API."""
        formatted_paybill = re.sub(r'\D', '', str(paybill_number).strip())
        if not formatted_paybill:
            return {'status': False, 'message': 'Invalid paybill number format'}

        if not callback_url:
            callback_url = self._get_merchant_callback_url(sender_merchant_code)

        b2c_data = {
            "MerchantCode": sender_merchant_code,
            "MerchantTransactionReference": transaction_reference,
            "Amount": str(float(amount)),
            "Currency": "KES",
            "ReceiverNumber": formatted_paybill,
            "Channel": channel,
            "AccountReference": account_reference or "Paybill Payment",
            "Reason": reason,
            "CallBackURL": callback_url,
            "ReceiverAccountType": "PAYBILL"
        }
        return self._send_b2c(
            "Paybill payment", sender_merchant_code, transaction_reference, b2c_data,
            {
                'payment_method': 'paybill',
                'receiver_number': formatted_paybill,
                'account_reference': account_reference,
                'channel': channel
            }
        )

    def pay_till(self, sender_merchant_code, transaction_reference, amount,
                 till_number, account_reference, callback_url=None,
                 reason="Till payment", channel="63902"):
        """Pay an EXTERNAL TILL via the B2C API."""
        formatted_till = re.sub(r'\D', '', str(till_number).strip())
        if not formatted_till:
            return {'status': False, 'message': 'Invalid till number format'}

        if not callback_url:
            callback_url = self._get_merchant_callback_url(sender_merchant_code)

        b2c_data = {
            "MerchantCode": sender_merchant_code,
            "MerchantTransactionReference": transaction_reference,
            "Amount": str(float(amount)),
            "Currency": "KES",
            "ReceiverNumber": formatted_till,
            "Channel": channel,
            "AccountReference": account_reference or "Till Payment",
            "Reason": reason,
            "CallBackURL": callback_url,
            "ReceiverAccountType": "TILL"
        }
        return self._send_b2c(
            "Till payment", sender_merchant_code, transaction_reference, b2c_data,
            {
                'payment_method': 'till',
                'receiver_number': formatted_till,
                'account_reference': account_reference,
                'channel': channel
            }
        )

    def initiate_b2c_payment(self, sender_merchant_code, transaction_reference, amount,
                             receiver_number, reason, callback_url=None, channel="63902"):
        """Send money to a phone number (M-PESA / Airtel / SasaPay wallet)."""
        formatted_phone = self._format_phone_number(receiver_number)
        if not formatted_phone:
            return {'status': False, 'message': 'Invalid receiver phone number format'}

        if not callback_url:
            callback_url = self._get_merchant_callback_url(sender_merchant_code)

        channel = self._get_network_code(channel)

        b2c_data = {
            "MerchantCode": sender_merchant_code,
            "MerchantTransactionReference": transaction_reference,
            "Amount": str(float(amount)),
            "Currency": "KES",
            "ReceiverNumber": formatted_phone,
            "Channel": channel,
            "Reason": reason,
            "CallBackURL": callback_url
        }
        return self._send_b2c(
            "B2C payment", sender_merchant_code, transaction_reference, b2c_data,
            {
                'payment_method': 'send_money',
                'receiver_number': formatted_phone,
                'channel': channel
            }
        )

    # ─────────────────────────────────────────────────────────────────
    #  Internal fund movement (working -> utility)
    # ─────────────────────────────────────────────────────────────────
    def move_to_utility_account(self, merchant_code, amount):
        """
        Move funds from a merchant's WORKING account to its UTILITY account.
        SasaPay debits B2C payments from the Utility account.
        """
        try:
            payload = {"merchantCode": merchant_code, "amount": str(float(amount))}
            logger.info(f"[SASAPAY] Fund movement | merchant={merchant_code} amount={amount}")

            response = self._request('POST', self.fund_movement_url, merchant_code, json=payload)
            logger.info(f"[SASAPAY] Fund movement response {response.status_code}: {response.text[:500]}")

            if response.status_code in [200, 201]:
                result = response.json()
                if result.get('status') is False:
                    return {
                        'status': False,
                        'message': result.get('message') or result.get('detail') or 'Fund movement rejected',
                        'response': json.dumps(result)
                    }
                return {
                    'status': True,
                    'data': {
                        'status': result.get('status'),
                        'message': result.get('message'),
                        'our_merchant_code': merchant_code,
                        'amount': str(float(amount))
                    }
                }

            return {
                'status': False,
                'message': f'Fund movement failed: {response.status_code}',
                'response': response.text
            }

        except Exception as e:
            logger.error(f"[SASAPAY] Exception during fund movement for {merchant_code}: {e}")
            return {'status': False, 'message': f'Error during fund movement: {str(e)}'}

    # ─────────────────────────────────────────────────────────────────
    #  OTP processing + payment status
    # ─────────────────────────────────────────────────────────────────
    def process_payment(self, merchant_code, checkout_request_id, verification_code):
        """Process a SasaPay wallet payment with OTP verification."""
        try:
            actual_merchant_code = merchant_code
            if self.environment == "sandbox":
                actual_merchant_code = self.sandbox_merchant_code

            process_data = {
                "MerchantCode": actual_merchant_code,
                "CheckoutRequestID": checkout_request_id,
                "VerificationCode": verification_code
            }
            response = self._request('POST', self.process_url, actual_merchant_code, json=process_data)
            logger.info(f"[SASAPAY] Process payment response {response.status_code}: {response.text[:500]}")

            if response.status_code in [200, 201]:
                return {'status': True, 'data': response.json()}

            return {
                'status': False,
                'message': f'Process payment failed: {response.status_code}',
                'response': response.text
            }

        except Exception as e:
            logger.error(f"[SASAPAY] Exception processing payment: {e}")
            return {'status': False, 'message': f'Error processing payment: {str(e)}'}

    def check_payment_status(self, transaction_reference, merchant_code):
        """Check the status of a SasaPay payment"""
        try:
            actual_merchant_code = merchant_code
            if self.environment == "sandbox":
                actual_merchant_code = self.sandbox_merchant_code

            status_data = {
                "MerchantCode": actual_merchant_code,
                "TransactionReference": transaction_reference
            }
            response = self._request('POST', self.status_url, actual_merchant_code, json=status_data)
            logger.info(f"[SASAPAY] Status response {response.status_code}: {response.text[:500]}")

            if response.status_code == 200:
                return {'status': True, 'data': response.json()}

            return {
                'status': False,
                'message': f'Status check failed: {response.status_code}',
                'response': response.text
            }

        except Exception as e:
            logger.error(f"[SASAPAY] Exception checking status {transaction_reference}: {e}")
            return {'status': False, 'message': f'Error checking payment status: {str(e)}'}

    # ─────────────────────────────────────────────────────────────────
    #  Callbacks
    # ─────────────────────────────────────────────────────────────────
    def process_callback(self, payload):
        """Process a SasaPay callback/webhook."""
        try:
            logger.info(f"[SASAPAY] Callback received: {json.dumps(payload)}")

            result = {
                'checkout_request_id': payload.get('CheckoutRequestID'),
                'merchant_request_id': payload.get('MerchantRequestID'),
                'result_code': payload.get('ResultCode'),
                'result_desc': payload.get('ResultDesc'),
                'amount': payload.get('Amount') or payload.get('TransAmount'),
                'transaction_reference': payload.get('TransactionReference') or payload.get('TransactionCode'),
                'customer_name': payload.get('CustomerName'),
                'customer_number': payload.get('CustomerNumber') or payload.get('CustomerMobile'),
                'merchant_code': payload.get('MerchantCode'),
                'account_reference': payload.get('AccountReference') or payload.get('BillRefNumber'),
                'status': 'success' if payload.get('ResultCode') == '0' else 'failed',
                'paid': payload.get('Paid'),
                'source_channel': payload.get('SourceChannel'),
                'payment_request_id': payload.get('PaymentRequestID'),
                'third_party_trans_id': payload.get('ThirdPartyTransID'),
                'transaction_date': payload.get('TransactionDate'),
                'raw_data': payload
            }

            is_successful = (
                result['result_code'] == '0' and
                result.get('paid') in [True, 'true', '1', 1]
            )
            result['payment_successful'] = is_successful

            if is_successful:
                logger.info(f"[SASAPAY] Payment successful: {result['transaction_reference']}")
            else:
                logger.warning(f"[SASAPAY] Payment failed: {result['result_desc']}")

            return result

        except Exception as e:
            logger.error(f"[SASAPAY] Exception processing callback: {e}")
            return {
                'status': 'error',
                'message': f'Error processing callback: {str(e)}',
                'payment_successful': False
            }

    def process_webhook(self, payload):
        """Alias for process_callback for backward compatibility"""
        return self.process_callback(payload)