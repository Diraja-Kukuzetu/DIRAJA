import os

class Config():
    CSRF_ENABLED = True
    
    @property
    def SASAPAY_CLIENT_ID(self):
        if os.getenv("SASAPAY_ENVIRONMENT") == "production":
            return os.getenv("SASAPAY_PRODUCTION_CLIENT_ID")
        return os.getenv("SASAPAY_SANDBOX_CLIENT_ID")
    
    @property
    def SASAPAY_CLIENT_SECRET(self):
        if os.getenv("SASAPAY_ENVIRONMENT") == "production":
            return os.getenv("SASAPAY_PRODUCTION_CLIENT_SECRET")
        return os.getenv("SASAPAY_SANDBOX_CLIENT_SECRET")
    
    @property
    def SASAPAY_BASE_URL(self):
        if os.getenv("SASAPAY_ENVIRONMENT") == "production":
            return os.getenv("SASAPAY_PRODUCTION_BASE_URL")
        return os.getenv("SASAPAY_SANDBOX_BASE_URL")
    
    @property
    def SASAPAY_MERCHANT_CODE(self):
        if os.getenv("SASAPAY_ENVIRONMENT") == "production":
            return os.getenv("SASAPAY_PRODUCTION_MERCHANT_CODE")
        return os.getenv("SASAPAY_SANDBOX_MERCHANT_CODE")
    
    @property
    def SASAPAY_CALLBACK_URL(self):
        if os.getenv("SASAPAY_ENVIRONMENT") == "production":
            return os.getenv("SASAPAY_PRODUCTION_CALLBACK_URL")
        return os.getenv("SASAPAY_SANDBOX_CALLBACK_URL")

class Development(Config):
    DEBUG = True
    TESTING = True

class Production(Config):
    DEBUG = False
    TESTING = False

class Testing(Config):
    DEBUG = True
    TESTING = True

app_config = {
    "development": Development(),
    "testing": Testing(),
    "production": Production()
}