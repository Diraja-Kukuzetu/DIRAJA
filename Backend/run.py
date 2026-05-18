from app import create_app
from config import app_config
import os
from dotenv import load_dotenv

# Force reload .env file
load_dotenv(override=True)

# Check SasaPay environment on startup - read directly from environment
sasapay_env = os.getenv("SASAPAY_ENVIRONMENT", "sandbox")
print(f"\n{'='*50}")
print(f"🚀 Starting with SasaPay {sasapay_env.upper()} environment")
print(f"{'='*50}")

# Determine which config to use based on environment
# You can also use the environment to determine config_name
if sasapay_env == "production":
    config_name = "production"
    print(f"📦 Using PRODUCTION configuration")
else:
    config_name = "development"  # Use development for sandbox
    print(f"🧪 Using DEVELOPMENT/SANDBOX configuration")

# Print SasaPay configuration from environment
print(f"\n📋 SasaPay Configuration:")
print(f"   Environment: {sasapay_env}")
print(f"   Config Name: {config_name}")

if sasapay_env == "production":
    print(f"   Base URL: {os.getenv('SASAPAY_PRODUCTION_BASE_URL', 'NOT SET')}")
    print(f"   Merchant Code: {os.getenv('SASAPAY_PRODUCTION_MERCHANT_CODE', 'NOT SET')}")
    print(f"   Client ID: {os.getenv('SASAPAY_PRODUCTION_CLIENT_ID', 'NOT SET')[:20]}..." if os.getenv('SASAPAY_PRODUCTION_CLIENT_ID') else "   Client ID: NOT SET")
else:
    print(f"   Base URL: {os.getenv('SASAPAY_SANDBOX_BASE_URL', 'NOT SET')}")
    print(f"   Merchant Code: {os.getenv('SASAPAY_SANDBOX_MERCHANT_CODE', 'NOT SET')}")
    print(f"   Client ID: {os.getenv('SASAPAY_SANDBOX_CLIENT_ID', 'NOT SET')[:20]}..." if os.getenv('SASAPAY_SANDBOX_CLIENT_ID') else "   Client ID: NOT SET")

print(f"{'='*50}\n")

# Create app with the appropriate config
app, socketio = create_app(app_config[config_name])

if __name__ == '__main__':
    socketio.run(
        app, 
        host='0.0.0.0', 
        port=5000,
        debug=(config_name != "production"),
        allow_unsafe_werkzeug=(config_name != "production")
    )