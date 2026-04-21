import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from dotenv import load_dotenv
from flask_mail import Mail
from openai import OpenAI  # ✅ NEW

# Removed: google.generativeai

load_dotenv()

# ---------- Extensions ----------
db = SQLAlchemy()
jwt = JWTManager()
mail = Mail()

# ---------- Models Import ----------
def initialize_models():
    """Import all models so SQLAlchemy can discover them."""
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


# ---------- Views Import ----------
def initialize_views(app):
    """Register Flask blueprints/resources."""
    from Server.Views import api_endpoint
    app.register_blueprint(api_endpoint)


def create_app(config_name):
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # CORS
    CORS(app, origins=[
        "https://beta.kulima.co.ke",
        "http://localhost:3000",
        "http://127.0.0.1:3000"
    ])

    # Load config
    app.config.from_object(config_name)

    # Database config
    app.config["SQLALCHEMY_DATABASE_URI"] = "mysql+pymysql://root:MyNewPass@localhost/Diraja"

    # JWT config (⚠️ move to .env in production)
    app.config['JWT_SECRET_KEY'] = os.getenv("JWT_SECRET_KEY", "Soweto@2024")
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = int(
        os.getenv('JWT_ACCESS_TOKEN_EXPIRES', 2592000)
    )

    # Mail config (⚠️ move password to .env)
    app.config['MAIL_SERVER'] = 'mail.kulima.co.ke'
    app.config['MAIL_PORT'] = 465
    app.config['MAIL_USERNAME'] = 'kukuzetureports@kulima.co.ke'
    app.config['MAIL_PASSWORD'] = os.getenv("MAIL_PASSWORD")
    app.config['MAIL_USE_SSL'] = True
    app.config['MAIL_USE_TLS'] = False
    app.config['MAIL_DEFAULT_SENDER'] = 'kukuzetureports@kulima.co.ke'

    # VAPID keys
    app.config['VAPID_PUBLIC_KEY'] = os.getenv("VAPID_PUBLIC_KEY")
    app.config['VAPID_PRIVATE_KEY'] = os.getenv("VAPID_PRIVATE_KEY")
    app.config['VAPID_EMAIL'] = os.getenv("VAPID_EMAIL")

    # Init extensions
    db.init_app(app)
    Migrate(app, db)
    jwt.init_app(app)
    mail.init_app(app)

    # -------------------------------
    # Initialize models & generate schema
    # -------------------------------
    with app.app_context():
        initialize_models()
        from schema_generator import write_schema_file
        write_schema_file()

    # -------------------------------
    # Configure ChatGPT (OpenAI)
    # -------------------------------
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set. Check your .env file.")

    client = OpenAI(api_key=api_key)
    app.llm_client = client

    # System prompt (same logic you had in Gemini)
    app.llm_system_prompt = (
        "Use only the tables provided. "
        "Use relationships when joining tables. "
        "Do not guess column names. "
        "Return only valid MySQL SQL queries."
    )

    # Chat history (optional)
    app.chat_history = []

    # -------------------------------
    # Register views/routes
    # -------------------------------
    initialize_views(app)

    return app


# -------------------------------
# OPTIONAL HELPER FUNCTION
# -------------------------------
def generate_sql(app, user_prompt):
    """
    Generate SQL query using ChatGPT
    """
    response = app.llm_client.chat.completions.create(
        model="gpt-5-mini",  # you can upgrade to gpt-5.3
        messages=[
            {"role": "system", "content": app.llm_system_prompt},
            {"role": "user", "content": user_prompt}
        ],
      
        max_completion_tokens=1000
    )

    return response.choices[0].message.content.strip()