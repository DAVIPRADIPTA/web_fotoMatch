import json
import jwt  # Pastikan menginstal PyJWT (pip install PyJWT)
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
import urllib
from app.extensions import db
from app.models import User, TemporaryScan
from app.services.face_engine import face_engine
from app.services.matcher import start_face_matching
from app.services.processor import start_buyer_scan
from app.services.gdrive import gdrive_service

api_auth_bp = Blueprint('api_auth', __name__)

# ==========================================
# 1. LOGIN SUPABASE (OTP EMAIL & GOOGLE)
# ==========================================
@api_auth_bp.route('/login-supabase', methods=['POST'])
def login_supabase():
    """
    Sinkronisasi Login Supabase ke MySQL Lokal
    ---
    tags:
      - Autentikasi
    consumes:
      - application/x-www-form-urlencoded
    parameters:
      - name: access_token
        in: formData
        type: string
        required: true
        description: JWT Access Token yang didapatkan dari Supabase (via OTP / Google Sign-In)
      - name: role
        in: formData
        type: string
        required: false
        default: buyer
        description: Peran pengguna (buyer, photographer, atau admin)
    responses:
      200:
        description: Autentikasi berhasil, mengembalikan token JWT Flask
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            message:
              type: string
              example: Autentikasi berhasil disinkronkan dengan server lokal.
            data:
              type: object
              properties:
                token:
                  type: string
                has_face_data:
                  type: boolean
                role:
                  type: string
      400:
        description: Access Token tidak ditemukan
      401:
        description: Token Supabase tidak valid atau kadaluwarsa
      500:
        description: Kesalahan server internal
    """
    supabase_token = request.form.get('access_token')
    role = request.form.get('role', 'kreator')
    
    if not supabase_token:
        return jsonify({"status": "error", "message": "Autentikasi gagal. Access Token Supabase tidak ditemukan."}), 400

    try:
        # PENGGUNAAN KREDENSIAL DARI .ENV (VIA CONFIG)
        SUPABASE_URL = current_app.config['SUPABASE_URL']
        SUPABASE_ANON_KEY = current_app.config['SUPABASE_ANON_KEY']
        
        req = urllib.request.Request(f"{SUPABASE_URL}/auth/v1/user")
        
        req.add_header("Authorization", f"Bearer {supabase_token}")
        req.add_header("apikey", SUPABASE_ANON_KEY) 
        
        try:
            response = urllib.request.urlopen(req)
            user_data = json.loads(response.read())
        except Exception as e:
            print(f"[!] Auth Error: Server Supabase menolak token: {str(e)}")
            return jsonify({"status": "error", "message": "Sesi tidak valid atau telah kadaluwarsa. Silakan login ulang."}), 401

        supabase_uid = user_data.get('id')
        email = user_data.get('email')
        
        user_metadata = user_data.get('user_metadata', {})
        name = user_metadata.get('full_name', email.split('@')[0])

        user = User.query.filter_by(email=email).first()
        
        if not user:
            user = User(
                name=name,
                email=email,
                provider_uid=supabase_uid,
                auth_provider='supabase',
                role=role
            )
            db.session.add(user)
            db.session.commit()

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
        db.session.rollback()
        print(f"[!] Server Error pada sistem autentikasi: {str(e)}")
        return jsonify({"status": "error", "message": f"Gagal memproses sinkronisasi: {str(e)}"}), 500
    
# ==========================================
# 2. SETUP WAJAH (Dilindungi JWT Lokal)
# ==========================================
@api_auth_bp.route('/setup-face', methods=['POST'])
@jwt_required()
def setup_face():
    """
    Setup Wajah (Face Onboarding)
    ---
    tags:
      - Autentikasi
    security:
      - Bearer: []
    consumes:
      - multipart/form-data
    parameters:
      - in: formData
        name: selfie_image
        type: file
        required: true
        description: Foto selfie wajah user (JPG/PNG) untuk ekstraksi biometrik
    responses:
      200:
        description: Data wajah berhasil disimpan dan pencarian AI dimulai
      400:
        description: File foto tidak ditemukan atau wajah tidak terdeteksi
      404:
        description: User tidak ditemukan
      500:
        description: Terjadi kesalahan internal server
    """
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

