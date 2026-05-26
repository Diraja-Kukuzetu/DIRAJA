import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from dotenv import load_dotenv
from flask_socketio import SocketIO
from flask_mail import Mail
from openai import OpenAI  

# Load env
load_dotenv()

# ---------- Extensions ----------
db = SQLAlchemy()
jwt = JWTManager()
mail = Mail()
socketio = SocketIO()

# ---------- Models Import ----------
def initialize_models():
    from Server.Models.Users import Users
    from Server.Models.Shops import Shops
    from Server.Models.Sales import Sales
    from Server.Models.Bank import Bank
    from Server.Models.Customers import Customers
    from Server.Models.Employees import Employees
    from Server.Models.EmployeeLoan import EmployeeLoan
    from Server.Models.Stock import Stock
    from Server.Models.Expenses import Expenses
    from Server.Models.Inventory import Inventory
    from Server.Models.Shopstock import ShopStock
    from Server.Models.Paymnetmethods import SalesPaymentMethods
    from Server.Models.SoldItems import SoldItem
    from Server.Models.Transfer import Transfer
    from Server.Models.LiveStock import LiveStock
    from Server.Models.ShopTransfers import ShopTransfer
    from Server.Models.SystemStockTransfer import SystemStockTransfer
    from Server.Models.ChartOfAccounts import ChartOfAccounts
    from Server.Models.BankAccounts import BankAccount, BankingTransaction
    from Server.Models.SalesDepartment import SalesDepartment
    from Server.Models.Supplier import Suppliers, SupplierHistory
    from Server.Models.InventoryV2 import InventoryV2
    from Server.Models.ShopstockV2 import ShopStockV2
    from Server.Models.ExpenseCategory import ExpenseCategory
    from Server.Models.StockReport import StockReport
    from Server.Models.Permission import Permission
    from Server.Models.TaskManager import TaskManager, TaskComment, TaskEvaluation


# ---------- Views Import ----------
def initialize_views(app):
    from Server.Views import api_endpoint
    app.register_blueprint(api_endpoint)


# ---------- SasaPay Service ----------
import requests
import time

