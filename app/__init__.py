from flask import Flask
from config import Config
from app.extensions import db, migrate, jwt, login_manager
import os

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Init Extensions
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)

    # Init Login Manager (Sisi Web)
    login_manager.init_app(app)
    login_manager.login_view = 'web_auth.login'

    @login_manager.user_loader
    def load_user(user_id):
        from app.models import User
        return User.query.get(int(user_id))

    # [HAPUS] Blok inisialisasi Firebase Admin SDK dihapus seluruhnya dari sini

    # Pendaftaran Model
    from app import models

    # =====================================
    # PENDAFTARAN BLUEPRINT
    # =====================================
    
    # 1. API Mobile (Untuk Pelanggan & Fotografer di HP)
    from app.api.auth import api_auth_bp
    app.register_blueprint(api_auth_bp, url_prefix='/api/v1/auth')

    # 2. Web Fotografer / Admin
    from app.web.auth import web_auth_bp
    app.register_blueprint(web_auth_bp)
    
    from app.web.views import web_bp
    app.register_blueprint(web_bp)

    return app