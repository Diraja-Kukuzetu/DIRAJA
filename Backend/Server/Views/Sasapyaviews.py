import requests
import json
from requests.auth import HTTPBasicAuth
from flask_restful import Resource
from flask import current_app, request
from flask_jwt_extended import jwt_required
import os
from datetime import datetime


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

class SasaPayBalanceResource(Resource):

    @jwt_required()
    def get(self):
        """Get merchant account balances from SasaPay using individual credentials for each merchant"""
        
        # Get specific merchant code from query params, or fetch all
        merchant_code_param = request.args.get('merchant_code')
        
        # Get current environment
        sasapay_env = os.getenv("SASAPAY_ENVIRONMENT", "sandbox")
        
        # Get all merchant configurations with their unique credentials
        merchants = self._get_all_merchant_configs(sasapay_env)
        
        # If specific merchant requested
        if merchant_code_param:
            merchants = [m for m in merchants if m['code'] == merchant_code_param]
            if not merchants:
                return {
                    "error": f"Merchant {merchant_code_param} not found or not configured",
                    "environment": sasapay_env
                }, 404
        
        if not merchants:
            return {
                "error": f"No merchants configured for {sasapay_env} environment",
                "environment": sasapay_env
            }, 404
        
        try:
            current_app.logger.info(f"Checking SasaPay balances for {len(merchants)} merchants in {sasapay_env.upper()}")
            print(f"\n{'='*60}")
            print(f"[ENV] Environment: {sasapay_env.upper()}")
            print(f"[INFO] Total merchants to fetch: {len(merchants)}")
            print(f"{'='*60}")
            
            all_balances = []
            total_combined_balance = 0
            successful_fetches = 0
            failed_fetches = 0
            
            for idx, merchant in enumerate(merchants, 1):
                # Use ASCII-safe printing - encode/decode to handle Unicode
                merchant_name_ascii = merchant['name'].encode('ascii', 'ignore').decode('ascii')
                print(f"\n{'-'*50}")
                print(f"[MERCHANT {idx}/{len(merchants)}] Processing: {merchant_name_ascii}")
                print(f"[CODE] {merchant['code']}")
                print(f"{'-'*50}")
                
                # Fetch balance for this merchant using its own credentials
                balance_result = self._fetch_merchant_balance_with_creds(merchant, sasapay_env)
                
                if balance_result and 'error' not in balance_result:
                    total_combined_balance += balance_result.get('total_balance', 0)
                    all_balances.append(balance_result)
                    successful_fetches += 1
                    print(f"[SUCCESS] Balance: {balance_result.get('total_balance', 0)} KES")
                else:
                    error_msg = balance_result.get('error', 'Unknown error') if balance_result else 'Failed to fetch'
                    all_balances.append({
                        "merchant_code": merchant['code'],
                        "merchant_name": merchant['name'],
                        "location": merchant.get('location', ''),
                        "type": merchant.get('type', 'shop'),
                        "error": error_msg,
                        "total_balance": 0
                    })
                    failed_fetches += 1
                    print(f"[FAILED] {error_msg}")
            
            print(f"\n{'='*60}")
            print(f"[SUMMARY] Successful: {successful_fetches}, Failed: {failed_fetches}")
            print(f"[TOTAL BALANCE] {total_combined_balance} KES")
            print(f"{'='*60}")
            
            # Return combined response
            return {
                "success": True,
                "environment": sasapay_env,
                "total_merchants": len(merchants),
                "successful_fetches": successful_fetches,
                "failed_fetches": failed_fetches,
                "total_combined_balance": total_combined_balance,
                "currency": "KES",
                "merchants": all_balances,
                "timestamp": datetime.utcnow().isoformat()
            }, 200
                
        except Exception as e:
            current_app.logger.error(f"SasaPay balance error: {str(e)}")
            return {
                "error": str(e),
                "environment": sasapay_env
            }, 500
    
    def _get_all_merchant_configs(self, environment):
        """Get all merchant configurations with their unique credentials from environment variables"""
        merchants = []
        
        if environment == "production":
            # Base URL for production
            base_url = os.getenv("SASAPAY_PRODUCTION_BASE_URL", "https://api.sasapay.app/api/v1")
            
            # ONLY the merchants you have credentials for (7 merchants)
            merchant_configs = [
                {"code": "570257", "name": "Kuku Zetu - Mirema", "location": "Mirema", "type": "shop"},
                {"code": "577960", "name": "Kuku Zetu - Lumumba Drive", "location": "Lumumba Drive", "type": "shop"},
                {"code": "577480", "name": "Kuku Zetu - Zimmerman", "location": "Zimmerman", "type": "shop"},
                {"code": "577668", "name": "Kukuzetu - Ngoingwa Stockist", "location": "Ngoingwa", "type": "stockist"},
                {"code": "577666", "name": "KUKUZETU - TRM", "location": "Thika Road Mall", "type": "shop"},
                {"code": "222333", "name": "Kukuzetu - Kasarani Equity", "location": "Kasarani", "type": "shop"},
                {"code": "577123", "name": "Kukuzetu - Kasarani Maternity", "location": "Kasarani", "type": "shop"},
                {"code": "577556", "name": "Kukuzetu - Turi", "location": "Turi", "type": "shop"}
            ]
            
            for config in merchant_configs:
                code = config['code']
                
                # Get unique credentials for this merchant
                client_id = os.getenv(f"SASAPAY_MERCHANT_{code}_CLIENT_ID")
                client_secret = os.getenv(f"SASAPAY_MERCHANT_{code}_CLIENT_SECRET")
                
                if client_id and client_secret:
                    merchants.append({
                        "code": code,
                        "name": config['name'],
                        "location": config['location'],
                        "type": config['type'],
                        "base_url": base_url,
                        "client_id": client_id,
                        "client_secret": client_secret
                    })
                else:
                    # Use ASCII-safe warning message
                    print(f"[WARNING] Missing credentials for merchant {code}")
        
        else:  # sandbox environment
            client_id = os.getenv("SASAPAY_SANDBOX_CLIENT_ID")
            client_secret = os.getenv("SASAPAY_SANDBOX_CLIENT_SECRET")
            base_url = os.getenv("SASAPAY_SANDBOX_BASE_URL", "https://sandbox.sasapay.app/api/v1")
            
            if client_id and client_secret:
                merchants.append({
                    "code": "600980",
                    "name": "SasaPay Sandbox Merchant",
                    "location": "Sandbox",
                    "type": "test",
                    "base_url": base_url,
                    "client_id": client_id,
                    "client_secret": client_secret
                })
        
        return merchants
    
    def _fetch_merchant_balance_with_creds(self, merchant, environment):
        """Fetch balance for a single merchant using its own client credentials"""
        
        try:
            merchant_code = merchant['code']
            merchant_name = merchant['name']
            base_url = merchant['base_url']
            client_id = merchant['client_id']
            client_secret = merchant['client_secret']
            
            print(f"  [1/2] Getting auth token...")
            
            # STEP 1: Get access token using THIS merchant's credentials
            access_token = self._get_access_token(base_url, client_id, client_secret)
            
            if not access_token:
                print(f"  [ERROR] Failed to obtain access token")
                return {"error": "Authentication failed - Invalid client credentials"}
            
            print(f"  [OK] Token obtained")
            print(f"  [2/2] Fetching balance...")
            
            # STEP 2: Fetch balance using the token
            balance_data = self._fetch_merchant_balance(
                base_url, access_token, merchant_code, environment
            )
            
            if not balance_data:
                print(f"  [ERROR] Failed to fetch balance")
                return {"error": "Balance fetch failed"}
            
            total_balance = balance_data.get('org_account_balance', 0)
            print(f"  [OK] Balance: {total_balance} KES")
            
            return {
                "merchant_code": merchant_code,
                "merchant_name": merchant_name,
                "location": merchant.get('location', ''),
                "type": merchant.get('type', 'shop'),
                "total_balance": total_balance,
                "currency": balance_data.get('currency', 'KES'),
                "accounts": balance_data.get('accounts', []),
                "statusCode": balance_data.get('statusCode'),
                "message": balance_data.get('message')
            }
            
        except Exception as e:
            print(f"  [ERROR] Exception: {str(e)}")
            return {"error": f"Exception: {str(e)}"}
    
    def _get_access_token(self, base_url, client_id, client_secret):
        """Get access token from SasaPay using specific merchant credentials"""
        try:
            token_url = f"{base_url}/auth/token/"
            
            params = {
                'grant_type': 'client_credentials'
            }
            
            response = requests.get(
                token_url,
                auth=HTTPBasicAuth(client_id, client_secret),
                params=params,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('status') == True:
                    access_token = data.get('access_token')
                    if access_token:
                        return access_token
                        
            return None
            
        except Exception as e:
            current_app.logger.error(f"Exception getting token: {str(e)}")
            return None
    
    def _fetch_merchant_balance(self, base_url, access_token, merchant_code, environment):
        """Fetch balance for a specific merchant using the access token"""
        try:
            # Use the documented endpoint
            balance_url = f"{base_url}/payments/check-balance/"
            
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
            
            params = {
                "MerchantCode": merchant_code
            }
            
            response = requests.get(
                balance_url, 
                headers=headers, 
                params=params, 
                timeout=30
            )
            
            if response.status_code == 200:
                response_data = response.json()
                
                # Check if the request was successful based on statusCode
                if response_data.get('statusCode') == '0':
                    return self._format_balance_response(response_data, environment, merchant_code)
                else:
                    current_app.logger.error(f"API error for {merchant_code}: {response_data.get('message')}")
                    return None
            else:
                current_app.logger.error(f"Failed to fetch balance for {merchant_code}: {response.status_code}")
                return None
                
        except Exception as e:
            current_app.logger.error(f"Error fetching balance for {merchant_code}: {str(e)}")
            return None
    
    def _format_balance_response(self, response_data, environment, merchant_code):
        """Format balance response according to SasaPay API structure"""
        
        # Extract data from response
        data = response_data.get('data', {})
        
        formatted = {
            "environment": environment,
            "currency": data.get('CurrencyCode', 'KES'),
            "org_account_balance": data.get('OrgAccountBalance', 0),
            "accounts": data.get('Accounts', []),
            "message": response_data.get('message', 'Account Balances'),
            "statusCode": response_data.get('statusCode')
        }
        
        return formatted

class SasaPayChannelCodesResource(Resource):

    @jwt_required()
    def get(self):
        """Get all payment channel codes from SasaPay (supports both environments)"""
        
        # Get current environment
        sasapay_env = os.getenv("SASAPAY_ENVIRONMENT", "sandbox")
        
        # Mock mode for development
        if current_app.config.get("SASAPAY_USE_MOCK", False):
            return self._mock_channel_codes(sasapay_env)
        
        base_url = current_app.config["SASAPAY_BASE_URL"]
        client_id = current_app.config["SASAPAY_CLIENT_ID"]
        client_secret = current_app.config["SASAPAY_CLIENT_SECRET"]
        
        try:
            current_app.logger.info(f"Fetching channel codes from {sasapay_env.upper()}")
            
            # Get access token based on environment
            access_token = self._get_access_token_for_channels(base_url, client_id, client_secret, sasapay_env)
            
            if not access_token:
                return {
                    "error": "Authentication failed",
                    "environment": sasapay_env
                }, 401
            
            # Different endpoints for sandbox vs production
            if sasapay_env == "production":
                channel_url = f"{base_url}/v1/payment/channels"
            else:
                channel_url = f"{base_url}/payments/channel-codes/"
            
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(channel_url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                # Format response consistently
                formatted_response = self._format_channel_response(response.json(), sasapay_env)
                return {
                    "success": True,
                    "environment": sasapay_env,
                    "channels": formatted_response
                }, 200
            else:
                return {
                    "error": "Failed to retrieve channel codes",
                    "environment": sasapay_env,
                    "status_code": response.status_code,
                    "details": response.text
                }, response.status_code
                
        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"SasaPay channel codes error in {sasapay_env}: {str(e)}")
            return {
                "error": "Failed to connect to SasaPay",
                "environment": sasapay_env,
                "details": str(e)
            }, 500
        except Exception as e:
            current_app.logger.error(f"Unexpected error: {str(e)}")
            return {"error": str(e), "environment": sasapay_env}, 500
    
    def _get_access_token_for_channels(self, base_url, client_id, client_secret, environment):
        """Get access token specifically for channel codes"""
        if environment == "production":
            token_url = f"{base_url}/oauth/token"
            try:
                response = requests.post(
                    token_url,
                    auth=HTTPBasicAuth(client_id, client_secret),
                    json={'grant_type': 'client_credentials'},
                    timeout=30
                )
            except:
                response = requests.get(
                    token_url,
                    auth=HTTPBasicAuth(client_id, client_secret),
                    params={'grant_type': 'client_credentials'},
                    timeout=30
                )
        else:
            token_url = f"{base_url}/auth/token/"
            response = requests.get(
                token_url,
                auth=HTTPBasicAuth(client_id, client_secret),
                params={'grant_type': 'client_credentials'},
                timeout=30
            )
        
        if response.status_code == 200:
            data = response.json()
            if environment == "production":
                return data.get('access_token') or data.get('token')
            else:
                if data.get('status') == True:
                    return data.get('access_token')
        return None
    
    def _format_channel_response(self, response_data, environment):
        """Format channel codes response consistently"""
        if environment == "production":
            # Production format
            if isinstance(response_data, list):
                return response_data
            elif isinstance(response_data, dict):
                return response_data.get("channels", [])
        else:
            # Sandbox format
            if "channel_codes" in response_data:
                return response_data["channel_codes"]
            elif "data" in response_data:
                return response_data["data"]
        
        return response_data
    
    def _mock_channel_codes(self, environment):
        """Mock channel codes for development based on environment"""
        channels = [
            {
                "network_code": "63902",
                "network_name": "M-PESA",
                "channel_type": "Mobile Money"
            },
            {
                "network_code": "63903", 
                "network_name": "Airtel Money",
                "channel_type": "Mobile Money"
            },
            {
                "network_code": "0",
                "network_name": "SasaPay Wallet",
                "channel_type": "Wallet"
            }
        ]
        
        if environment == "production":
            channels.append({
                "network_code": "63904",
                "network_name": "T-Kash",
                "channel_type": "Mobile Money"
            })
        
        return {
            "success": True,
            "mock": True,
            "environment": environment,
            "warning": f"Mock {environment.upper()} data for testing only",
            "channels": channels
        }, 200


class SasaPayTransactionStatementResource(Resource):
    """Get transaction statement for a merchant account"""
    
    @jwt_required()
    def get(self):
        """Get transaction statement from SasaPay"""
        
        # Get query parameters
        merchant_code = request.args.get('merchant_code')
        account_number = request.args.get('account_number')
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 50))
        
        # Validate required parameters
        if not merchant_code:
            return {
                "error": "merchant_code is required",
                "available_merchants": self._get_available_merchants(os.getenv("SASAPAY_ENVIRONMENT", "sandbox"))
            }, 400
        
        # If account_number not provided, use merchant_code as default
        if not account_number:
            account_number = merchant_code
            current_app.logger.info(f"account_number not provided, defaulting to merchant_code: {merchant_code}")
        
        # Get current environment
        sasapay_env = os.getenv("SASAPAY_ENVIRONMENT", "sandbox")
        
        # Note: According to docs, transaction statements are only available in production
        if sasapay_env != "production":
            return {
                "error": "Transaction statements are only available in PRODUCTION environment",
                "environment": sasapay_env,
                "message": "Please switch to production to fetch real transaction statements",
                "mock_data_available": True
            }, 400
        
        # Mock mode for development
        if current_app.config.get("SASAPAY_USE_MOCK", False):
            return self._mock_transaction_response(merchant_code, account_number, page, page_size)
        
        # Get all merchant configurations
        merchants = self._get_all_merchant_configs(sasapay_env)
        
        # Find the specific merchant
        merchant = None
        for m in merchants:
            if m['code'] == merchant_code:
                merchant = m
                break
        
        if not merchant:
            return {
                "error": f"Merchant {merchant_code} not found or not configured",
                "environment": sasapay_env,
                "available_merchants": [m['code'] for m in merchants]
            }, 404
        
        try:
            # Log environment being used
            current_app.logger.info(f"Fetching transactions for merchant {merchant_code} in {sasapay_env.upper()} environment")
            print(f"\n{'='*60}")
            print(f"[ENV] Environment: {sasapay_env.upper()}")
            print(f"[INFO] Merchant: {merchant['name']}")
            print(f"[CODE] {merchant_code}")
            print(f"[ACCOUNT] {account_number}")
            print(f"{'='*60}")
            
            # Step 1: Get access token using the SAME method as balance resource
            print(f"  [1/2] Getting auth token...")
            access_token = self._get_access_token(merchant['base_url'], merchant['client_id'], merchant['client_secret'])
            
            if not access_token:
                print(f"  [ERROR] Failed to obtain access token")
                return {
                    "error": "Failed to obtain access token", 
                    "environment": sasapay_env,
                    "merchant_code": merchant_code,
                    "message": "Authentication failed - Invalid client credentials"
                }, 401
            
            print(f"  [OK] Token obtained")
            print(f"  [2/2] Fetching transaction statement...")
            
            # Use the exact endpoint from documentation
            if sasapay_env == "production":
                transactions_url = "https://api.sasapay.app/api/v2/waas/transactions/"
            else:
                transactions_url = "https://sandbox.sasapay.app/api/v2/waas/transactions/"
            
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
            
            params = {
                "merchantCode": merchant_code,
                "accountNumber": account_number,
                "page": page,
                "page_size": page_size
            }
            
            print(f"  [URL] {transactions_url}")
            print(f"  [PARAMS] {params}")
            
            response = requests.get(
                transactions_url, 
                headers=headers, 
                params=params, 
                timeout=30
            )
            
            print(f"  [RESPONSE] Status: {response.status_code}")
            
            if response.status_code == 200:
                response_data = response.json()
                
                # Check if the request was successful
                if response_data.get('status') == True or response_data.get('statusCode') == '0':
                    print(f"  [OK] Transactions retrieved successfully")
                    
                    # Format and return the response
                    return {
                        "success": True,
                        "environment": sasapay_env,
                        "merchant_code": merchant_code,
                        "merchant_name": merchant['name'],
                        "account_number": account_number,
                        "status": response_data.get('status'),
                        "responseCode": response_data.get('responseCode'),
                        "message": response_data.get('message'),
                        "count": response_data.get('count', 0),
                        "current_page": response_data.get('current_page', page),
                        "pages": response_data.get('pages', 1),
                        "links": response_data.get('links', {}),
                        "transactions": self._format_transaction_response(response_data),
                        "timestamp": datetime.utcnow().isoformat()
                    }, 200
                else:
                    print(f"  [ERROR] API error: {response_data.get('message')}")
                    return {
                        "error": response_data.get('message', 'Failed to retrieve transactions'),
                        "environment": sasapay_env,
                        "merchant_code": merchant_code,
                        "statusCode": response_data.get('statusCode')
                    }, 400
            else:
                print(f"  [ERROR] HTTP {response.status_code}: {response.text[:200]}")
                return {
                    "error": "Failed to retrieve transaction statement",
                    "environment": sasapay_env,
                    "merchant_code": merchant_code,
                    "status_code": response.status_code,
                    "details": response.text
                }, response.status_code
                
        except Exception as e:
            current_app.logger.error(f"SasaPay transaction error for {merchant_code}: {str(e)}")
            return {
                "error": str(e),
                "environment": sasapay_env,
                "merchant_code": merchant_code
            }, 500
    
    def _get_all_merchant_configs(self, environment):
        """Get all merchant configurations with their unique credentials from environment variables"""
        merchants = []
        
        if environment == "production":
            # Base URL for production (used only for token endpoint)
            base_url = os.getenv("SASAPAY_PRODUCTION_BASE_URL", "https://api.sasapay.app/api/v1")
            
            # All merchants with their credentials
            merchant_configs = [
                {"code": "570257", "name": "Kuku Zetu - Mirema", "location": "Mirema", "type": "shop"},
                {"code": "577960", "name": "Kuku Zetu - Lumumba Drive", "location": "Lumumba Drive", "type": "shop"},
                {"code": "577480", "name": "Kuku Zetu - Zimmerman", "location": "Zimmerman", "type": "shop"},
                {"code": "577668", "name": "Kukuzetu - Ngoingwa Stockist", "location": "Ngoingwa", "type": "stockist"},
                {"code": "577666", "name": "KUKUZETU - TRM", "location": "Thika Road Mall", "type": "shop"},
                {"code": "222333", "name": "Kukuzetu - Kasarani Equity", "location": "Kasarani", "type": "shop"},
                {"code": "577123", "name": "Kukuzetu - Kasarani Maternity", "location": "Kasarani", "type": "shop"},
                {"code": "577556", "name": "Kukuzetu - Turi", "location": "Turi", "type": "shop"}
            ]
            
            for config in merchant_configs:
                code = config['code']
                
                # Get unique credentials for this merchant
                client_id = os.getenv(f"SASAPAY_MERCHANT_{code}_CLIENT_ID")
                client_secret = os.getenv(f"SASAPAY_MERCHANT_{code}_CLIENT_SECRET")
                
                if client_id and client_secret:
                    merchants.append({
                        "code": code,
                        "name": config['name'],
                        "location": config['location'],
                        "type": config['type'],
                        "base_url": base_url,
                        "client_id": client_id,
                        "client_secret": client_secret
                    })
                else:
                    print(f"[WARNING] Missing credentials for merchant {code}")
        
        else:  # sandbox environment
            client_id = os.getenv("SASAPAY_SANDBOX_CLIENT_ID")
            client_secret = os.getenv("SASAPAY_SANDBOX_CLIENT_SECRET")
            base_url = os.getenv("SASAPAY_SANDBOX_BASE_URL", "https://sandbox.sasapay.app/api/v1")
            
            if client_id and client_secret:
                merchants.append({
                    "code": "600980",
                    "name": "SasaPay Sandbox Merchant",
                    "location": "Sandbox",
                    "type": "test",
                    "base_url": base_url,
                    "client_id": client_id,
                    "client_secret": client_secret
                })
        
        return merchants
    
    def _get_access_token(self, base_url, client_id, client_secret):
        """Get access token from SasaPay using specific merchant credentials - EXACT same as balance resource"""
        try:
            token_url = f"{base_url}/auth/token/"
            
            params = {
                'grant_type': 'client_credentials'
            }
            
            response = requests.get(
                token_url,
                auth=HTTPBasicAuth(client_id, client_secret),
                params=params,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('status') == True:
                    access_token = data.get('access_token')
                    if access_token:
                        return access_token
                        
            return None
            
        except Exception as e:
            current_app.logger.error(f"Exception getting token: {str(e)}")
            return None
    
    def _format_transaction_response(self, response_data):
        """Format transaction response according to SasaPay documentation"""
        transactions = []
        
        # Extract transactions from response data structure
        if 'data' in response_data and 'transactions' in response_data['data']:
            transaction_list = response_data['data']['transactions']
        elif 'transactions' in response_data:
            transaction_list = response_data['transactions']
        else:
            transaction_list = []
        
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
            
            # Add payment details if available
            if 'payment_details' in tx and tx['payment_details']:
                formatted_tx['payment_details'] = {
                    "party_B_account_number": tx['payment_details'].get('party_B_account_number'),
                    "party_B_account_name": tx['payment_details'].get('party_B_account_name'),
                    "channel_name": tx['payment_details'].get('channel_name'),
                    "channel_transaction_reference": tx['payment_details'].get('channel_transaction_reference')
                }
            
            transactions.append(formatted_tx)
        
        return transactions
    
    def _get_available_merchants(self, environment):
        """Get list of available merchant codes"""
        merchants = self._get_all_merchant_configs(environment)
        return [m['code'] for m in merchants]
    
    def _mock_transaction_response(self, merchant_code, account_number, page, page_size):
        """Mock transaction data for development/testing"""
        import random
        from datetime import datetime, timedelta
        
        print(f"\n{'='*60}")
        print(f"[MOCK MODE] Generating mock transaction data")
        print(f"[MERCHANT] {merchant_code}")
        print(f"[ACCOUNT] {account_number}")
        print(f"{'='*60}")
        
        # Generate mock transactions
        mock_transactions = []
        transaction_types = ["TRANSACTION IN", "TRANSACTION OUT"]
        channels = ["M-PESA", "AIRTEL MONEY", "KCB", "Equity Bank", "SasaPay Wallet"]
        
        # Generate dates for the last 30 days
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)
        
        for i in range(min(page_size, 50)):
            tx_date = start_date + timedelta(days=random.randint(0, 30))
            tx_type = random.choice(transaction_types)
            amount = round(random.uniform(10, 50000), 2)
            charges = round(amount * 0.01, 2) if tx_type == "TRANSACTION IN" else 0
            
            mock_transactions.append({
                "id": 10000 + i + ((page - 1) * page_size),
                "merchant_code": merchant_code,
                "transaction_amount": amount,
                "transaction_charges": charges,
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
        
        # Sort by date descending
        mock_transactions.sort(key=lambda x: x['transaction_date'], reverse=True)
        
        total_count = 137
        total_pages = (total_count + page_size - 1) // page_size
        
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
                "next": f"/api/v2/waas/transactions/?merchantCode={merchant_code}&accountNumber={account_number}&page={page + 1}&page_size={page_size}" if page < total_pages else None,
                "previous": f"/api/v2/waas/transactions/?merchantCode={merchant_code}&accountNumber={account_number}&page={page - 1}&page_size={page_size}" if page > 1 else None
            },
            "transactions": mock_transactions,
            "timestamp": datetime.utcnow().isoformat()
        }, 200