class SasaPayService:
    def __init__(self, app):
        self.app = app
        self.base_url = app.config.get("SASAPAY_BASE_URL")
        self.client_id = app.config.get("SASAPAY_CLIENT_ID")
        self.client_secret = app.config.get("SASAPAY_CLIENT_SECRET")
        self.token_expiry = 0
        
        # Log configuration status
        if not self.base_url or not self.client_id or not self.client_secret:
            print("⚠️ SasaPay service initialized with missing configuration")
            print(f"  Base URL: {self.base_url}")
            print(f"  Client ID: {'Set' if self.client_id else 'Missing'}")
            print(f"  Client Secret: {'Set' if self.client_secret else 'Missing'}")

    def get_token(self):
        # reuse token if not expired
        if self.app.sasapay_token and time.time() < self.token_expiry:
            return self.app.sasapay_token

        if not self.base_url or not self.client_id or not self.client_secret:
            print("❌ Cannot get token: Missing SasaPay configuration")
            return None

        url = f"{self.base_url}/auth/token"

        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }

        try:
            response = requests.post(url, json=payload, timeout=30)
            data = response.json()
            token = data.get("access_token")

            # store token + expiry (assume 1 hour if not provided)
            self.app.sasapay_token = token
            self.token_expiry = time.time() + 3500

            return token
        except Exception as e:
            print(f"❌ Error getting SasaPay token: {str(e)}")
            return None

    def request_payment(self, amount, phone, reference):
        token = self.get_token()
        if not token:
            return {"error": "Failed to get access token"}

        url = f"{self.base_url}/payments/request"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        payload = {
            "amount": amount,
            "phone_number": phone,
            "account_reference": reference,
            "transaction_desc": "Payment"
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            return response.json()
        except Exception as e:
            return {"error": str(e)}

    def check_status(self, transaction_id):
        token = self.get_token()
        if not token:
            return {"error": "Failed to get access token"}

        url = f"{self.base_url}/transactions/{transaction_id}"

        headers = {
            "Authorization": f"Bearer {token}"
        }

        try:
            response = requests.get(url, headers=headers, timeout=30)
            return response.json()
        except Exception as e:
            return {"error": str(e)}


# ---------- App Factory ----------
def create_app(config_name):
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # CORS
    CORS(app, origins=[
        "https://beta.kulima.co.ke",
        "http://localhost:3000",
        "http://127.0.0.1:3000"
    ])

    # Load config from config object
    app.config.from_object(config_name)

    # Database
    app.config["SQLALCHEMY_DATABASE_URI"] = 'mysql+pymysql://root:@localhost/Diraja'
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # JWT
    app.config['JWT_SECRET_KEY'] = os.getenv("JWT_SECRET_KEY", "Soweto@2024")
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = int(
        os.getenv('JWT_ACCESS_TOKEN_EXPIRES', 2592000)
    )

    # Mail
    app.config['MAIL_SERVER'] = 'mail.kulima.co.ke'
    app.config['MAIL_PORT'] = 465
    app.config['MAIL_USERNAME'] = 'kukuzetureports@kulima.co.ke'
    app.config['MAIL_PASSWORD'] = os.getenv("MAIL_PASSWORD")
    app.config['MAIL_USE_SSL'] = True
    app.config['MAIL_USE_TLS'] = False
    app.config['MAIL_DEFAULT_SENDER'] = 'kukuzetureports@kulima.co.ke'

    # VAPID
    app.config['VAPID_PUBLIC_KEY'] = os.getenv("VAPID_PUBLIC_KEY")
    app.config['VAPID_PRIVATE_KEY'] = os.getenv("VAPID_PRIVATE_KEY")
    app.config['VAPID_EMAIL'] = os.getenv("VAPID_EMAIL")

    # -------------------------------
    # SasaPay Config - Now loaded from config object
    # Note: These values are already set by the config class
    # -------------------------------
    # The config object already has these attributes from the Config class
    # We just need to ensure they're accessible
    if not app.config.get("SASAPAY_BASE_URL"):
        print("⚠️ Warning: SASAPAY_BASE_URL not configured")
    if not app.config.get("SASAPAY_CLIENT_ID"):
        print("⚠️ Warning: SASAPAY_CLIENT_ID not configured")
    if not app.config.get("SASAPAY_CLIENT_SECRET"):
        print("⚠️ Warning: SASAPAY_CLIENT_SECRET not configured")
    
    # Print SasaPay configuration status
    print("\n" + "="*50)
    print("SASAPAY CONFIGURATION STATUS")
    print("="*50)
    print(f"Environment: {os.getenv('SASAPAY_ENVIRONMENT', 'sandbox')}")
    print(f"Base URL: {app.config.get('SASAPAY_BASE_URL', 'NOT SET')}")
    print(f"Merchant Code: {app.config.get('SASAPAY_MERCHANT_CODE', 'NOT SET')}")
    print(f"Client ID: {'✓ SET' if app.config.get('SASAPAY_CLIENT_ID') else '✗ MISSING'}")
    print(f"Client Secret: {'✓ SET' if app.config.get('SASAPAY_CLIENT_SECRET') else '✗ MISSING'}")
    print(f"Callback URL: {app.config.get('SASAPAY_CALLBACK_URL', 'NOT SET')}")
    print(f"Use Mock: {app.config.get('SASAPAY_USE_MOCK', False)}")
    print("="*50 + "\n")
    
    app.sasapay_token = None

    # Init extensions
    db.init_app(app)
    Migrate(app, db)
    jwt.init_app(app)
    mail.init_app(app)

    # Init socket
    socketio.init_app(app, cors_allowed_origins='*')

    # -------------------------------
    # Initialize models + schema
    # -------------------------------
    with app.app_context():
        initialize_models()
        try:
            from schema_generator import write_schema_file
            write_schema_file()
        except ImportError:
            print("⚠️ schema_generator not found, skipping schema generation")

    # -------------------------------
    # OpenAI Setup
    # -------------------------------
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set.")

    client = OpenAI(api_key=api_key)
    app.llm_client = client

    app.llm_system_prompt = (
        "Use only the tables provided. "
        "Use relationships when joining tables. "
        "Do not guess column names. "
        "Return only valid MySQL SQL queries."
    )

    app.chat_history = []

    # -------------------------------
    # Attach SasaPay Service
    # -------------------------------
    # Only initialize if configuration exists
    if app.config.get("SASAPAY_BASE_URL") and app.config.get("SASAPAY_CLIENT_ID"):
        app.sasapay = SasaPayService(app)
    else:
        print("⚠️ SasaPay service not initialized due to missing configuration")
        app.sasapay = None

    # -------------------------------
    # Register Views
    # -------------------------------
    initialize_views(app)

    return app, socketio


# -------------------------------
# SQL Generator Helper
# -------------------------------
def generate_sql(app, user_prompt):
    response = app.llm_client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": app.llm_system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        max_completion_tokens=1000
    )

    return response.choices[0].message.content.strip()