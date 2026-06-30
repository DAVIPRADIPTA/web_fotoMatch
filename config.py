import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv('SECRET_KEY')
    # JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY')

    SUPABASE_JWT_SECRET = os.getenv('SUPABASE_JWT_SECRET')
    FIREBASE_CONFIG = {
        'apiKey': os.getenv('FIREBASE_API_KEY'),
        'authDomain': os.getenv('FIREBASE_AUTH_DOMAIN'),
        'projectId': os.getenv('FIREBASE_PROJECT_ID'),
    }
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_ANON_KEY = os.getenv('SUPABASE_ANON_KEY')
    KOMERCE_SHIPPING_KEY = os.getenv('KOMERCE_SHIPPING_KEY')
    BITESHIP_API_KEY = os.getenv('BITESHIP_API_KEY')
    MIDTRANS_SERVER_KEY = os.getenv('MIDTRANS_SERVER_KEY')