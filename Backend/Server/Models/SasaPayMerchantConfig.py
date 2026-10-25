# Server/Models/SasaPayMerchantConfig.py

from app import db
import os
from cryptography.fernet import Fernet


# ─────────────────────────────────────────────────────────────────────
#  Encryption helpers (Fernet = reversible AES)
# ─────────────────────────────────────────────────────────────────────

def _get_fernet():
    """Build a Fernet instance from the app's encryption key."""
    key = os.getenv("SASAPAY_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError(
            "SASAPAY_ENCRYPTION_KEY is not set. Generate one with:\n"
            "  python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"\n"
            "Then add it to your .env file."
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def _encrypt(value):
    """Reversible encryption — used for API credentials sent to SasaPay."""
    if not value:
        return None
    return _get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def _decrypt(token):
    """Reverse of _encrypt()."""
    if not token:
        return None
    return _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")


class SasaPayMerchantConfig(db.Model):
    __tablename__ = "sasapay_merchant_configs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    merchant_code = db.Column(
        db.String(20), nullable=False, unique=True, index=True
    )
    merchant_name = db.Column(db.String(120), nullable=True)
    location = db.Column(db.String(120), nullable=True)
    merchant_type = db.Column(db.String(30), default="shop")

    # Encrypted credentials (reversible) — used to call SasaPay
    client_id_encrypted = db.Column(db.Text, nullable=True)
    client_secret_encrypted = db.Column(db.Text, nullable=True)

    # Status + audit
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    # Relationship (same pattern as Stock → Shops)
    shop_id = db.Column(db.Integer, db.ForeignKey("shops.shops_id"))
    shops = db.relationship("Shops", backref="sasapay_configs", lazy=True)

    # ─────────────────────────────────────────────────────────────────
    #  Credential helpers
    # ─────────────────────────────────────────────────────────────────
    def set_credentials(self, client_id, client_secret):
        """Encrypt and store both credentials."""
        self.client_id_encrypted = _encrypt(client_id)
        self.client_secret_encrypted = _encrypt(client_secret)

    def get_client_id(self):
        """Return the plaintext client_id for API auth."""
        return _decrypt(self.client_id_encrypted)

    def get_client_secret(self):
        """Return the plaintext client_secret for API auth."""
        return _decrypt(self.client_secret_encrypted)

    # ─────────────────────────────────────────────────────────────────
    #  Lookup helpers
    # ─────────────────────────────────────────────────────────────────
    @classmethod
    def get_for_shop(cls, shop_id):
        """Return the active SasaPay config for a given shop."""
        return cls.query.filter_by(shop_id=shop_id, is_active=True).first()

    @classmethod
    def get_by_merchant_code(cls, merchant_code):
        """Return the active SasaPay config for a merchant code."""
        return cls.query.filter_by(
            merchant_code=str(merchant_code), is_active=True
        ).first()

    @classmethod
    def list_active(cls):
        """Return all active merchant configs, ordered by id."""
        return (
            cls.query.filter_by(is_active=True)
            .order_by(cls.id.asc())
            .all()
        )

    # ─────────────────────────────────────────────────────────────────
    #  Serialization
    # ─────────────────────────────────────────────────────────────────
    def to_dict(self, include_secrets=False):
        data = {
            "id": self.id,
            "shop_id": self.shop_id,
            "merchant_code": self.merchant_code,
            "merchant_name": self.merchant_name,
            "location": self.location,
            "merchant_type": self.merchant_type,
            "is_active": self.is_active,
            "created_at": (
                self.created_at.isoformat() if self.created_at else None
            ),
        }
        if include_secrets:
            # Only reports whether credentials exist; never returns them.
            data["has_client_id"] = bool(self.client_id_encrypted)
            data["has_client_secret"] = bool(self.client_secret_encrypted)
        return data

    def __repr__(self):
        return (
            f"SasaPayMerchantConfig(id={self.id}, shop_id='{self.shop_id}', "
            f"merchant_code='{self.merchant_code}')"
        )