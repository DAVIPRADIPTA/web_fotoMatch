from flask import Flask
from config import Config
from app.extensions import db, migrate, jwt, login_manager
from flasgger import Swagger
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

    # ==========================================
    # TAMBAHKAN TEMPLATE SWAGGER INI
    # ==========================================
    swagger_template = {
        "swagger": "2.0",
        "info": {
            "title": "FotoMatch API",
            "description": "Dokumentasi API Terintegrasi",
            "version": "1.0.0"
        },
        "securityDefinitions": {
            "Bearer": {
                "type": "apiKey",
                "name": "Authorization",
                "in": "header",
                "description": "Masukkan token JWT dengan format: Bearer {token_milik_flask}"
            }
        }
    }
    
    # Masukkan template-nya ke dalam Swagger
    Swagger(app, template=swagger_template)

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
    from app.api.events import api_events_bp
    from app.api.studios  import api_studios_bp
    from app.api.orders import api_orders_bp
    from app.api.finance import api_finance_bp

    app.register_blueprint(api_auth_bp, url_prefix='/api/v1/auth')
    app.register_blueprint(api_events_bp, url_prefix='/api/v1/events')
    app.register_blueprint(api_studios_bp, url_prefix='/api/v1/studios')
    app.register_blueprint(api_orders_bp, url_prefix='/api/v1/orders')
    app.register_blueprint(api_finance_bp, url_prefix='/api/v1/creator')

    # 2. Web Fotografer / Admin
    from app.web.auth import web_auth_bp
    app.register_blueprint(web_auth_bp)
    
    from app.web.views import web_bp
    app.register_blueprint(web_bp)

    return app