# migrate_all_tenants.py
import sys
from flask import Flask
from flask_migrate import Migrate, upgrade
from app import db  # reuse the same db instance your models are registered on
from tenant import TENANT_DATABASES


def build_migration_app(uri: str) -> Flask:
    """A lightweight Flask app — just enough for Alembic to run against
    a specific tenant DB. No mail, JWT, OpenAI, SasaPay, sockets, etc."""
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = uri
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)          # engine is bound HERE, to the correct uri, every time
    Migrate(app, db, directory="migrations")  # point at your existing migrations folder

    return app


def migrate_all():
    for tenant, uri in TENANT_DATABASES.items():
        print(f"\n{'='*50}")
        print(f"Migrating tenant: {tenant}")
        print(f"URI: {uri.split('@')[-1]}")  # log host/db only, not credentials
        print(f"{'='*50}")

        app = build_migration_app(uri)

        with app.app_context():
            try:
                upgrade()
                print(f"✅ {tenant} migrated successfully")
            except Exception as e:
                print(f"❌ {tenant} FAILED: {e}")
                sys.exit(1)  # stop immediately — don't let tenants drift further apart


if __name__ == "__main__":
    migrate_all()