import json
from flask import Blueprint, request, jsonify, current_app
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from firebase_admin import auth as firebase_auth
from app.extensions import db
from app.models import User
from app.services.face_engine import face_engine
from app.services.matcher import start_face_matching


api_auth_bp = Blueprint('api_auth', __name__)

# ==========================================
# 1. REGISTER MANUAL
# ==========================================
@api_auth_bp.route('/register', methods=['POST'])
def register_buyer():
    name = request.form.get('name')
    email = request.form.get('email')
    password = request.form.get('password')

    if not name or not email or not password:
        return jsonify({"status": "error", "message": "Semua kolom wajib diisi."}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"status": "error", "message": "Email sudah terdaftar."}), 400

    try:
        new_user = User(
            name=name,
            email=email,
            password=generate_password_hash(password),
            role='buyer',
            auth_provider='manual'
        )
        db.session.add(new_user)
        db.session.commit()

        return jsonify({"status": "success", "message": "Registrasi berhasil! Silakan login."}), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

# ==========================================
# 2. LOGIN MANUAL
# ==========================================
@api_auth_bp.route('/login', methods=['POST'])
def login_manual():
    email = request.form.get('email')
    password = request.form.get('password')

    # # ==========================================
    # # RADAR DEBUG: BONGKAR APA YANG FLASK BACA
    # # ==========================================
    # print("\n========= DEBUG LOGIN MULAI =========")
    # print(f"1. Email dari Postman    : '{email}'")
    # print(f"2. Password dari Postman : '{password}'")

    user = User.query.filter_by(email=email).first()
    
    if user:
        print(f"3. Akun ditemukan di DB? : YA ({user.email})")
        print(f"4. Hash Password di DB   : '{user.password}'")
        
        # Kita tes langsung kecocokannya
        if password is not None:
            is_match = check_password_hash(user.password, password)
            print(f"5. Apakah Hash Cocok?    : {is_match}")
        else:
            print("5. Apakah Hash Cocok?    : GAGAL (Password dari Postman None)")
    else:
        print("3. Akun ditemukan di DB? : TIDAK ADA (Email tidak terdaftar/salah ketik)")
    
    print("========= DEBUG LOGIN SELESAI ========\n")
    # ==========================================

    if not user or not user.password or not check_password_hash(user.password, password):
        return jsonify({"status": "error", "message": "Email atau password salah."}), 401

    # Buat JWT Token
    from flask_jwt_extended import create_access_token
    access_token = create_access_token(identity=str(user.id))
    has_face_data = True if user.face_embedding_user else False

    return jsonify({
        "status": "success",
        "message": "Login berhasil.",
        "data": {
            "token": access_token,
            "has_face_data": has_face_data
        }
    }), 200

# ==========================================
# 3. LOGIN GOOGLE (HYBRID)
# ==========================================
@api_auth_bp.route('/login-google', methods=['POST'])
def login_google():
    """
    Flutter mengirimkan id_token yang didapat dari Firebase Auth (Google Sign-In).
    Flask memverifikasinya, jika valid, keluarkan JWT buatan Flask.
    """
    id_token = request.form.get('id_token')
    if not id_token:
        return jsonify({"status": "error", "message": "Token Google tidak ditemukan."}), 400

    try:
        # Verifikasi token menggunakan Firebase Admin SDK
        decoded_token = firebase_auth.verify_id_token(id_token)
        uid = decoded_token.get('uid')
        email = decoded_token.get('email')
        name = decoded_token.get('name', 'FotoMatch')

        # Cari user, jika belum ada, otomatis daftarkan (Register Otomatis)
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(
                email=email,
                name=name,
                firebase_uid=uid,
                auth_provider='google',
                role='buyer'
                # Password dikosongkan karena nullable=True di models.py
            )
            db.session.add(user)
            db.session.commit()

        # Generate JWT Flask
        access_token = create_access_token(identity=str(user.id))
        has_face_data = True if user.face_embedding_user else False

        return jsonify({
            "status": "success",
            "message": "Login Google berhasil.",
            "data": {
                "token": access_token,
                "has_face_data": has_face_data
            }
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": f"Token Google tidak valid: {str(e)}"}), 401

# ==========================================
# 4. SETUP WAJAH (Dilindungi JWT)
# ==========================================
# ==========================================
# 4. SETUP WAJAH MULTI-TEMPLATE (Depan & Samping)
# ==========================================
@api_auth_bp.route('/setup-face', methods=['POST'])
@jwt_required()
def setup_face():
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    if not user:
        return jsonify({"status": "error", "message": "User tidak ditemukan."}), 404

    # 1. Kembali cek 1 key saja: 'selfie_image'
    if 'selfie_image' not in request.files:
        return jsonify({"status": "error", "message": "Foto selfie wajib dilampirkan!"}), 400
        
    file = request.files['selfie_image']
    if file.filename == '':
        return jsonify({"status": "error", "message": "File foto tidak boleh kosong."}), 400

    # 2. Proses ekstraksi 1 wajah saja
    ai_result = face_engine.get_face_from_file_stream(file)
    if ai_result['status'] == 'error':
        return jsonify({"status": "error", "message": ai_result['message']}), 400

    # 3. Jadikan array numpy 1D kembali ke string JSON
    vector_json = json.dumps(ai_result['vector'])

    try:
        user.face_embedding_user = vector_json
        db.session.commit()

        # 4. Picu pencarian AI asinkronus dengan 1 vektor
        start_face_matching(current_app._get_current_object(), user.id, vector_json)

        return jsonify({
            "status": "success",
            "message": "Data wajah berhasil disimpan! AI sedang bekerja mencari foto Anda di background."
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": f"Gagal menyimpan data: {str(e)}"}), 500

# ==========================================
# 5. LOGOUT (Sisi Client)
# ==========================================
@api_auth_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    """
    Karena JWT adalah token stateless, server tidak perlu menyimpan daftar token 
    yang expired (kecuali butuh keamanan tingkat bank dengan blacklist redis).
    Cukup beritahu Flutter untuk menghapus token dari Shared Preferences/GetStorage.
    """
    return jsonify({
        "status": "success",
        "message": "Logout berhasil. Tolong hapus token di sisi aplikasi mobile."
    }), 200