class TestSasaPayConnection(Resource):
    """Test endpoint to verify SasaPay API connection and token generation"""
    
    @jwt_required()
    def get(self):
        """Test SasaPay API connection"""
        
        # Get environment from config
        environment = os.getenv("SASAPAY_ENVIRONMENT", "sandbox")
        base_url = os.getenv("SASAPAY_BASE_URL", "https://sandbox.sasapay.app/api/v1")
        client_id = os.getenv("SASAPAY_CLIENT_ID")
        client_secret = os.getenv("SASAPAY_CLIENT_SECRET")
        
        # Test results
        test_results = {
            "test_time": datetime.utcnow().isoformat(),
            "environment": environment,
            "tests": []
        }
        
        # Test 1: Token Generation
        token_result = self.test_token_generation(base_url, client_id, client_secret)
        test_results["tests"].append(token_result)
        
        # If token successful, test balance fetch
        if token_result.get("success") and token_result.get("access_token"):
            access_token = token_result.get("access_token")
            
            # Test 2: Balance fetch for specific merchant
            merchant_code = request.args.get("merchant_code", "600980")  # Default sandbox merchant
            balance_result = self.test_balance_fetch(base_url, access_token, merchant_code, environment)
            test_results["tests"].append(balance_result)
        
        # Overall status
        test_results["overall_success"] = all(test.get("success", False) for test in test_results["tests"])
        
        return test_results, 200 if test_results["overall_success"] else 500
    
    def test_token_generation(self, base_url, client_id, client_secret):
        """Test token generation endpoint"""
        result = {
            "test_name": "Token Generation",
            "success": False,
            "details": {}
        }
        
        try:
            token_url = f"{base_url}/auth/token/"
            params = {'grant_type': 'client_credentials'}
            
            print(f"[TEST] Token URL: {token_url}")
            print(f"[TEST] Client ID: {client_id[:10]}...")
            
            response = requests.get(
                token_url,
                auth=HTTPBasicAuth(client_id, client_secret),
                params=params,
                timeout=30
            )
            
            result["details"]["status_code"] = response.status_code
            result["details"]["url"] = token_url
            
            if response.status_code == 200:
                data = response.json()
                result["details"]["response_keys"] = list(data.keys())
                
                if data.get('status') == True:
                    access_token = data.get('access_token')
                    result["success"] = True
                    result["access_token"] = access_token
                    result["details"]["token_length"] = len(access_token) if access_token else 0
                    result["details"]["message"] = "Token generated successfully"
                else:
                    result["details"]["error"] = data.get('detail', 'Unknown error')
                    result["details"]["full_response"] = data
            else:
                result["details"]["error"] = f"HTTP {response.status_code}"
                result["details"]["response_body"] = response.text[:500]
                
        except Exception as e:
            result["details"]["exception"] = str(e)
            result["details"]["error"] = f"Exception: {str(e)}"
        
        return result
    
    def test_balance_fetch(self, base_url, access_token, merchant_code, environment):
        """Test balance fetch endpoint"""
        result = {
            "test_name": f"Balance Fetch (Merchant: {merchant_code})",
            "success": False,
            "details": {}
        }
        
        try:
            # Different endpoints for sandbox vs production
            if environment == "production":
                balance_url = f"{base_url}/merchant/balance"
                params = {"merchantCode": merchant_code}
            else:
                balance_url = f"{base_url}/payments/check-balance/"
                params = {"MerchantCode": merchant_code}
            
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            
            print(f"[TEST] Balance URL: {balance_url}")
            print(f"[TEST] Merchant: {merchant_code}")
            
            response = requests.get(
                balance_url,
                headers=headers,
                params=params,
                timeout=30
            )
            
            result["details"]["status_code"] = response.status_code
            result["details"]["url"] = balance_url
            result["details"]["merchant_code"] = merchant_code
            
            if response.status_code == 200:
                data = response.json()
                result["success"] = True
                result["details"]["response_keys"] = list(data.keys())
                
                # Extract balance information
                if environment == "production":
                    result["details"]["ledger_balance"] = data.get("ledgerBalance", 0)
                    result["details"]["available_balance"] = data.get("availableBalance", 0)
                    result["details"]["currency"] = data.get("currency", "KES")
                else:
                    if "data" in data:
                        result["details"]["org_account_balance"] = data["data"].get("OrgAccountBalance", 0)
                        result["details"]["currency"] = data["data"].get("CurrencyCode", "KES")
                        result["details"]["accounts"] = len(data["data"].get("Accounts", []))
                
                result["details"]["message"] = "Balance fetched successfully"
            elif response.status_code == 404:
                # Try alternative endpoint for production
                if environment == "production":
                    alt_url = f"{base_url}/v1/merchant/balance"
                    print(f"[TEST] Trying alternative URL: {alt_url}")
                    
                    alt_response = requests.get(alt_url, headers=headers, params=params, timeout=30)
                    result["details"]["alt_status_code"] = alt_response.status_code
                    
                    if alt_response.status_code == 200:
                        alt_data = alt_response.json()
                        result["success"] = True
                        result["details"]["message"] = "Balance fetched from alternative endpoint"
                        result["details"]["ledger_balance"] = alt_data.get("ledgerBalance", 0)
                    else:
                        result["details"]["error"] = f"Primary and alternative endpoints failed"
                        result["details"]["alt_response"] = alt_response.text[:500]
                else:
                    result["details"]["error"] = f"HTTP {response.status_code} - Not Found"
                    result["details"]["response_body"] = response.text[:500]
            else:
                result["details"]["error"] = f"HTTP {response.status_code}"
                result["details"]["response_body"] = response.text[:500]
                
        except requests.exceptions.Timeout:
            result["details"]["error"] = "Request timeout after 30 seconds"
        except requests.exceptions.ConnectionError:
            result["details"]["error"] = "Connection error - cannot reach SasaPay API"
        except Exception as e:
            result["details"]["error"] = f"Exception: {str(e)}"
            import traceback
            result["details"]["traceback"] = traceback.format_exc()
        
        return result


