from app import create_app
from config import app_config
import os

# Check SasaPay environment on startup
sasapay_env = os.getenv("SASAPAY_ENVIRONMENT", "sandbox")
print(f"🚀 Starting with SasaPay {sasapay_env.upper()} environment")

# Pass the configuration name to create_app
config_name = "production"  # or "development"
app, socketio = create_app(app_config[config_name])

if __name__ == '__main__':
    socketio.run(
        app, 
        host='0.0.0.0', 
        port=5000,
        debug=(config_name != "production"),
        allow_unsafe_werkzeug=(config_name != "production")
    )