import json
import jwt  # Pastikan menginstal PyJWT (pip install PyJWT)
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
import urllib
from app.extensions import db
from app.models import User
from app.services.face_engine import face_engine
from app.services.matcher import start_face_matching

api_auth_bp = Blueprint('api_auth', __name__)

# ==========================================
# 1. LOGIN SUPABASE (OTP EMAIL & GOOGLE)
# ==========================================
@api_auth_bp.route('/login-supabase', methods=['POST'])
def login_supabase():
    supabase_token = request.form.get('access_token')
    role = request.form.get('role', 'buyer')
    
    if not supabase_token:
        return jsonify({"status": "error", "message": "Autentikasi gagal. Access Token Supabase tidak ditemukan."}), 400

    try:
        # ==========================================
        # 1. TANYA LANGSUNG KE SERVER SUPABASE
        # ==========================================
        # GANTI INI: Masukkan URL Project dan Anon Key milikmu
        SUPABASE_URL = "https://pwqzhkbtevlgecbnddil.supabase.co" 
        SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InB3cXpoa2J0ZXZsZ2VjYm5kZGlsIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODE2MDM2MzksImV4cCI6MjA5NzE3OTYzOX0.U3I5flv39XcELupehptCdWC_lav4Qz1TUlWPSKYAZqE"
        
        req = urllib.request.Request(f"{SUPABASE_URL}/auth/v1/user")
        
        # Dua Header Wajib Supabase!
        req.add_header("Authorization", f"Bearer {supabase_token}")
        req.add_header("apikey", SUPABASE_ANON_KEY) # <--- INI BARIS PENYELAMATNYA
        
        try:
            response = urllib.request.urlopen(req)
            user_data = json.loads(response.read())
        except Exception as e:
            print(f"[!] Auth Error: Server Supabase menolak token: {str(e)}")
            return jsonify({"status": "error", "message": "Sesi tidak valid atau telah kadaluwarsa. Silakan login ulang."}), 401

        # ==========================================
        # 2. EKSTRAK DATA RESMI DARI SUPABASE
        # ==========================================
        supabase_uid = user_data.get('id')
        email = user_data.get('email')
        
        # Ekstrak nama (jika ada di metadata)
        user_metadata = user_data.get('user_metadata', {})
        name = user_metadata.get('full_name', email.split('@')[0])

        print(f"\n[*] AI-Auth-System: Token Divalidasi oleh API Supabase untuk Email: {email} | Role: {role}")

        # ==========================================
        # 3. SINKRONISASI KE MYSQL LOKAL FLASK
        # ==========================================
        user = User.query.filter_by(email=email).first()
        
        if not user:
            print(f"[*] Akun baru terdeteksi. Mendaftarkan {email} secara otomatis ke MySQL...")
            user = User(
                name=name,
                email=email,
                provider_uid=supabase_uid,
                auth_provider='supabase',
                role=role
            )
            db.session.add(user)
            db.session.commit()
            print("[*] Sinkronisasi akun baru berhasil disimpan.")

        # 4. Terbitkan JWT Token Lokal milik Flask untuk mengunci sesi di Flutter GetX
        flask_access_token = create_access_token(identity=str(user.id))
        has_face_data = True if user.face_embedding_user else False

        return jsonify({
            "status": "success",
            "message": "Autentikasi berhasil disinkronkan dengan server lokal.",
            "data": {
                "token": flask_access_token,
                "has_face_data": has_face_data,
                "role": user.role
            }
        }), 200

    except Exception as e:
        # ... sisa kode tidak berubah ...
        db.session.rollback()
        print(f"[!] Server Error pada sistem autentikasi: {str(e)}")
        return jsonify({"status": "error", "message": f"Gagal memproses sinkronisasi: {str(e)}"}), 500

# ==========================================
# 2. SETUP WAJAH (Dilindungi JWT Lokal)
# ==========================================
@api_auth_bp.route('/setup-face', methods=['POST'])
@jwt_required()
def setup_face():
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    if not user:
        return jsonify({"status": "error", "message": "User tidak ditemukan."}), 404

    # 1. Cek lampiran file selfie
    if 'selfie_image' not in request.files:
        return jsonify({"status": "error", "message": "Foto selfie wajib dilampirkan!"}), 400
        
    file = request.files['selfie_image']
    if file.filename == '':
        return jsonify({"status": "error", "message": "File foto tidak boleh kosong."}), 400

    # 2. Proses ekstraksi wajah dengan AI
    ai_result = face_engine.get_face_from_file_stream(file)
    if ai_result['status'] == 'error':
        return jsonify({"status": "error", "message": ai_result['message']}), 400

    # 3. Jadikan array numpy 1D kembali ke string JSON
    vector_json = json.dumps(ai_result['vector'])

    try:
        user.face_embedding_user = vector_json
        db.session.commit()

        # 4. Picu pencarian AI asinkronus di background
        start_face_matching(current_app._get_current_object(), user.id, vector_json)

        return jsonify({
            "status": "success",
            "message": "Data wajah berhasil disimpan! AI sedang bekerja mencari foto Anda di background."
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": f"Gagal menyimpan data: {str(e)}"}), 500


# ==========================================
# 3. LOGOUT (Sisi Client)
# ==========================================
@api_auth_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    """
    Sistem JWT bersifat stateless. Server cukup meminta Flutter menghapus token di GetStorage/SharedPreferences.
    """
    return jsonify({
        "status": "success",
        "message": "Logout berhasil. Tolong hapus token di sisi aplikasi mobile."
    }), 200

@api_auth_bp.route('', methods=['GET'])
def home():
    return 'haloo'