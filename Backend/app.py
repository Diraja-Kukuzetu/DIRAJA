import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from flask_mail import Mail


app = Flask(__name__)
CORS(app)
db = SQLAlchemy()
jwt = JWTManager()

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = '465'
app.config['MAIL_USERNAME'] = 'dirajadevelopment@gmail.com'
app.config['MAIL_PASSWORD'] = 'sazf zull wwva ikjd'
app.config['MAIL_USE_SSL'] = True
app.config['MAIL_USE_TLS'] = False
app.config['MAIL_DEFAULT_SENDER'] = 'dirajadevelopment@gmail.com'
mail = Mail(app)


def initialize_models():
    from Server.Models.Users import Users
    
    from Server.Models.Shops import Shops
    from Server.Models.Sales import Sales
    from Server.Models.Bank import Bank
    from Server.Models.Customers import Customers
    from Server.Models.Employees import Employees
    from Server.Models.EmployeeLoan import  EmployeeLoan
    from Server.Models.Stock import Stock
    from Server.Models.Expenses import Expenses 
    from Server.Models.Inventory import Inventory
    from Server.Models.Shopstock import ShopStock
    from Server.Models.Paymnetmethods import SalesPaymentMethods
    # from Server.Models.Distribution import Distribution
    from Server.Models.Transfer import Transfer
    from Server.Models.LiveStock import LiveStock
    from Server.Models.ShopTransfers import ShopTransfer
    from Server.Models.SystemStockTransfer import  SystemStockTransfer
    
    # from Server.Models.Purchases import Purchases

def initialize_views():
    from  Server.Views import api_endpoint
    app.register_blueprint(api_endpoint)


def create_app(config_name):
    app.config.from_object(config_name)
    # app.config["SQLALCHEMY_DATABASE_URI"] = 'sqlite:///app.db'
    app.config["SQLALCHEMY_DATABASE_URI"] = 'mysql+pymysql://root:@localhost/Diraja'



    # MySQL database configuration      
    
#     app.config["SQLALCHEMY_DATABASE_URI"] = 'mysql+pymysql://kulimaco_dirajaapp:Diraja2024@148.251.133.221/kulimaco_dirajaapp'

#     app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
#     'pool_recycle': 280,  # Recycle connections after 280 seconds of inactivity
#     'pool_timeout': 30,   # Wait 30 seconds for a connection from the pool
#     'pool_pre_ping': True  # Check connection health before using it
# }   


    
    #JWT SETUP KEY
    app.config['JWT_SECRET_KEY'] = "Soweto@2024"
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = int(os.getenv('JWT_ACCESS_TOKEN_EXPIRES', 2592000))
    
    #Initialize DB with app
    db.init_app(app)
    migrate = Migrate(app, db)
    jwt.init_app(app)
   
    # Create database schemas
    with app.app_context():
        initialize_models()

    initialize_views()


        


    return app