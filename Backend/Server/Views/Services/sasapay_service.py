# Server/Views/Services/sasapay_service.py

import requests
import os
import json
import time
import base64
from datetime import datetime, timedelta
import logging
import re

logger = logging.getLogger(__name__)

class SasaPayPaymentService:
    def __init__(self):
        self.environment = os.getenv("SASAPAY_ENVIRONMENT", "sandbox")
        
        # ===== BASE URLs =====
        if self.environment == "production":
            self.base_url = os.getenv("SASAPAY_PRODUCTION_BASE_URL", "https://api.sasapay.app")
            self.payment_url = "https://api.sasapay.app/api/v1/payments/request-payment/"
            self.status_url = "https://api.sasapay.app/api/v1/payments/status/"
            self.process_url = "https://api.sasapay.app/api/v1/payments/process-payment/"
        else:
            self.base_url = os.getenv("SASAPAY_SANDBOX_BASE_URL", "https://sandbox.sasapay.app")
            self.payment_url = "https://sandbox.sasapay.app/api/v1/payments/request-payment/"
            self.status_url = "https://sandbox.sasapay.app/api/v1/payments/status/"
            self.process_url = "https://sandbox.sasapay.app/api/v1/payments/process-payment/"
        
        self.sandbox_merchant_code = os.getenv("SASAPAY_SANDBOX_MERCHANT_CODE", "600980")
        
        # Token cache
        self.token_cache = {}
        self.token_cache_time = {}
        self.token_expiry_seconds = 3600  # 1 hour
        
        # ===== NETWORK CODE MAPPING =====
        self.network_mapping = {
            'safaricom': '63902',
            'airtel': '63903',
            'telkom': '63904',
            'equitel': '63905',
            'sasapay': '0'
        }
        
        logger.info("=" * 60)
        logger.info("[SASAPAY] Service Initialized")
        logger.info(f"[SASAPAY] Environment: {self.environment}")
        logger.info(f"[SASAPAY] Base URL: {self.base_url}")
        logger.info(f"[SASAPAY] Payment URL: {self.payment_url}")
        logger.info(f"[SASAPAY] Status URL: {self.status_url}")
        logger.info(f"[SASAPAY] Process URL: {self.process_url}")
        logger.info(f"[SASAPAY] Sandbox Merchant Code: {self.sandbox_merchant_code}")
        logger.info("=" * 60)

    def _get_merchant_credentials(self, merchant_code):
        """Get client ID and secret for a specific merchant from env"""
        # Try to get merchant-specific credentials
        client_id = os.getenv(f"SASAPAY_MERCHANT_{merchant_code}_CLIENT_ID")
        client_secret = os.getenv(f"SASAPAY_MERCHANT_{merchant_code}_CLIENT_SECRET")
        
        logger.info("=" * 60)
        logger.info(f"[SASAPAY] Looking for credentials for merchant: {merchant_code}")
        logger.info(f"[SASAPAY] SASAPAY_MERCHANT_{merchant_code}_CLIENT_ID: {'[SET]' if client_id else '[MISSING]'}")
        logger.info(f"[SASAPAY] SASAPAY_MERCHANT_{merchant_code}_CLIENT_SECRET: {'[SET]' if client_secret else '[MISSING]'}")
        
        if client_id:
            logger.info(f"[SASAPAY] CLIENT_ID (first 20 chars): {client_id[:20]}...")
        if client_secret:
            logger.info(f"[SASAPAY] CLIENT_SECRET (first 20 chars): {client_secret[:20]}...")
        
        if not client_id or not client_secret:
            # Try alternative format without merchant code
            logger.info("[SASAPAY] Trying fallback credentials (SASAPAY_CLIENT_ID / SASAPAY_CLIENT_SECRET)")
            client_id = os.getenv("SASAPAY_CLIENT_ID")
            client_secret = os.getenv("SASAPAY_CLIENT_SECRET")
            logger.info(f"[SASAPAY] Fallback CLIENT_ID: {'[SET]' if client_id else '[MISSING]'}")
            logger.info(f"[SASAPAY] Fallback CLIENT_SECRET: {'[SET]' if client_secret else '[MISSING]'}")
            if client_id:
                logger.info(f"[SASAPAY] Fallback CLIENT_ID (first 20 chars): {client_id[:20]}...")
        
        if not client_id or not client_secret:
            logger.error(f"[SASAPAY] Missing credentials for merchant: {merchant_code}")
            logger.error(f"[SASAPAY] Expected env vars: SASAPAY_MERCHANT_{merchant_code}_CLIENT_ID and SASAPAY_MERCHANT_{merchant_code}_CLIENT_SECRET")
            raise Exception(f"Missing credentials for merchant {merchant_code}. Please check environment variables.")
        
        return client_id, client_secret

    def _get_merchant_callback_url(self, merchant_code):
        """
        Get merchant-specific callback URL.
        Your callback URL is: https://app.kukuzetu.co.ke/api/diraja/sasapay/callback
        """
        # Try merchant-specific callback from env
        callback_url = os.getenv(f"SASAPAY_MERCHANT_{merchant_code}_CALLBACK_URL")
        
        if not callback_url:
            # Try default callback from env
            callback_url = os.getenv("SASAPAY_CALLBACK_URL")
        
        if not callback_url:
            # Fallback: Build from BASE_URL
            base_url = os.getenv('BASE_URL', 'https://app.kukuzetu.co.ke')
            # Your callback endpoint is at /api/diraja/sasapay/callback
            callback_url = f"{base_url}/api/diraja/sasapay/callback"
        
        # Ensure the callback URL ends with the correct path
        # If the env var is set to "https://app.kukuzetu.co.ke/api/diraja", append /sasapay/callback
        if callback_url and not callback_url.endswith('/sasapay/callback'):
            # Check if it ends with /api/diraja
            if callback_url.endswith('/api/diraja'):
                callback_url = f"{callback_url}/sasapay/callback"
            elif callback_url.endswith('/api/diraja/'):
                callback_url = f"{callback_url}sasapay/callback"
            elif not callback_url.endswith('callback'):
                # If it doesn't contain the callback path, append it
                callback_url = f"{callback_url}/api/diraja/sasapay/callback"
        
        logger.info(f"[SASAPAY] Callback URL for merchant {merchant_code}: {callback_url}")
        return callback_url

    def _format_phone_number(self, phone_number):
        """Format phone number to international format"""
        if not phone_number:
            return None
        
        # Remove any non-digit characters
        phone_number = re.sub(r'\D', '', phone_number)
        
        # Format to 254XXXXXXXXX
        if phone_number.startswith('0'):
            phone_number = '254' + phone_number[1:]
        elif not phone_number.startswith('254'):
            if phone_number.startswith('+'):
                phone_number = phone_number[1:]
            if not phone_number.startswith('254'):
                phone_number = '254' + phone_number
        
        return phone_number

    def _get_network_code(self, network_input):
        """Get network code from various input formats"""
        if not network_input:
            return '63902'  # Default to MPESA
        
        # Convert to lowercase for matching
        network_input = network_input.lower().strip()
        
        # Check if it's already a network code
        if network_input in ['63902', '63903', '63904', '63905', '0']:
            return network_input
        
        # Check mapping
        for key, code in self.network_mapping.items():
            if key in network_input or network_input in key:
                return code
        
        # Default to MPESA
        logger.warning(f"[SASAPAY] Unknown network code '{network_input}', defaulting to MPESA (63902)")
        return '63902'

    def _get_access_token(self, merchant_code):
        """Get access token using SasaPay's documented GET + Basic Auth method."""
        try:
            # Check cache
            cache_key = merchant_code
            if cache_key in self.token_cache:
                cached_time = self.token_cache_time.get(cache_key, 0)
                if time.time() - cached_time < self.token_expiry_seconds:
                    logger.info(f"[SASAPAY AUTH] Using cached token for merchant: {merchant_code}")
                    return self.token_cache[cache_key]

            # 1. Get merchant-specific credentials
            client_id, client_secret = self._get_merchant_credentials(merchant_code)

            # 2. Construct the full URL with the query parameter
            url = f"{self.base_url}/auth/token/?grant_type=client_credentials"

            # 3. Prepare Basic Auth Header
            auth_string = f"{client_id}:{client_secret}"
            auth_bytes = auth_string.encode('ascii')
            base64_auth = base64.b64encode(auth_bytes).decode('ascii')

            headers = {
                'Authorization': f'Basic {base64_auth}',
                'Accept': 'application/json'
            }

            logger.info("=" * 60)
            logger.info("[SASAPAY AUTH] AUTHENTICATION ATTEMPT")
            logger.info(f"[SASAPAY AUTH] Merchant Code: {merchant_code}")
            logger.info(f"[SASAPAY AUTH] URL: {url}")
            logger.info(f"[SASAPAY AUTH] Method: GET")
            logger.info(f"[SASAPAY AUTH] Authorization: Basic {base64_auth[:20]}... (truncated)")
            logger.info("=" * 60)

            # 4. Make the GET request
            response = requests.get(url, headers=headers, timeout=30)

            logger.info(f"[SASAPAY AUTH] Response Status: {response.status_code}")
            logger.info(f"[SASAPAY AUTH] Response Headers: {dict(response.headers)}")
            logger.info(f"[SASAPAY AUTH] Response Body: {response.text[:500]}")

            if response.status_code == 200:
                token_data = response.json()
                logger.info(f"[SASAPAY AUTH] Token response keys: {list(token_data.keys()) if token_data else 'None'}")
                
                access_token = token_data.get('access_token')
                status = token_data.get('status')
                detail = token_data.get('detail')

                if access_token:
                    self.token_cache[cache_key] = access_token
                    self.token_cache_time[cache_key] = time.time()
                    logger.info(f"[SASAPAY AUTH] SUCCESS - Token obtained for merchant: {merchant_code}")
                    logger.info(f"[SASAPAY AUTH] Token (first 30 chars): {access_token[:30]}...")
                    logger.info(f"[SASAPAY AUTH] Expires in: {token_data.get('expires_in')} seconds")
                    logger.info(f"[SASAPAY AUTH] Token type: {token_data.get('token_type')}")
                    return access_token
                else:
                    error_msg = f"No access token in response: {token_data}"
                    logger.error(f"[SASAPAY AUTH] {error_msg}")
                    raise Exception(error_msg)
            elif response.status_code == 401:
                logger.error(f"[SASAPAY AUTH] Authentication failed - Invalid credentials for merchant: {merchant_code}")
                logger.error(f"[SASAPAY AUTH] Please check CLIENT_ID and CLIENT_SECRET for this merchant")
                raise Exception(f"Invalid credentials for merchant {merchant_code}")
            else:
                error_msg = f"Token request failed with status {response.status_code}: {response.text}"
                logger.error(f"[SASAPAY AUTH] {error_msg}")
                raise Exception(error_msg)

        except Exception as e:
            logger.error(f"[SASAPAY AUTH] Exception getting token for merchant: {merchant_code} - {str(e)}")
            raise

    def initiate_payment(self, merchant_code, transaction_reference, amount, 
                         sender_account_number, receiver_merchant_code,
                         account_reference, network_code, callback_url, reason):
        """Initiate a SasaPay C2B payment request using the correct API."""
        try:
            logger.info("=" * 60)
            logger.info("[SASAPAY] PAYMENT INITIATION STARTED (C2B API)")
            logger.info("=" * 60)
            
            # Use sandbox merchant code if in sandbox environment
            actual_merchant_code = merchant_code
            if self.environment == "sandbox":
                actual_merchant_code = self.sandbox_merchant_code
                logger.info(f"[SASAPAY] Using sandbox merchant code: {actual_merchant_code}")

            # STEP 1: Get access token
            logger.info("[SASAPAY] STEP 1: Getting access token...")
            access_token = self._get_access_token(actual_merchant_code)
            logger.info(f"[SASAPAY] STEP 1: Access token obtained successfully")

            # STEP 2: Prepare payment request
            logger.info("[SASAPAY] STEP 2: Preparing C2B payment request...")
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            # Get callback URL
            if not callback_url:
                callback_url = self._get_merchant_callback_url(actual_merchant_code)
            logger.info(f"[SASAPAY] Using callback URL: {callback_url}")
            
            # Format phone number
            formatted_phone = self._format_phone_number(sender_account_number)
            if not formatted_phone:
                logger.error("[SASAPAY] Invalid phone number format")
                return {
                    'status': False,
                    'message': 'Invalid phone number format'
                }
            
            # Get network code
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
            
            payment_json = json.dumps(payment_data, indent=2)
            
            logger.info("=" * 60)
            logger.info("[SASAPAY] STEP 2: C2B PAYMENT REQUEST DETAILS")
            logger.info(f"[SASAPAY] Transaction Reference: {transaction_reference}")
            logger.info(f"[SASAPAY] Amount: {amount}")
            logger.info(f"[SASAPAY] Merchant Code: {actual_merchant_code}")
            logger.info(f"[SASAPAY] Payment URL: {self.payment_url}")
            logger.info(f"[SASAPAY] Network Code: {network_code}")
            logger.info(f"[SASAPAY] Phone Number: {formatted_phone}")
            logger.info(f"[SASAPAY] Callback URL: {callback_url}")
            logger.info("[SASAPAY] PAYLOAD BEING SENT TO SASAPAY:")
            logger.info(f"\n{payment_json}")
            logger.info("=" * 60)
            
            # STEP 3: Make the POST request
            logger.info("[SASAPAY] STEP 3: Sending payment request to SasaPay...")
            response = requests.post(self.payment_url, json=payment_data, headers=headers, timeout=30)
            
            logger.info(f"[SASAPAY] Response Status: {response.status_code}")
            logger.info(f"[SASAPAY] Response Body: {response.text[:500]}")
            
            # STEP 4: Process response
            logger.info("[SASAPAY] STEP 4: Processing response...")
            
            if response.status_code in [200, 201]:
                result = response.json()
                logger.info(f"[SASAPAY] Payment initiated successfully for transaction: {transaction_reference}")
                logger.info(f"[SASAPAY] Response: {json.dumps(result, indent=2)}")
                
                # Extract important response fields
                checkout_request_id = result.get('CheckoutRequestID')
                merchant_request_id = result.get('MerchantRequestID')
                response_code = result.get('ResponseCode')
                response_desc = result.get('ResponseDescription')
                customer_message = result.get('CustomerMessage')
                
                # Check if it's a SasaPay wallet payment (requires OTP)
                if network_code == "0":
                    logger.info("[SASAPAY] SasaPay wallet payment detected - OTP will be sent")
                    if result.get('status') and response_code == "0":
                        logger.info("[SASAPAY] SasaPay wallet payment requires OTP verification")
                        logger.info(f"[SASAPAY] CheckoutRequestID: {checkout_request_id}")
                
                return {
                    'status': True,
                    'data': {
                        'CheckoutRequestID': checkout_request_id,
                        'MerchantRequestID': merchant_request_id,
                        'ResponseCode': response_code,
                        'ResponseDescription': response_desc,
                        'CustomerMessage': customer_message,
                        'PaymentGateway': result.get('PaymentGateway'),
                        'our_transaction_reference': transaction_reference
                    }
                }
            else:
                logger.error(f"[SASAPAY] Payment initiation failed for transaction: {transaction_reference}, status: {response.status_code}")
                logger.error(f"[SASAPAY] Response: {response.text}")
                return {
                    'status': False,
                    'message': f'Payment initiation failed: {response.status_code}',
                    'response': response.text
                }
                
        except Exception as e:
            logger.error(f"[SASAPAY] Exception initiating payment for transaction: {transaction_reference} - {str(e)}")
            return {
                'status': False,
                'message': f'Error initiating payment: {str(e)}'
            }

    def process_payment(self, merchant_code, checkout_request_id, verification_code):
        """Process a SasaPay payment with OTP verification (for SasaPay wallet only)."""
        try:
            logger.info("=" * 60)
            logger.info("[SASAPAY] PROCESS PAYMENT WITH OTP")
            logger.info("=" * 60)
            
            # Use sandbox merchant code if in sandbox environment
            actual_merchant_code = merchant_code
            if self.environment == "sandbox":
                actual_merchant_code = self.sandbox_merchant_code
            
            # Get access token
            access_token = self._get_access_token(actual_merchant_code)
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            process_data = {
                "MerchantCode": actual_merchant_code,
                "CheckoutRequestID": checkout_request_id,
                "VerificationCode": verification_code
            }
            
            logger.info(f"[SASAPAY] Process URL: {self.process_url}")
            logger.info(f"[SASAPAY] Process Data: {json.dumps(process_data, indent=2)}")
            
            response = requests.post(self.process_url, json=process_data, headers=headers, timeout=30)
            
            logger.info(f"[SASAPAY] Response Status: {response.status_code}")
            logger.info(f"[SASAPAY] Response Body: {response.text[:500]}")
            
            if response.status_code in [200, 201]:
                result = response.json()
                logger.info(f"[SASAPAY] Payment processed successfully")
                return {
                    'status': True,
                    'data': result
                }
            else:
                logger.error(f"[SASAPAY] Process payment failed")
                return {
                    'status': False,
                    'message': f'Process payment failed: {response.status_code}',
                    'response': response.text
                }
                
        except Exception as e:
            logger.error(f"[SASAPAY] Exception processing payment - {str(e)}")
            return {
                'status': False,
                'message': f'Error processing payment: {str(e)}'
            }

    def check_payment_status(self, transaction_reference, merchant_code):
        """Check the status of a SasaPay payment"""
        try:
            logger.info("=" * 60)
            logger.info("[SASAPAY] PAYMENT STATUS CHECK STARTED")
            logger.info("=" * 60)
            
            # Use sandbox merchant code if in sandbox environment
            actual_merchant_code = merchant_code
            if self.environment == "sandbox":
                actual_merchant_code = self.sandbox_merchant_code

            # Get access token
            logger.info("[SASAPAY] STEP 1: Getting access token for status check...")
            access_token = self._get_access_token(actual_merchant_code)
            logger.info(f"[SASAPAY] STEP 1: Access token obtained successfully")

            # Prepare status check request
            logger.info("[SASAPAY] STEP 2: Preparing status check request...")
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            status_data = {
                "MerchantCode": actual_merchant_code,
                "TransactionReference": transaction_reference
            }
            
            logger.info("=" * 60)
            logger.info("[SASAPAY] STEP 2: STATUS CHECK REQUEST DETAILS")
            logger.info(f"[SASAPAY] Transaction Reference: {transaction_reference}")
            logger.info(f"[SASAPAY] Merchant Code: {actual_merchant_code}")
            logger.info(f"[SASAPAY] Status URL: {self.status_url}")
            logger.info("[SASAPAY] STATUS DATA BEING SENT:")
            logger.info(f"\n{json.dumps(status_data, indent=2)}")
            logger.info("=" * 60)
            
            # Make the POST request
            logger.info("[SASAPAY] STEP 3: Sending status check request to SasaPay...")
            response = requests.post(self.status_url, json=status_data, headers=headers, timeout=30)
            
            logger.info(f"[SASAPAY] Status Response Status: {response.status_code}")
            logger.info(f"[SASAPAY] Status Response Body: {response.text[:500]}")
            
            # Process response
            logger.info("[SASAPAY] STEP 4: Processing status response...")
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"[SASAPAY] Payment status checked for transaction: {transaction_reference}")
                logger.info(f"[SASAPAY] Status Result: {json.dumps(result, indent=2)}")
                return {
                    'status': True,
                    'data': result
                }
            else:
                logger.error(f"[SASAPAY] Status check failed for transaction: {transaction_reference}, status: {response.status_code}")
                return {
                    'status': False,
                    'message': f'Status check failed: {response.status_code}',
                    'response': response.text
                }
                
        except Exception as e:
            logger.error(f"[SASAPAY] Exception checking payment status for transaction: {transaction_reference} - {str(e)}")
            return {
                'status': False,
                'message': f'Error checking payment status: {str(e)}'
            }

    def process_callback(self, payload):
        """
        Process a SasaPay callback/webhook.
        This is the main method to handle incoming callbacks.
        """
        try:
            logger.info("=" * 60)
            logger.info("[SASAPAY] CALLBACK RECEIVED")
            logger.info("=" * 60)
            
            # Log the full payload
            logger.info(f"[SASAPAY] Full Callback Payload: {json.dumps(payload, indent=2)}")
            logger.info("=" * 60)
            
            # Extract key fields
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
            
            logger.info("[SASAPAY] Processed Callback Data:")
            for key, value in result.items():
                if key != 'raw_data':
                    logger.info(f"[SASAPAY] {key}: {value}")
            
            # Determine if payment was successful
            is_successful = (
                result['result_code'] == '0' and 
                result.get('paid') in [True, 'true', '1', 1]
            )
            
            if is_successful:
                logger.info(f"[SASAPAY] ✅ Payment successful! Transaction: {result['transaction_reference']}")
                result['payment_successful'] = True
            else:
                logger.warning(f"[SASAPAY] ❌ Payment failed: {result['result_desc']}")
                result['payment_successful'] = False
            
            return result
            
        except Exception as e:
            logger.error(f"[SASAPAY] Exception processing callback - {str(e)}")
            return {
                'status': 'error',
                'message': f'Error processing callback: {str(e)}',
                'payment_successful': False
            }

    def process_webhook(self, payload):
        """Alias for process_callback for backward compatibility"""
        return self.process_callback(payload)