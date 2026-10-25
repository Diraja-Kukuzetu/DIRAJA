import os


class Config():
    CSRF_ENABLED = True

    # ── Upload storage ────────────────────────────────────────────
    # Physical folder on disk where uploaded files are written.
    # Locally this is inside the project; on the VPS it's
    # /var/www/dirauploads (served directly by Apache).
    @property
    def UPLOAD_FOLDER(self):
        return os.getenv("UPLOAD_FOLDER", "/var/www/dirauploads")

    @property
    def CLOSING_IMAGES_FOLDER(self):
        return os.getenv(
            "CLOSING_IMAGES_FOLDER",
            os.path.join(self.UPLOAD_FOLDER, "closing_stock_images"),
        )

    # Public base URL where /dirauploads/ is served.
    # On the VPS this is your Apache-served domain.
    @property
    def UPLOADS_BASE_URL(self):
        return os.getenv("UPLOADS_BASE_URL", "https://server.kukuzetu.co.ke")

    # URL path prefix that Apache/Flask maps to UPLOAD_FOLDER.
    # Kept separate so you can change it in one place.
    @property
    def UPLOADS_URL_PREFIX(self):
        return os.getenv("UPLOADS_URL_PREFIX", "dirauploads")

    # Max upload size in bytes (Flask enforces this automatically).
    @property
    def MAX_CONTENT_LENGTH(self):
        return int(os.getenv("MAX_CONTENT_LENGTH", 10 * 1024 * 1024))  # 10 MB

    # ── SasaPay (unchanged) ───────────────────────────────────────
    @property
    def SASAPAY_ENVIRONMENT(self):
        return os.getenv("SASAPAY_ENVIRONMENT", "sandbox")

    @property
    def SASAPAY_CLIENT_ID(self):
        if self.SASAPAY_ENVIRONMENT == "production":
            return os.getenv("SASAPAY_PRODUCTION_CLIENT_ID")
        return os.getenv("SASAPAY_SANDBOX_CLIENT_ID")

    @property
    def SASAPAY_CLIENT_SECRET(self):
        if self.SASAPAY_ENVIRONMENT == "production":
            return os.getenv("SASAPAY_PRODUCTION_CLIENT_SECRET")
        return os.getenv("SASAPAY_SANDBOX_CLIENT_SECRET")

    @property
    def SASAPAY_BASE_URL(self):
        if self.SASAPAY_ENVIRONMENT == "production":
            return os.getenv("SASAPAY_PRODUCTION_BASE_URL")
        return os.getenv("SASAPAY_SANDBOX_BASE_URL")

    @property
    def SASAPAY_MERCHANT_CODE(self):
        if self.SASAPAY_ENVIRONMENT == "production":
            return os.getenv("SASAPAY_PRODUCTION_MERCHANT_CODE")
        return os.getenv("SASAPAY_SANDBOX_MERCHANT_CODE")

    @property
    def SASAPAY_CALLBACK_URL(self):
        if self.SASAPAY_ENVIRONMENT == "production":
            return os.getenv("SASAPAY_PRODUCTION_CALLBACK_URL")
        return os.getenv("SASAPAY_SANDBOX_CALLBACK_URL")

    @property
    def SASAPAY_USE_MOCK(self):
        return os.getenv("SASAPAY_USE_MOCK", "False").lower() == "true"


class Development(Config):
    """Local dev: store uploads inside the project so you don't need /var/www."""
    def __init__(self):
        self.DEBUG = True
        self.TESTING = True

    @property
    def UPLOAD_FOLDER(self):
        # Local project folder — sits next to the app
        return os.getenv(
            "UPLOAD_FOLDER",
            os.path.abspath(os.path.join(os.path.dirname(__file__), "dirauploads")),
        )

    @property
    def UPLOADS_BASE_URL(self):
        # Local Flask server base — used to build URLs you can click during dev
        return os.getenv("UPLOADS_BASE_URL", "http://127.0.0.1:8000")


class Production(Config):
    """Production: /var/www/dirauploads served directly by Apache."""
    def __init__(self):
        self.DEBUG = False
        self.TESTING = False

    @property
    def UPLOAD_FOLDER(self):
        return os.getenv("UPLOAD_FOLDER", "/var/www/dirauploads")

    @property
    def UPLOADS_BASE_URL(self):
        return os.getenv("UPLOADS_BASE_URL", "https://server.kukuzetu.co.ke")


class Testing(Config):
    def __init__(self):
        self.DEBUG = True
        self.TESTING = True

    @property
    def UPLOAD_FOLDER(self):
        return os.getenv(
            "UPLOAD_FOLDER",
            os.path.abspath(os.path.join(os.path.dirname(__file__), "dirauploads_test")),
        )


# Create config instances
app_config = {
    "development": Development(),
    "testing": Testing(),
    "production": Production(),
}