class TestSasaPaySingleMerchant(Resource):
    """Test specific merchant endpoint"""
    
    @jwt_required()
    def get(self, merchant_code):
        """Test balance for a single merchant with live API call"""
        
        environment = os.getenv("SASAPAY_ENVIRONMENT", "sandbox")
        base_url = os.getenv("SASAPAY_BASE_URL", "https://sandbox.sasapay.app/api/v1")
        client_id = os.getenv("SASAPAY_CLIENT_ID")
        client_secret = os.getenv("SASAPAY_CLIENT_SECRET")
        
        test_data = {
            "merchant_code": merchant_code,
            "environment": environment,
            "timestamp": datetime.utcnow().isoformat(),
            "steps": []
        }
        
        # Step 1: Generate token
        test_data["steps"].append({"step": "Generating token", "status": "started"})
        
        try:
            token_url = f"{base_url}/auth/token/"
            params = {'grant_type': 'client_credentials'}
            
            token_response = requests.get(
                token_url,
                auth=HTTPBasicAuth(client_id, client_secret),
                params=params,
                timeout=30
            )
            
            test_data["steps"].append({
                "step": "Token request",
                "status_code": token_response.status_code,
                "url": token_url
            })
            
            if token_response.status_code != 200:
                test_data["steps"].append({
                    "step": "Token generation",
                    "status": "failed",
                    "error": f"HTTP {token_response.status_code}",
                    "response": token_response.text[:500]
                })
                return test_data, 401
            
            token_data = token_response.json()
            
            if not token_data.get('status'):
                test_data["steps"].append({
                    "step": "Token generation",
                    "status": "failed",
                    "error": token_data.get('detail', 'Unknown error'),
                    "response": token_data
                })
                return test_data, 401
            
            access_token = token_data.get('access_token')
            test_data["steps"].append({
                "step": "Token generation",
                "status": "success",
                "token_length": len(access_token)
            })
            
            # Step 2: Fetch balance
            test_data["steps"].append({"step": "Fetching balance", "status": "started"})
            
            if environment == "production":
                balance_url = f"{base_url}/merchant/balance"
                params = {"merchantCode": merchant_code}
            else:
                balance_url = f"{base_url}/payments/check-balance/"
                params = {"MerchantCode": merchant_code}
            
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            
            balance_response = requests.get(
                balance_url,
                headers=headers,
                params=params,
                timeout=30
            )
            
            test_data["steps"].append({
                "step": "Balance request",
                "status_code": balance_response.status_code,
                "url": balance_url,
                "params": params
            })
            
            if balance_response.status_code == 200:
                balance_data = balance_response.json()
                test_data["success"] = True
                test_data["balance_data"] = balance_data
                
                # Extract useful info
                if environment == "production":
                    test_data["balance"] = balance_data.get("ledgerBalance", 0)
                else:
                    test_data["balance"] = balance_data.get("data", {}).get("OrgAccountBalance", 0)
                
                test_data["steps"].append({
                    "step": "Fetch balance",
                    "status": "success",
                    "balance": test_data["balance"]
                })
            else:
                test_data["success"] = False
                test_data["error"] = f"HTTP {balance_response.status_code}"
                test_data["response_body"] = balance_response.text[:500]
                test_data["steps"].append({
                    "step": "Fetch balance",
                    "status": "failed",
                    "error": test_data["error"]
                })
                
        except Exception as e:
            test_data["success"] = False
            test_data["error"] = str(e)
            test_data["steps"].append({
                "step": "Exception",
                "status": "failed",
                "error": str(e)
            })
            import traceback
            test_data["traceback"] = traceback.format_exc()
        
        return test_data, 200 if test_data.get("success") else 500


