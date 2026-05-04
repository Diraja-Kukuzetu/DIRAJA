from app import create_app
from config import app_config

# Pass the configuration name to create_app
config_name = "production"
app, socketio = create_app(app_config)  # ← Note: returning both app and socketio

if __name__ == '__main__':
    # Use socketio.run instead of app.run for WebSocket support
    socketio.run(
        app, 
        host='0.0.0.0', 
        port=5000,
        debug=True,  # Set to False in production
        allow_unsafe_werkzeug=True  # For development only
    )