@api_auth_bp.route('/scan-folder', methods=['POST'])
@jwt_required()
def scan_folder():
    """
    Buyer Self-Scan Folder
    ---
    tags:
      - Autentikasi
    security:
      - Bearer: []
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - folder_url
          properties:
            folder_url:
              type: string
              description: URL Google Drive folder milik pembeli
              example: "https://drive.google.com/drive/folders/1A2B3C4D5E6F7G8H9I"
    responses:
      202:
        description: Proses scanning dimulai di background
      400:
        description: Bad Request (URL folder tidak valid atau kosong)
      404:
        description: User tidak ditemukan
      500:
        description: Internal Server Error
    """
    data = request.get_json()
    folder_url = data.get('folder_url')

    if not folder_url:
        return jsonify({"status": "error", "message": "URL folder Google Drive wajib diisi."}), 400

    folder_id = gdrive_service.extract_folder_id(folder_url)
    if not folder_id:
        return jsonify({"status": "error", "message": "Format URL Google Drive folder tidak valid."}), 400

    current_user_identity = get_jwt_identity()
    try:
        if isinstance(current_user_identity, int) or str(current_user_identity).isdigit():
            user = User.query.get(int(current_user_identity))
        else:
            user = User.query.filter_by(email=current_user_identity).first()

        if not user:
            return jsonify({"status": "error", "message": "User tidak ditemukan"}), 404

        # 1. Hapus data TemporaryScan lama milik user ini
        TemporaryScan.query.filter_by(user_id=user.id).delete()
        db.session.commit()

        # 2. Pemicu background thread
        start_buyer_scan(current_app._get_current_object(), user.id, folder_id)

        return jsonify({
            "status": "success",
            "message": "Pencarian wajah sedang diproses di background."
        }), 202

    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": f"Gagal memulai pencarian wajah: {str(e)}"}), 500


@api_auth_bp.route('/scan-results', methods=['GET'])
@jwt_required()
def get_scan_results():
    """
    Dapatkan Hasil Scan Mandiri Buyer
    ---
    tags:
      - Autentikasi
    security:
      - Bearer: []
    responses:
      200:
        description: Berhasil mengambil hasil scan wajah dari folder pribadi
      404:
        description: User tidak ditemukan
      500:
        description: Internal Server Error
    """
    current_user_identity = get_jwt_identity()
    try:
        if isinstance(current_user_identity, int) or str(current_user_identity).isdigit():
            user = User.query.get(int(current_user_identity))
        else:
            user = User.query.filter_by(email=current_user_identity).first()

        if not user:
            return jsonify({"status": "error", "message": "User tidak ditemukan"}), 404

        # Ambil hasil scan diurutkan berdasarkan kecocokan terbaik (jarak terkecil)
        results = TemporaryScan.query.filter_by(user_id=user.id).order_by(TemporaryScan.match_score.asc()).all()

        data = []
        for res in results:
            data.append({
                "id": res.id,
                "gdrive_file_id": res.gdrive_file_id,
                "preview_path": res.preview_path,
                "download_url": res.download_url,
                "match_score": res.match_score,
                "created_at": res.created_at.isoformat() if res.created_at else None
            })

        return jsonify({
            "status": "success",
            "message": "Berhasil mengambil hasil scan wajah.",
            "data": data
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": f"Gagal mengambil hasil scan: {str(e)}"}), 500

@api_auth_bp.route('/profile', methods=['PUT'])
@jwt_required()
def update_profile():
    """
    Update Profil Pengguna
    ---
    tags:
      - Autentikasi
    security:
      - Bearer: []
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            name:
              type: string
              description: Nama lengkap baru
              example: "Davi Pradipta"
            phone:
              type: string
              description: Nomor telepon baru
              example: "081234567890"
            postal_code:
              type: integer
              description: Kode pos baru
              example: 40132
    responses:
      200:
        description: Profil berhasil diperbarui
      404:
        description: User tidak ditemukan
      500:
        description: Internal Server Error
    """
    current_user_identity = get_jwt_identity()
    try:
        if isinstance(current_user_identity, int) or str(current_user_identity).isdigit():
            user = User.query.get(int(current_user_identity))
        else:
            user = User.query.filter_by(email=current_user_identity).first()

        if not user:
            return jsonify({"status": "error", "message": "User tidak ditemukan"}), 404

        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "Payload JSON kosong atau tidak valid."}), 400

        # Update data profil jika disediakan di body request
        if 'name' in data:
            user.name = data['name']
        if 'phone' in data:
            user.phone = data['phone']
        if 'postal_code' in data:
            try:
                user.postal_code = int(data['postal_code']) if data['postal_code'] is not None else None
            except ValueError:
                return jsonify({"status": "error", "message": "Kode pos harus berupa angka."}), 400

        db.session.commit()

        return jsonify({
            "status": "success",
            "message": "Profil berhasil diperbarui.",
            "data": user.to_dict()
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": f"Gagal memperbarui profil: {str(e)}"}), 500