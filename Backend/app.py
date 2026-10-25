# app.py file 2 

import os
from flask import Flask, g
from flask_sqlalchemy import SQLAlchemy
from flask_sqlalchemy.session import Session as FSASession
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from dotenv import load_dotenv
from flask_socketio import SocketIO
from flask_mail import Mail
from openai import OpenAI

# Load env
load_dotenv()

# Base directory for local asset folders
BASE_DIR = os.path.abspath(os.path.dirname(__file__))


# ---------- Tenant-aware Session ----------
class TenantAwareSession(FSASession):
    def get_bind(self, mapper=None, clause=None, **kwargs):
        engine = getattr(g, "tenant_engine", None)
        if engine is not None:
            return engine
        return super().get_bind(mapper=mapper, clause=clause, **kwargs)


# ---------- Extensions ----------
db = SQLAlchemy(session_options={"class_": TenantAwareSession})
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
    from Server.Models.Users import Users
    from Server.Models.TwoFactorAuth import TwoFactorAuth
    from Server.Models.SasaPayMerchantConfig import SasaPayMerchantConfig
    from Server.Models.Shops import Shops
    from Server.Models.Creditors import Creditors
    from Server.Models.Accounting.SalesLedger import SalesLedger
    from Server.Models.StockItems import StockItems


# ---------- Views Import ----------
def initialize_views(app):
    from Server.Views import api_endpoint
    app.register_blueprint(api_endpoint)


# ---------- App Factory ----------
def create_app(config_name):
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # CORS
    CORS(app, origins=[
        "https://beta.kulima.co.ke",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ])

    # Load config from config object FIRST
    app.config.from_object(config_name)

    # ── Upload storage (works locally and on VPS) ────────────────
    env = os.getenv("FLASK_ENV", "development")

    if env == "production":
        upload_root = os.getenv("UPLOAD_FOLDER", "/var/www/dirauploads")
        uploads_base = os.getenv(
            "UPLOADS_BASE_URL", "https://server.kukuzetu.co.ke"
        )
    else:
        upload_root = os.getenv(
            "UPLOAD_FOLDER", os.path.join(BASE_DIR, "dirauploads")
        )
        uploads_base = os.getenv("UPLOADS_BASE_URL", "http://127.0.0.1:8000")

    app.config["UPLOAD_FOLDER"] = upload_root
    app.config["CLOSING_IMAGES_FOLDER"] = os.path.join(
        upload_root, "closing_stock_images"
    )
    app.config["UPLOADS_BASE_URL"] = uploads_base
    app.config["UPLOADS_URL_PREFIX"] = os.getenv(
        "UPLOADS_URL_PREFIX", "dirauploads"
    )
    app.config["MAX_CONTENT_LENGTH"] = int(
        os.getenv("MAX_CONTENT_LENGTH", 10 * 1024 * 1024)
    )

    os.makedirs(app.config["CLOSING_IMAGES_FOLDER"], exist_ok=True)

    print("\n" + "=" * 50)
    print("UPLOAD STORAGE CONFIGURATION")
    print("=" * 50)
    print(f"Environment:            {env}")
    print(f"UPLOAD_FOLDER:          {app.config['UPLOAD_FOLDER']}")
    print(f"CLOSING_IMAGES_FOLDER:  {app.config['CLOSING_IMAGES_FOLDER']}")
    print(f"UPLOADS_BASE_URL:       {app.config['UPLOADS_BASE_URL']}")
    print(f"UPLOADS_URL_PREFIX:     {app.config['UPLOADS_URL_PREFIX']}")
    print(f"MAX_CONTENT_LENGTH:     {app.config['MAX_CONTENT_LENGTH']} bytes")
    print("=" * 50 + "\n")

    # ── Dev-only: serve uploaded files locally (Apache handles this in prod) ──
    if env != "production":
        from flask import send_from_directory

        @app.route(f"/{app.config['UPLOADS_URL_PREFIX']}/<path:filename>")
        def serve_uploads(filename):
            return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    # -------------------------------
    # Database
    # -------------------------------
    from tenant import TENANT_DATABASES

    app.config["SQLALCHEMY_DATABASE_URI"] = TENANT_DATABASES["diraja"]
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_BINDS"] = TENANT_DATABASES

    # JWT
    app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", "Soweto@2024")
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = int(
        os.getenv("JWT_ACCESS_TOKEN_EXPIRES", 2592000)
    )

    # Mail
    app.config["MAIL_SERVER"] = "mail.kukuzetu.co.ke"
    app.config["MAIL_PORT"] = 465
    app.config["MAIL_USERNAME"] = "no-reply@kukuzetu.co.ke"
    app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD")
    app.config["MAIL_USE_SSL"] = True
    app.config["MAIL_USE_TLS"] = False
    app.config["MAIL_DEFAULT_SENDER"] = "no-reply@kukuzetu.co.ke"

    # VAPID
    app.config["VAPID_PUBLIC_KEY"] = os.getenv("VAPID_PUBLIC_KEY")
    app.config["VAPID_PRIVATE_KEY"] = os.getenv("VAPID_PRIVATE_KEY")
    app.config["VAPID_EMAIL"] = os.getenv("VAPID_EMAIL")

    # Init extensions
    db.init_app(app)
    Migrate(app, db)
    jwt.init_app(app)
    mail.init_app(app)

    # Init socket
    socketio.init_app(app, cors_allowed_origins="*")

    # -------------------------------
    # Initialize models + schema
    # -------------------------------
    with app.app_context():
        initialize_models()
        try:
            from schema_generator import write_schema_file
            write_schema_file()
        except ImportError:
            print("schema_generator not found, skipping schema generation")

    # -------------------------------
    # SasaPay startup checks (DB-backed credentials)
    # -------------------------------
    # The encryption key is required for storing and reading merchant
    # credentials. Fail fast rather than silently breaking the first time
    # someone tries to save or read a merchant config.
    if not os.getenv("SASAPAY_ENCRYPTION_KEY"):
        raise RuntimeError(
            "SASAPAY_ENCRYPTION_KEY is not set. Generate one with:\n"
            "  python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"\n"
            "and add it to your .env file."
        )

    print("\n" + "=" * 50)
    print("SASAPAY CONFIGURATION STATUS")
    print("=" * 50)
    print(f"Environment:      {os.getenv('SASAPAY_ENVIRONMENT', 'sandbox')}")
    print("Encryption key:   ✓ SET")
    print(
        f"Callback URL:     "
        f"{os.getenv('SASAPAY_CALLBACK_URL', 'falls back to BASE_URL')}"
    )
    print(
        f"Sandbox Merchant: "
        f"{os.getenv('SASAPAY_SANDBOX_MERCHANT_CODE', '600980')}"
    )

    # Count configured merchants in the DB (safe — models already loaded)
    try:
        from Server.Models.SasaPayMerchantConfig import SasaPayMerchantConfig

        with app.app_context():
            active_count = SasaPayMerchantConfig.query.filter_by(
                is_active=True
            ).count()
            print(f"Merchants (DB):   {active_count} active")
    except Exception as e:
        print(f"Merchants (DB):   could not query — {e}")

    print("=" * 50 + "\n")

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
            {"role": "user", "content": user_prompt},
        ],
        max_completion_tokens=1000,
    )

    return response.choices[0].message.content.strip()