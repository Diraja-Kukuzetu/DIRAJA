import requests
import json
from requests.auth import HTTPBasicAuth
from flask_restful import Resource
from flask import current_app, request
from flask_jwt_extended import jwt_required
import os
from datetime import datetime

class SasaPayBalanceResource(Resource):

    @jwt_required()
    def get(self):
        """Get merchant account balances from SasaPay (supports multiple merchants)"""
        
        # Get specific merchant code from query params, or fetch all
        merchant_code_param = request.args.get('merchant_code')
        fetch_all = request.args.get('all', 'false').lower() == 'true'
        
        # Get current environment
        sasapay_env = os.getenv("SASAPAY_ENVIRONMENT", "sandbox")
        
        # Define merchant accounts based on environment
        merchants = self._get_merchant_accounts(sasapay_env)
        
        # If specific merchant requested
        if merchant_code_param:
            merchants = [m for m in merchants if m['code'] == merchant_code_param]
            if not merchants:
                return {
                    "error": f"Merchant {merchant_code_param} not found in {sasapay_env} environment",
                    "available_merchants": [m['code'] for m in self._get_merchant_accounts(sasapay_env)]
                }, 404
        
        # Mock mode for development
        if current_app.config.get("SASAPAY_USE_MOCK", False):
            return self._mock_multi_merchant_response(merchants, sasapay_env)
        
        base_url = current_app.config["SASAPAY_BASE_URL"]
        client_id = current_app.config["SASAPAY_CLIENT_ID"]
        client_secret = current_app.config["SASAPAY_CLIENT_SECRET"]
        
        try:
            # Log environment being used
            current_app.logger.info(f"Checking SasaPay balances in {sasapay_env.upper()} environment")
            print(f"\n🌍 Environment: {sasapay_env.upper()}")
            print(f"📍 Base URL: {base_url}")
            print(f"📊 Fetching balances for {len(merchants)} merchants")
            
            # Step 1: Get access token (reused for all merchants)
            access_token = self._get_access_token(base_url, client_id, client_secret, sasapay_env)
            if not access_token:
                return {
                    "error": "Failed to obtain access token", 
                    "environment": sasapay_env
                }, 401
            
            # Step 2: Fetch balances for all merchants
            all_balances = []
            total_combined_balance = 0
            
            for merchant in merchants:
                merchant_code = merchant['code']
                merchant_name = merchant['name']
                
                print(f"\n🔍 Fetching balance for {merchant_name} ({merchant_code})...")
                
                balance_data = self._fetch_merchant_balance(
                    base_url, access_token, merchant_code, sasapay_env
                )
                
                if balance_data:
                    merchant_balance = {
                        "merchant_code": merchant_code,
                        "merchant_name": merchant_name,
                        "location": merchant.get('location', ''),
                        "type": merchant.get('type', 'shop'),
                        "balances": balance_data
                    }
                    
                    # Extract total balance
                    if sasapay_env == "production":
                        total = balance_data.get('ledger_balance', 0)
                    else:
                        total = balance_data.get('org_account_balance', 0)
                    
                    merchant_balance['total_balance'] = total
                    total_combined_balance += total
                    
                    all_balances.append(merchant_balance)
                else:
                    all_balances.append({
                        "merchant_code": merchant_code,
                        "merchant_name": merchant_name,
                        "error": "Failed to fetch balance",
                        "total_balance": 0
                    })
            
            # Return combined response
            return {
                "success": True,
                "environment": sasapay_env,
                "total_merchants": len(merchants),
                "total_combined_balance": total_combined_balance,
                "currency": "KES",
                "merchants": all_balances,
                "timestamp": datetime.utcnow().isoformat()
            }, 200
                
        except Exception as e:
            current_app.logger.error(f"SasaPay balance error in {sasapay_env}: {str(e)}")
            return {
                "error": str(e),
                "environment": sasapay_env
            }, 500
    
    def _get_merchant_accounts(self, environment):
        """Get merchant accounts based on environment"""
        
        # Sandbox accounts (original test accounts)
        sandbox_merchants = [
            {"code": "600980", "name": "SasaPay Sandbox Merchant", "location": "Sandbox", "type": "test"},
        ]
        
        # Production accounts (all your real merchants)
        production_merchants = [
            {"code": "570257", "name": "Kuku Zetu - Mirema", "location": "Mirema", "type": "shop"},
            {"code": "577960", "name": "Kuku Zetu - Lumumba Drive", "location": "Lumumba Drive", "type": "shop"},
            {"code": "577480", "name": "Kuku Zetu - Zimmerman", "location": "Zimmerman", "type": "shop"},
            {"code": "577481", "name": "Kuku Zetu - Mabanda", "location": "Mabanda", "type": "shop"},
            {"code": "577668", "name": "Kukuzetu - Ngoingwa Stockist", "location": "Ngoingwa", "type": "stockist"},
            {"code": "577667", "name": "Kukuzetu - Umoja 2 Stockist", "location": "Umoja 2", "type": "stockist"},
            {"code": "577111", "name": "Kukuzetu - Deliveries", "location": "Nairobi", "type": "delivery"},
            {"code": "577666", "name": "KUKUZETU - TRM", "location": "Thika Road Mall", "type": "shop"},
            {"code": "222333", "name": "Kukuzetu - Kasarani Equity", "location": "Kasarani", "type": "shop"},
            {"code": "577123", "name": "Kukuzetu - Kasarani Maternity", "location": "Kasarani", "type": "shop"},
            {"code": "577556", "name": "Kukuzetu - Turi", "location": "Turi", "type": "shop"},
            {"code": "577555", "name": "Kukuzetu - Mabanda Shopping Centre", "location": "Mabanda", "type": "shop"},
            {"code": "577444", "name": "Kukuzetu - Shwari Ngara", "location": "Ngara", "type": "shop"},
            {"code": "577112", "name": "Kukuzetu - Thika Jamhuri Market", "location": "Thika", "type": "shop"},
            {"code": "577777", "name": "Kukuzetu - Kang'undo Zimmerman Store", "location": "Zimmerman", "type": "shop"},
            {"code": "577333", "name": "Kukuzetu - Kang'undo Road Market", "location": "Kang'undo Road", "type": "market"},
            {"code": "577222", "name": "Kukuzetu - Kisumu", "location": "Kisumu", "type": "shop"},
        ]
        
        # Return appropriate list based on environment
        if environment == "production":
            return production_merchants
        else:
            return sandbox_merchants
    
    def _fetch_merchant_balance(self, base_url, access_token, merchant_code, environment):
        """Fetch balance for a specific merchant"""
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
            
            response = requests.get(
                balance_url, 
                headers=headers, 
                params=params, 
                timeout=30
            )
            
            if response.status_code == 200:
                response_data = response.json()
                return self._format_balance_response(response_data, environment, merchant_code)
            else:
                # Try alternative endpoint for production
                if environment == "production" and response.status_code == 404:
                    alt_url = f"{base_url}/v1/merchant/balance"
                    alt_response = requests.get(alt_url, headers=headers, params=params, timeout=30)
                    if alt_response.status_code == 200:
                        return self._format_balance_response(alt_response.json(), environment, merchant_code)
                
                current_app.logger.error(f"Failed to fetch balance for {merchant_code}: {response.status_code}")
                return None
                
        except Exception as e:
            current_app.logger.error(f"Error fetching balance for {merchant_code}: {str(e)}")
            return None
    
    def _get_access_token(self, base_url, client_id, client_secret, environment):
        """Helper method to get access token for specific environment"""
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
        else:
            current_app.logger.error(f"Token fetch failed for {environment}: {response.status_code}")
        
        return None
    
    def _format_balance_response(self, response_data, environment, merchant_code):
        """Format balance response consistently across environments"""
        formatted = {
            "raw_response": response_data,
            "environment": environment
        }
        
        if environment == "production":
            formatted["currency"] = response_data.get("currency", "KES")
            formatted["available_balance"] = response_data.get("availableBalance", 0)
            formatted["ledger_balance"] = response_data.get("ledgerBalance", 0)
            formatted["accounts"] = response_data.get("accounts", [])
        else:
            if "data" in response_data:
                formatted["currency"] = response_data["data"].get("CurrencyCode", "KES")
                formatted["org_account_balance"] = response_data["data"].get("OrgAccountBalance", 0)
                formatted["accounts"] = response_data["data"].get("Accounts", [])
            else:
                formatted["data"] = response_data
        
        return formatted
    
    def _mock_multi_merchant_response(self, merchants, environment):
        """Mock balance data for multiple merchants"""
        mock_balances = []
        total = 0
        
        if environment == "production":
            # Production mock data
            mock_data = {
                "570257": 15750.50,
                "577960": 8930.75,
                "577480": 12450.00,
                "577481": 6720.25,
                "577668": 3450.00,
                "577667": 2890.50,
                "577111": 500.00,
                "577666": 23500.00,
                "222333": 8760.30,
                "577123": 4320.80,
                "577556": 5670.45,
                "577555": 7890.60,
                "577444": 12340.90,
                "577112": 9870.20,
                "577777": 4560.75,
                "577333": 3450.30,
                "577222": 18450.30,
            }
        else:
            # Sandbox mock data (only the test merchant)
            mock_data = {
                "600980": 13384.05,
            }
        
        for merchant in merchants:
            balance = mock_data.get(merchant['code'], 5000.00)
            total += balance
            
            if environment == "production":
                accounts = [
                    {"account_label": "Main Account", "account_balance": round(balance * 0.7, 2)},
                    {"account_label": "Working Account", "account_balance": round(balance * 0.3, 2)}
                ]
                org_balance = round(balance, 2)
            else:
                # Sandbox accounts structure (matching your original response)
                accounts = [
                    {"account_label": "Bulk Payment", "account_balance": 743},
                    {"account_label": "Utility Account", "account_balance": 8.71},
                    {"account_label": "Working Account", "account_balance": 12786.34}
                ]
                org_balance = 13384.05
            
            mock_balances.append({
                "merchant_code": merchant['code'],
                "merchant_name": merchant['name'],
                "location": merchant.get('location', ''),
                "type": merchant.get('type', 'shop'),
                "total_balance": org_balance,
                "balances": {
                    "environment": environment,
                    "currency": "KES",
                    "org_account_balance": org_balance,
                    "accounts": accounts
                }
            })
        
        return {
            "success": True,
            "mock": True,
            "environment": environment,
            "total_merchants": len(merchants),
            "total_combined_balance": round(total, 2),
            "currency": "KES",
            "merchants": mock_balances,
            "warning": "MOCK DATA - Not real balances" if environment == "production" else "MOCK SANDBOX DATA",
            "timestamp": datetime.utcnow().isoformat()
        }, 200







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
        page = request.args.get('page', 1)
        page_size = request.args.get('page_size', 50)
        
        # Validate required parameters
        if not merchant_code:
            return {
                "error": "merchant_code is required",
                "available_merchants": [m['code'] for m in self._get_merchant_accounts(os.getenv("SASAPAY_ENVIRONMENT", "sandbox"))]
            }, 400
        
        if not account_number:
            return {
                "error": "account_number is required",
                "message": "Please provide the account number to fetch transactions for"
            }, 400
        
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
            return self._mock_transaction_response(merchant_code, account_number, int(page), int(page_size))
        
        base_url = current_app.config["SASAPAY_BASE_URL"]
        client_id = current_app.config["SASAPAY_CLIENT_ID"]
        client_secret = current_app.config["SASAPAY_CLIENT_SECRET"]
        
        try:
            # Log environment being used
            current_app.logger.info(f"Fetching transactions for merchant {merchant_code} in {sasapay_env.upper()} environment")
            print(f"\n🌍 Environment: {sasapay_env.upper()}")
            print(f"📍 Base URL: {base_url}")
            print(f"🔑 Merchant Code: {merchant_code}")
            print(f"📱 Account Number: {account_number}")
            
            # Step 1: Get access token
            access_token = self._get_access_token(base_url, client_id, client_secret, sasapay_env)
            if not access_token:
                return {
                    "error": "Failed to obtain access token", 
                    "environment": sasapay_env
                }, 401
            
            # Step 2: Get transaction statement
            # Use v2 endpoint as per documentation
            transactions_url = f"{base_url}/api/v2/waas/transactions/"
            
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            
            params = {
                "merchantCode": merchant_code,
                "accountNumber": account_number,
                "page": int(page),
                "page_size": int(page_size)
            }
            
            response = requests.get(
                transactions_url, 
                headers=headers, 
                params=params, 
                timeout=30
            )
            
            if response.status_code == 200:
                response_data = response.json()
                
                # Format and return the response
                return {
                    "success": True,
                    "environment": sasapay_env,
                    "merchant_code": merchant_code,
                    "account_number": account_number,
                    "transactions": self._format_transaction_response(response_data),
                    "pagination": {
                        "current_page": response_data.get('current_page', 1),
                        "total_pages": response_data.get('pages', 1),
                        "total_transactions": response_data.get('count', 0),
                        "has_next": response_data.get('links', {}).get('next') is not None,
                        "has_previous": response_data.get('links', {}).get('previous') is not None
                    },
                    "timestamp": datetime.utcnow().isoformat()
                }, 200
            else:
                return {
                    "error": "Failed to retrieve transaction statement",
                    "environment": sasapay_env,
                    "status_code": response.status_code,
                    "details": response.text
                }, response.status_code
                
        except Exception as e:
            current_app.logger.error(f"SasaPay transaction error in {sasapay_env}: {str(e)}")
            return {
                "error": str(e),
                "environment": sasapay_env
            }, 500
    
    def _get_access_token(self, base_url, client_id, client_secret, environment):
        """Helper method to get access token for specific environment"""
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
        else:
            current_app.logger.error(f"Token fetch failed for {environment}: {response.status_code}")
        
        return None
    
    def _format_transaction_response(self, response_data):
        """Format transaction response for cleaner output"""
        transactions = []
        
        if 'data' in response_data and 'transactions' in response_data['data']:
            for tx in response_data['data']['transactions']:
                formatted_tx = {
                    "id": tx.get('id'),
                    "amount": tx.get('transaction_amount', 0),
                    "charges": tx.get('transaction_charges', 0),
                    "type": tx.get('transaction_type'),
                    "code": tx.get('transaction_code'),
                    "description": tx.get('transaction_description'),
                    "reference": tx.get('transaction_reference'),
                    "date": tx.get('transaction_date'),
                    "status": {
                        "code": tx.get('result_code'),
                        "description": tx.get('result_description')
                    },
                    "reversal_status": tx.get('reversal_status'),
                    "created_date": tx.get('created_date')
                }
                
                # Add payment details if available
                if 'payment_details' in tx and tx['payment_details']:
                    formatted_tx['payment_details'] = {
                        "account_number": tx['payment_details'].get('party_B_account_number'),
                        "channel": tx['payment_details'].get('channel_name'),
                        "channel_reference": tx['payment_details'].get('channel_transaction_reference')
                    }
                
                transactions.append(formatted_tx)
        
        return transactions
    
    def _get_merchant_accounts(self, environment):
        """Get merchant accounts based on environment"""
        if environment == "production":
            return [
                {"code": "570257", "name": "Kuku Zetu - Mirema"},
                {"code": "577960", "name": "Kuku Zetu - Lumumba Drive"},
                {"code": "577480", "name": "Kuku Zetu - Zimmerman"},
                {"code": "577481", "name": "Kuku Zetu - Mabanda"},
                {"code": "577668", "name": "Kukuzetu - Ngoingwa Stockist"},
                {"code": "577667", "name": "Kukuzetu - Umoja 2 Stockist"},
                {"code": "577111", "name": "Kukuzetu - Deliveries"},
                {"code": "577666", "name": "KUKUZETU - TRM"},
                {"code": "222333", "name": "Kukuzetu - Kasarani Equity"},
                {"code": "577123", "name": "Kukuzetu - Kasarani Maternity"},
                {"code": "577556", "name": "Kukuzetu - Turi"},
                {"code": "577555", "name": "Kukuzetu - Mabanda Shopping Centre"},
                {"code": "577444", "name": "Kukuzetu - Shwari Ngara"},
                {"code": "577112", "name": "Kukuzetu - Thika Jamhuri Market"},
                {"code": "577777", "name": "Kukuzetu - Kang'undo Zimmerman Store"},
                {"code": "577333", "name": "Kukuzetu - Kang'undo Road Market"},
                {"code": "577222", "name": "Kukuzetu - Kisumu"},
            ]
        else:
            return [
                {"code": "600980", "name": "SasaPay Sandbox Merchant"},
            ]
    
    def _mock_transaction_response(self, merchant_code, account_number, page, page_size):
        """Mock transaction data for development"""
        import random
        from datetime import datetime, timedelta
        
        # Generate mock transactions
        mock_transactions = []
        transaction_types = ["TRANSACTION IN", "TRANSACTION OUT"]
        channels = ["M-PESA", "AIRTEL MONEY", "KCB", "Equity Bank", "SasaPay Wallet"]
        status_codes = ["SP00000", "SP00001", "SP00002"]
        status_descriptions = [
            "Transaction completed successfully",
            "Transaction pending",
            "Transaction failed"
        ]
        
        # Generate dates for the last 30 days
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)
        
        for i in range(min(page_size, 50)):  # Max 50 per page
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
                "result_code": random.choice(status_codes),
                "result_description": random.choice(status_descriptions),
                "reversal_status": "NOT REVERSED" if random.random() > 0.1 else "REVERSED",
                "created_date": tx_date.strftime("%Y-%m-%dT%H:%M:%S+03:00")
            })
        
        # Sort by date descending
        mock_transactions.sort(key=lambda x: x['transaction_date'], reverse=True)
        
        total_count = 137  # Mock total count
        total_pages = (total_count + page_size - 1) // page_size
        
        return {
            "success": True,
            "mock": True,
            "environment": "sandbox",
            "merchant_code": merchant_code,
            "account_number": account_number,
            "warning": "MOCK DATA - This is simulated transaction data for testing",
            "transactions": mock_transactions,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_transactions": total_count,
                "page_size": page_size,
                "has_next": page < total_pages,
                "has_previous": page > 1
            },
            "timestamp": datetime.utcnow().isoformat()
        }, 200