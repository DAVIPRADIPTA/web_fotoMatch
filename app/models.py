from app.extensions import db
from datetime import datetime
from flask_login import UserMixin
import json

class User(db.Model, UserMixin):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    # Kolom ini diubah namanya untuk menyimpan ID unik dari Supabase (atau provider lain nantinya)
    provider_uid = db.Column(db.String(128), unique=True, nullable=True) 
    
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    
    # Password nullable=True karena jika login pakai OTP Supabase, kita tidak butuh password
    password = db.Column(db.String(255), nullable=True) 
    
    # 'manual' untuk form password biasa, 'supabase' untuk OTP/Google
    auth_provider = db.Column(db.String(50), default='manual') 
    
    role = db.Column(db.Enum('admin', 'photographer', 'buyer'), default='buyer')
    face_embedding_user = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Studio(db.Model):
    __tablename__ = 'studios'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'))
    studio_name = db.Column(db.String(255), nullable=False)
    province_id = db.Column(db.Integer, nullable=True) # Untuk RajaOngkir
    city_id = db.Column(db.Integer, nullable=True)     # Untuk RajaOngkir
    address_detail = db.Column(db.Text, nullable=True)
    bank_name = db.Column(db.String(100), nullable=True)
    bank_account_number = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Event(db.Model):
    __tablename__ = 'events'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(100))
    event_date = db.Column(db.Date, nullable=False)
    location_name = db.Column(db.String(255))
    # Tidak ada link drive di sini, karena Event hanya sebagai 'Wadah'
    albums = db.relationship('EventAlbum', backref='event', lazy=True)

class EventAlbum(db.Model):
    """Satu Event bisa punya banyak Album dari banyak Fotografer"""
    __tablename__ = 'event_albums'
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id', ondelete='CASCADE'))
    photographer_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'))
    
    # Detail teknis & harga per album (karena tiap fotografer mungkin pasang harga beda)
    drive_folder_link = db.Column(db.String(255), nullable=False)
    price_digital = db.Column(db.Integer, default=15000)
    allow_physical_print = db.Column(db.Boolean, default=False)
    
    status_ai = db.Column(db.Enum('idle', 'processing', 'completed', 'error'), default='idle')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Photo(db.Model):
    __tablename__ = 'photos'
    id = db.Column(db.Integer, primary_key=True)
    
    # Relasi diubah ke EventAlbum agar kita tahu siapa fotografer yang mengunggahnya
    album_id = db.Column(db.Integer, db.ForeignKey('event_albums.id', ondelete='CASCADE'), nullable=False)
    
    # Data spesifik dari Google Drive
    gdrive_file_id = db.Column(db.String(100), nullable=False)
    file_name = db.Column(db.String(255))
    
    # Path dari struktur aslimu kita gunakan untuk menyimpan URL dari Drive
    original_path = db.Column(db.String(255), nullable=True) # Menyimpan webContentLink (URL Download)
    preview_path = db.Column(db.Text, nullable=True)         # Menyimpan thumbnailLink (URL Preview)
    
    price_digital = db.Column(db.Integer, nullable=False, default=0)
    price_physical = db.Column(db.Integer, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relasi ke FaceEmbedding agar saat Photo dihapus, data wajahnya ikut terhapus
    faces = db.relationship('FaceEmbedding', backref='photo', lazy=True, cascade="all, delete-orphan")

class FaceEmbedding(db.Model):
    __tablename__ = 'face_embeddings'
    id = db.Column(db.Integer, primary_key=True)
    photo_id = db.Column(db.Integer, db.ForeignKey('photos.id', ondelete='CASCADE'))
    
    # Sesuai dengan namamu, menyimpan vektor 128 dimensi
    embedding_vector = db.Column(db.Text, nullable=False) 
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_embedding_array(self):
        """Fungsi bantu untuk mengubah teks JSON kembali menjadi Array Python"""
        return json.loads(self.embedding_vector)

class FaceMatch(db.Model):
    __tablename__ = 'face_matches'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'))
    photo_id = db.Column(db.Integer, db.ForeignKey('photos.id', ondelete='CASCADE'))
    match_score = db.Column(db.Float, nullable=False)
    is_confirmed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Order(db.Model):
    __tablename__ = 'orders'
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(100), unique=True, nullable=False)
    buyer_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'))
    photographer_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'))
    midtrans_transaction_id = db.Column(db.String(255), nullable=True)
    total_price = db.Column(db.Integer, nullable=False)
    payment_status = db.Column(db.Enum('unpaid', 'paid', 'expired', 'failed'), default='unpaid')
    payment_type = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class OrderItem(db.Model):
    __tablename__ = 'order_items'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id', ondelete='CASCADE'))
    photo_id = db.Column(db.Integer, db.ForeignKey('photos.id', ondelete='CASCADE'))
    purchase_type = db.Column(db.Enum('digital', 'physical'), nullable=False)
    subtotal = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Shipping(db.Model):
    __tablename__ = 'shippings'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id', ondelete='CASCADE'))
    courier_name = db.Column(db.String(100), nullable=True)
    shipping_cost = db.Column(db.Integer, default=0)
    tracking_number = db.Column(db.String(255), nullable=True)
    destination_address = db.Column(db.Text, nullable=False)
    shipping_status = db.Column(db.Enum('pending', 'processing', 'shipped', 'delivered'), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Wallet(db.Model):
    __tablename__ = 'wallets'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'))
    balance = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Withdrawal(db.Model):
    __tablename__ = 'withdrawals'
    id = db.Column(db.Integer, primary_key=True)
    wallet_id = db.Column(db.Integer, db.ForeignKey('wallets.id', ondelete='CASCADE'))
    amount = db.Column(db.Integer, nullable=False)
    status = db.Column(db.Enum('pending', 'completed', 'rejected'), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)



class StudioService(db.Model):
    """Tempat fotografer input daftar ukuran & bingkai yang mereka punya"""
    __tablename__ = 'studio_services'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    service_name = db.Column(db.String(100)) # Contoh: "Cetak 4R", "Bingkai Minimalis Hitam"
    service_type = db.Column(db.Enum('print', 'frame'))
    additional_price = db.Column(db.Integer, default=0) # Harga tambahan