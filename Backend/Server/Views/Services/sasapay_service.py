# Server/Views/Services/sasapay_service.py
import requests
import json
import uuid
from datetime import datetime
from requests.auth import HTTPBasicAuth
from flask import current_app
import logging

logger = logging.getLogger(__name__)

class SasaPayService:
    """Service to handle SasaPay STK push operations"""
    
    # Cache for access token (in production, use Redis)
    _access_token = None
    _token_expiry = None
    
    @classmethod
    def _get_access_token(cls):
        """Get access token with caching"""
        # Check if cached token is still valid
        if cls._access_token and cls._token_expiry:
            if datetime.utcnow() < cls._token_expiry:
                return cls._access_token
        
        base_url = current_app.config.get("SASAPAY_BASE_URL")
        client_id = current_app.config.get("SASAPAY_CLIENT_ID")
        client_secret = current_app.config.get("SASAPAY_CLIENT_SECRET")
        
        if not all([base_url, client_id, client_secret]):
            logger.error("SasaPay credentials not configured")
            return None
        
        try:
            token_url = f"{base_url}/auth/token/"
            response = requests.get(
                token_url,
                auth=HTTPBasicAuth(client_id, client_secret),
                params={'grant_type': 'client_credentials'},
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == True:
                    cls._access_token = data.get('access_token')
                    # Set expiry (default 1 hour, but use from response if available)
                    expires_in = data.get('expires_in', 3600)
                    cls._token_expiry = datetime.utcnow().replace(
                        second=datetime.utcnow().second + expires_in - 300  # 5 min buffer
                    )
                    return cls._access_token
            else:
                logger.error(f"Failed to get token: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting access token: {str(e)}")
            return None
    
    @classmethod
    def initiate_stk_push(cls, phone_number, amount, sale_id, customer_name=None, reference=None):
        """
        Initiate STK push to customer's phone
        
        Args:
            phone_number (str): Customer's phone number (format: 2547XXXXXXXX)
            amount (float): Amount to charge
            sale_id (int): Sale ID for reference
            customer_name (str): Customer name
            reference (str): Optional transaction reference
        
        Returns:
            dict: Response from SasaPay
        """
        # Mock mode for development
        if current_app.config.get("SASAPAY_USE_MOCK", False):
            return cls._mock_stk_push_response(phone_number, amount, sale_id)
        
        access_token = cls._get_access_token()
        if not access_token:
            return {
                "success": False,
                "error": "Failed to obtain access token"
            }
        
        base_url = current_app.config.get("SASAPAY_BASE_URL")
        merchant_code = current_app.config.get("SASAPAY_MERCHANT_CODE")
        stk_push_url = f"{base_url}/payments/stk-push/"
        
        # Format phone number (ensure it starts with 254)
        phone_number = cls._format_phone_number(phone_number)
        
        # Generate unique transaction reference if not provided
        if not reference:
            reference = f"SALE{sale_id}{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        
        # Prepare payload according to SasaPay STK push format
        payload = {
            "MerchantCode": merchant_code,
            "PhoneNumber": phone_number,
            "Amount": str(round(amount, 2)),
            "TransactionReference": reference,
            "TransactionDesc": f"Payment for Sale #{sale_id}",
            "CustomerName": customer_name or "Customer",
            "TransactionType": "PAY_BILL",  # or "BUY_GOODS" depending on your setup
            "CallBackURL": current_app.config.get("SASAPAY_CALLBACK_URL"),
            "TransactionDate": datetime.utcnow().strftime("%Y%m%d%H%M%S")
        }
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        try:
            logger.info(f"Initiating STK push for sale {sale_id} to {phone_number} for amount {amount}")
            
            response = requests.post(
                stk_push_url,
                json=payload,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                # Check if the response indicates success
                if result.get("statusCode") == "0" or result.get("success") == True:
                    return {
                        "success": True,
                        "sale_id": sale_id,
                        "amount": amount,
                        "phone_number": phone_number,
                        "transaction_reference": reference,
                        "sasapay_response": result,
                        "checkout_request_id": result.get("CheckoutRequestID") or result.get("requestId"),
                        "message": "STK push initiated successfully. Please check your phone and enter PIN."
                    }
                else:
                    return {
                        "success": False,
                        "error": result.get("message") or result.get("errorMessage") or "STK push failed",
                        "sasapay_response": result
                    }
            else:
                logger.error(f"STK push failed with status {response.status_code}: {response.text}")
                return {
                    "success": False,
                    "error": f"Failed to initiate STK push: {response.status_code}",
                    "details": response.text
                }
                
        except requests.Timeout:
            logger.error(f"STK push timeout for sale {sale_id}")
            return {
                "success": False,
                "error": "Request timeout. Please try again."
            }
        except Exception as e:
            logger.error(f"Error initiating STK push: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    @classmethod
    def _format_phone_number(cls, phone_number):
        """Format phone number to international format (254XXXXXXXX)"""
        # Remove any non-digit characters
        phone = ''.join(filter(str.isdigit, str(phone_number)))
        
        # Remove leading zero if present
        if phone.startswith('0'):
            phone = phone[1:]
        
        # Add 254 if not present
        if not phone.startswith('254'):
            phone = '254' + phone
        
        return phone
    
    @classmethod
    def _mock_stk_push_response(cls, phone_number, amount, sale_id):
        """Mock STK push response for development"""
        return {
            "success": True,
            "mock": True,
            "sale_id": sale_id,
            "amount": amount,
            "phone_number": cls._format_phone_number(phone_number),
            "transaction_reference": f"MOCK{sale_id}{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            "checkout_request_id": str(uuid.uuid4()),
            "message": "MOCK: STK push simulated. In production, customer would receive payment prompt."
        }