class TestNetworkConnectivity(Resource):
    """Test network connectivity to SasaPay API"""
    
    @jwt_required()
    def get(self):
        results = {
            "tests": [],
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Test 1: DNS Resolution
        import socket
        try:
            socket.gethostbyname("api.sasapay.app")
            results["tests"].append({
                "test": "DNS Resolution",
                "status": "PASS",
                "message": "api.sasapay.app resolves correctly"
            })
        except Exception as e:
            results["tests"].append({
                "test": "DNS Resolution",
                "status": "FAIL",
                "error": str(e)
            })
        
        # Test 2: Basic connectivity (ping alternative)
        try:
            import subprocess
            result = subprocess.run(['ping', '-c', '1', 'api.sasapay.app'], 
                                  capture_output=True, timeout=5)
            if result.returncode == 0:
                results["tests"].append({
                    "test": "ICMP Ping",
                    "status": "PASS",
                    "message": "Server is reachable"
                })
            else:
                results["tests"].append({
                    "test": "ICMP Ping",
                    "status": "WARN",
                    "message": "Ping failed (might be blocked)"
                })
        except Exception as e:
            results["tests"].append({
                "test": "ICMP Ping",
                "status": "SKIP",
                "message": f"Ping test skipped: {str(e)}"
            })
        
        # Test 3: HTTPS connectivity
        try:
            response = requests.get("https://api.sasapay.app", timeout=10)
            results["tests"].append({
                "test": "HTTPS Connectivity",
                "status": "PASS",
                "status_code": response.status_code,
                "message": "Can reach SasaPay API"
            })
        except Exception as e:
            results["tests"].append({
                "test": "HTTPS Connectivity",
                "status": "FAIL",
                "error": str(e)
            })
        
        # Test 4: API endpoint direct test
        try:
            test_url = "https://api.sasapay.app/api/v1/merchant/balance"
            response = requests.get(test_url, timeout=10)
            results["tests"].append({
                "test": "API Endpoint Reachable",
                "status": "INFO",
                "status_code": response.status_code,
                "message": "Endpoint returns response (even if unauthorized)"
            })
        except Exception as e:
            results["tests"].append({
                "test": "API Endpoint Reachable",
                "status": "FAIL",
                "error": str(e)
            })
        
        return results, 200



class SasaPaySingleBalanceResource(Resource):

    @jwt_required()
    def get(self):
        """Get merchant account balance from SasaPay"""
        
        # Get current environment (sandbox or production)
        sasapay_env = os.getenv("SASAPAY_ENVIRONMENT", "sandbox")
        
        # Get environment-specific credentials
        if sasapay_env == "production":
            merchant_code = os.getenv("SASAPAY_PRODUCTION_MERCHANT_CODE")
            base_url = os.getenv("SASAPAY_PRODUCTION_BASE_URL")
            client_id = os.getenv("SASAPAY_PRODUCTION_CLIENT_ID")
            client_secret = os.getenv("SASAPAY_PRODUCTION_CLIENT_SECRET")
        else:
            merchant_code = os.getenv("SASAPAY_SANDBOX_MERCHANT_CODE")
            base_url = os.getenv("SASAPAY_SANDBOX_BASE_URL")
            client_id = os.getenv("SASAPAY_SANDBOX_CLIENT_ID")
            client_secret = os.getenv("SASAPAY_SANDBOX_CLIENT_SECRET")
        
        # Validate required credentials
        if not all([merchant_code, base_url, client_id, client_secret]):
            missing = []
            if not merchant_code: missing.append("MERCHANT_CODE")
            if not base_url: missing.append("BASE_URL")
            if not client_id: missing.append("CLIENT_ID")
            if not client_secret: missing.append("CLIENT_SECRET")
            
            return {
                "error": f"Missing SasaPay credentials for {sasapay_env.upper()} environment",
                "missing": missing,
                "environment": sasapay_env
            }, 500
        
        try:
            current_app.logger.info(f"Fetching balance for merchant {merchant_code} in {sasapay_env.upper()} environment")
            
            # Step 1: Get access token with full details
            token_result = self._get_access_token_with_details(base_url, client_id, client_secret)
            
            if not token_result['success']:
                return {
                    "error": "Failed to obtain access token",
                    "environment": sasapay_env,
                    "token_debug_info": token_result.get('debug_info', {}),
                    "token_response": token_result.get('token_response', {})
                }, 401
            
            access_token = token_result['access_token']
            
            # Step 2: Fetch balance using the documented endpoint
            balance_url = f"{base_url}/payments/check-balance/"
            
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            
            params = {
                "MerchantCode": merchant_code
            }
            
            current_app.logger.info(f"Calling SasaPay balance API: {balance_url}")
            
            response = requests.get(
                balance_url,
                headers=headers,
                params=params,
                timeout=30
            )
            
            if response.status_code == 200:
                response_data = response.json()
                
                # Check if the request was successful based on statusCode
                if response_data.get('statusCode') == '0':
                    # Extract balance data
                    data = response_data.get('data', {})
                    
                    return {
                        "success": True,
                        "environment": sasapay_env,
                        "merchant_code": merchant_code,
                        "currency": data.get('CurrencyCode', 'KES'),
                        "total_balance": data.get('OrgAccountBalance', 0),
                        "accounts": data.get('Accounts', []),
                        "message": response_data.get('message', 'Account Balances'),
                        "timestamp": datetime.utcnow().isoformat(),
                        "debug_info": {
                            "auth": token_result['debug_info'],
                            "balance_api_call": {
                                "url": balance_url,
                                "params": params,
                                "status_code": response.status_code
                            }
                        }
                    }, 200
                else:
                    # API returned an error status code
                    return {
                        "error": "SasaPay API returned error",
                        "statusCode": response_data.get('statusCode'),
                        "message": response_data.get('message', 'Unknown error'),
                        "environment": sasapay_env,
                        "full_response": response_data,
                        "token_info": token_result['debug_info']
                    }, 400
            else:
                # HTTP error
                current_app.logger.error(f"SasaPay balance API error: {response.status_code} - {response.text}")
                return {
                    "error": f"SasaPay API returned status code {response.status_code}",
                    "details": response.text,
                    "environment": sasapay_env,
                    "token_info": token_result['debug_info'],
                    "balance_request": {
                        "url": balance_url,
                        "params": params,
                        "headers": {k: v for k, v in headers.items() if k != 'Authorization'}
                    }
                }, response.status_code
                
        except requests.exceptions.Timeout:
            current_app.logger.error("SasaPay balance request timed out")
            return {
                "error": "Request to SasaPay timed out",
                "environment": sasapay_env
            }, 504
        except requests.exceptions.ConnectionError:
            current_app.logger.error("Failed to connect to SasaPay")
            return {
                "error": "Failed to connect to SasaPay API",
                "environment": sasapay_env
            }, 503
        except Exception as e:
            current_app.logger.error(f"SasaPay balance error: {str(e)}")
            return {
                "error": "Internal server error",
                "details": str(e) if current_app.debug else None,
                "environment": sasapay_env
            }, 500
    
    def _get_access_token_with_details(self, base_url, client_id, client_secret):
        """Get access token from SasaPay with full debug information"""
        result = {
            'success': False,
            'access_token': None,
            'debug_info': {},
            'token_response': {}
        }
        
        try:
            token_url = f"{base_url}/auth/token/"
            
            params = {
                'grant_type': 'client_credentials'
            }
            
            # Create Basic Auth header
            auth_string = f"{client_id}:{client_secret}"
            import base64
            auth_base64 = base64.b64encode(auth_string.encode()).decode()
            
            result['debug_info']['auth_method'] = 'HTTP Basic Auth'
            result['debug_info']['token_url'] = token_url
            result['debug_info']['client_id_prefix'] = client_id[:20] + '...' if len(client_id) > 20 else client_id
            result['debug_info']['auth_header'] = f"Basic {auth_base64[:20]}..."
            result['debug_info']['grant_type'] = params['grant_type']
            
            current_app.logger.info(f"Requesting token from: {token_url}")
            
            response = requests.get(
                token_url,
                auth=HTTPBasicAuth(client_id, client_secret),
                params=params,
                timeout=30
            )
            
            result['debug_info']['request_method'] = 'GET'
            result['debug_info']['response_status_code'] = response.status_code
            
            if response.status_code == 200:
                data = response.json()
                result['token_response'] = data
                
                # According to SasaPay docs, response should have status=True
                if data.get('status') == True:
                    access_token = data.get('access_token')
                    if access_token:
                        result['success'] = True
                        result['access_token'] = access_token
                        result['debug_info']['token_received'] = True
                        result['debug_info']['token_prefix'] = access_token[:30] + '...' if len(access_token) > 30 else access_token
                        result['debug_info']['expires_in'] = data.get('expires_in', 'N/A')
                        result['debug_info']['token_type'] = data.get('token_type', 'N/A')
                        current_app.logger.info("Successfully obtained access token")
                    else:
                        result['debug_info']['error'] = 'No access_token in response'
                        result['debug_info']['response_keys'] = list(data.keys())
                        current_app.logger.error(f"No access_token in response: {data}")
                else:
                    result['debug_info']['error'] = f"Status false: {data.get('detail', 'Unknown error')}"
                    result['debug_info']['full_response'] = data
                    current_app.logger.error(f"Token request failed: {data.get('detail', 'Unknown error')}")
            else:
                result['debug_info']['error'] = f"HTTP {response.status_code}"
                result['debug_info']['response_body'] = response.text[:500]  # Limit length
                current_app.logger.error(f"Token request HTTP error: {response.status_code} - {response.text}")
                
            return result
            
        except Exception as e:
            result['debug_info']['error'] = str(e)
            result['debug_info']['exception_type'] = type(e).__name__
            current_app.logger.error(f"Exception getting token: {str(e)}")
            return result
    
    def _get_access_token(self, base_url, client_id, client_secret):
        """Legacy method for compatibility - returns just the token"""
        result = self._get_access_token_with_details(base_url, client_id, client_secret)
        return result['access_token'] if result['success'] else None



class SasaPayBusinessToBeneficiaryResource(Resource):
    
    @jwt_required()
    def post(self):
        """Transfer funds from one merchant to another merchant's beneficiary account (B2B)"""
        
        # Get request data
        data = request.get_json()
        
        # Validate required fields
        required_fields = [
            'sender_merchant_code', 'receiver_merchant_code', 
            'beneficiary_account_number', 'amount', 'callback_url'
        ]
        missing_fields = [field for field in required_fields if field not in data]
        
        if missing_fields:
            return {
                "error": f"Missing required fields: {', '.join(missing_fields)}",
                "required_fields": required_fields
            }, 400
        
        sender_merchant_code = data['sender_merchant_code']
        receiver_merchant_code = data['receiver_merchant_code']
        beneficiary_account_number = data['beneficiary_account_number']
        amount = data['amount']
        callback_url = data['callback_url']
        
        # Optional fields
        transaction_reference = data.get('transaction_reference', self._generate_transaction_reference())
        transaction_fee = data.get('transaction_fee', 0)
        reason = data.get('reason', '')
        
        # Get current environment
        sasapay_env = data.get('environment', os.getenv("SASAPAY_ENVIRONMENT", "sandbox"))
        
        # Get all merchant configurations with their unique credentials
        merchants = self._get_all_merchant_configs(sasapay_env)
        
        # Find the sender merchant (must have credentials to authenticate)
        sender_merchant = next((m for m in merchants if m['code'] == sender_merchant_code), None)
        if not sender_merchant:
            return {
                "error": f"Sender merchant {sender_merchant_code} not found or not configured",
                "available_merchants": [m['code'] for m in merchants],
                "environment": sasapay_env
            }, 404
        
        try:
            current_app.logger.info(
                f"Initiating B2B transfer from {sender_merchant_code} to {receiver_merchant_code} "
                f"beneficiary {beneficiary_account_number} in {sasapay_env.upper()}"
            )
            print(f"\n{'='*60}")
            print(f"[ENV] Environment: {sasapay_env.upper()}")
            print(f"[TRANSFER] From: {sender_merchant['name']} ({sender_merchant_code})")
            print(f"[TRANSFER] To Beneficiary: {beneficiary_account_number}")
            print(f"[TRANSFER] Receiver Merchant: {receiver_merchant_code}")
            print(f"[AMOUNT] {amount} KES")
            print(f"[REF] Transaction Reference: {transaction_reference}")
            print(f"{'='*60}")
            
            # STEP 1: Get access token using SENDER merchant's credentials
            print(f"[1/2] Getting auth token for sender {sender_merchant_code}...")
            access_token = self._get_access_token(
                sender_merchant['base_url'], 
                sender_merchant['client_id'], 
                sender_merchant['client_secret']
            )
            
            if not access_token:
                print(f"[ERROR] Failed to obtain access token")
                return {
                    "error": "Authentication failed - Invalid client credentials for sender merchant",
                    "merchant_code": sender_merchant_code,
                    "environment": sasapay_env
                }, 401
            
            print(f"[OK] Token obtained")
            print(f"[2/2] Initiating B2B transfer...")
            
            # STEP 2: Make Business to Beneficiary request using the token
            # Use the Business to Beneficiary endpoint as per documentation [citation:1]
            b2b_url = f"{sender_merchant['base_url']}/transfers/business-to-beneficiary"
            
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
            
            payload = {
                "TransactionReference": transaction_reference,
                "SenderMerchantCode": sender_merchant_code,
                "ReceiverMerchantCode": receiver_merchant_code,
                "BeneficiaryAccountNumber": beneficiary_account_number,
                "Amount": float(amount),
                "TransactionFee": float(transaction_fee),
                "Reason": reason,
                "CallBackUrl": callback_url
            }
            
            response = requests.post(
                b2b_url,
                json=payload,
                headers=headers,
                timeout=30
            )
            
            # STEP 3: Process response
            if response.status_code == 200:
                response_data = response.json()
                
                if response_data.get('status') == True:
                    print(f"[SUCCESS] Transfer initiated: {response_data.get('message')}")
                    print(f"[CHECKOUT ID] {response_data.get('checkoutRequestId')}")
                    
                    return {
                        "success": True,
                        "sender_merchant_code": sender_merchant_code,
                        "sender_merchant_name": sender_merchant['name'],
                        "receiver_merchant_code": receiver_merchant_code,
                        "beneficiary_account_number": beneficiary_account_number,
                        "amount": float(amount),
                        "currency": "KES",
                        "transaction_reference": transaction_reference,
                        "checkout_request_id": response_data.get('checkoutRequestId'),
                        "merchant_request_id": response_data.get('merchantRequestID'),
                        "message": response_data.get('message', 'Transaction is being processed'),
                        "environment": sasapay_env,
                        "status": "pending",
                        "timestamp": datetime.utcnow().isoformat()
                    }, 200
                else:
                    print(f"[FAILED] {response_data.get('message')}")
                    return {
                        "success": False,
                        "sender_merchant_code": sender_merchant_code,
                        "error": response_data.get('message', 'B2B transfer failed'),
                        "environment": sasapay_env
                    }, 400
            else:
                print(f"[ERROR] HTTP {response.status_code}: {response.text}")
                current_app.logger.error(
                    f"B2B transfer failed: HTTP {response.status_code} - {response.text}"
                )
                return {
                    "success": False,
                    "error": f"SasaPay API returned {response.status_code}",
                    "details": response.text,
                    "environment": sasapay_env
                }, response.status_code
                
        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"Network error: {str(e)}")
            return {
                "error": "Failed to connect to SasaPay",
                "details": str(e),
                "environment": sasapay_env
            }, 500
        except Exception as e:
            current_app.logger.error(f"Unexpected error: {str(e)}")
            return {"error": str(e), "environment": sasapay_env}, 500
    
    def _generate_transaction_reference(self):
        """Generate a unique transaction reference"""
        import uuid
        return f"B2B{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{str(uuid.uuid4())[:8]}"
    
    def _get_all_merchant_configs(self, environment):
        """Get all merchant configurations with their unique credentials from environment variables"""
        merchants = []
        
        if environment == "production":
            # Base URL for production
            base_url = os.getenv("SASAPAY_PRODUCTION_BASE_URL", "https://api.sasapay.app/api/v1")
            
            # All production merchants
            merchant_configs = [
                {"code": "570257", "name": "Kuku Zetu - Mirema", "location": "Mirema", "type": "shop"},
                {"code": "577960", "name": "Kuku Zetu - Lumumba Drive", "location": "Lumumba Drive", "type": "shop"},
                {"code": "577480", "name": "Kuku Zetu - Zimmerman", "location": "Zimmerman", "type": "shop"},
                {"code": "577668", "name": "Kukuzetu - Ngoingwa Stockist", "location": "Ngoingwa", "type": "stockist"},
                {"code": "577666", "name": "KUKUZETU - TRM", "location": "Thika Road Mall", "type": "shop"},
                {"code": "222333", "name": "Kukuzetu - Kasarani Equity", "location": "Kasarani", "type": "shop"},
                {"code": "577123", "name": "Kukuzetu - Kasarani Maternity", "location": "Kasarani", "type": "shop"},
                {"code": "577556", "name": "Kukuzetu - Turi", "location": "Turi", "type": "shop"}
            ]
            
            for config in merchant_configs:
                code = config['code']
                
                # Get unique credentials for this merchant
                client_id = os.getenv(f"SASAPAY_MERCHANT_{code}_CLIENT_ID")
                client_secret = os.getenv(f"SASAPAY_MERCHANT_{code}_CLIENT_SECRET")
                
                if client_id and client_secret:
                    merchants.append({
                        "code": code,
                        "name": config['name'],
                        "location": config['location'],
                        "type": config['type'],
                        "base_url": base_url,
                        "client_id": client_id,
                        "client_secret": client_secret
                    })
                else:
                    print(f"[WARNING] Missing credentials for merchant {code}")
        
        else:  # sandbox environment
            client_id = os.getenv("SASAPAY_SANDBOX_CLIENT_ID")
            client_secret = os.getenv("SASAPAY_SANDBOX_CLIENT_SECRET")
            base_url = os.getenv("SASAPAY_SANDBOX_BASE_URL", "https://sandbox.sasapay.app/api/v1")
            
            if client_id and client_secret:
                merchants.append({
                    "code": "600980",
                    "name": "SasaPay Sandbox Merchant",
                    "location": "Sandbox",
                    "type": "test",
                    "base_url": base_url,
                    "client_id": client_id,
                    "client_secret": client_secret
                })
        
        return merchants
    
    def _get_access_token(self, base_url, client_id, client_secret):
        """Get access token from SasaPay using specific merchant credentials"""
        try:
            token_url = f"{base_url}/auth/token/"
            
            params = {
                'grant_type': 'client_credentials'
            }
            
            response = requests.get(
                token_url,
                auth=HTTPBasicAuth(client_id, client_secret),
                params=params,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('status') == True:
                    access_token = data.get('access_token')
                    if access_token:
                        return access_token
                        
            return None
            
        except Exception as e:
            current_app.logger.error(f"Exception getting token: {str(e)}")
            return None