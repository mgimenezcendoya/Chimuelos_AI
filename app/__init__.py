from flask import Flask
from .routes.webhook import webhook_bp

def create_app():
    app = Flask(__name__)
    
    # Registrar blueprints
    app.register_blueprint(webhook_bp)
    
    return app 