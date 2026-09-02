# stamp_all_tenants.py
from flask import Flask
from flask_migrate import Migrate, stamp
from app import db
from tenant import TENANT_DATABASES

for tenant, uri in TENANT_DATABASES.items():
    print(f"Stamping {tenant}...")
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = uri
    db.init_app(app)
    Migrate(app, db, directory="migrations")
    with app.app_context():
        stamp()  # stamps to head by default
    print(f"✅ {tenant} stamped")