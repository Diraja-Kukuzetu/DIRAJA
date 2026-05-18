import os

class Config():
    CSRF_ENABLED = True
    
    # Direct environment variable access without caching
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
    def __init__(self):
        self.DEBUG = True
        self.TESTING = True

class Production(Config):
    def __init__(self):
        self.DEBUG = False
        self.TESTING = False

class Testing(Config):
    def __init__(self):
        self.DEBUG = True
        self.TESTING = True

# Create config instances
app_config = {
    "development": Development(),
    "testing": Testing(),
    "production": Production()
}