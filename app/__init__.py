from flask import Flask
from config import Config
from app.extensions import db, migrate, jwt, login_manager
import firebase_admin
from firebase_admin import credentials
import os

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Init Extensions
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)

    login_manager.init_app(app)
    login_manager.login_view = 'web_auth.login'

    @login_manager.user_loader
    def load_user(user_id):
        from app.models import User
        return User.query.get(int(user_id))

    # Inisialisasi Firebase Admin SDK
    # Pastikan kamu punya file JSON dari Firebase Console nantinya
    firebase_key_path = os.path.join(os.path.dirname(__file__), '..', 'firebase_credentials.json')
    if os.path.exists(firebase_key_path) and not firebase_admin._apps:
        cred = credentials.Certificate(firebase_key_path)
        firebase_admin.initialize_app(cred)

    # Nanti kita daftarkan Blueprint di sini
    from app import models

    from app.api.auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/api/auth')

    from app.web.auth import web_auth_bp
    from app.web.views import web_bp

    app.register_blueprint(web_auth_bp)
    app.register_blueprint(web_bp)

    return app