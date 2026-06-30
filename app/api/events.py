# pyrefly: ignore [missing-import]
from flask import Blueprint, request, jsonify
# pyrefly: ignore [missing-import]
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models import Event, FaceMatch, Photo, User, EventAlbum, EventContributor
from app.extensions import db
from datetime import datetime
import os
# pyrefly: ignore [missing-import]
from flask import current_app
# pyrefly: ignore [missing-import]
from werkzeug.utils import secure_filename
# from flask import current_app
from app.services.gdrive import gdrive_service
from app.services.processor import start_album_processing

api_events_bp = Blueprint('api_events', __name__)

# ==========================================
# 1. READ ALL EVENTS & SEARCH (GET)
# Endpoint: GET /api/v1/events
# ==========================================
@api_events_bp.route('/', methods=['GET'])
@jwt_required(optional=True)
def get_events():
    """
    Mendapatkan Daftar Event & Pencarian
    ---
    tags:
      - Event
    security:
      - Bearer: []
    parameters:
      - name: search
        in: query
        type: string
        required: false
        description: Cari berdasarkan sebagian judul atau nama lokasi event
      - name: category
        in: query
        type: string
        required: false
        description: Filter berdasarkan kategori event (contoh. Musik, Pameran)
    responses:
      200:
        description: Berhasil mengambil data event
      500:
        description: Terjadi kesalahan internal
    """
    try:
        # Mengambil parameter pencarian dari URL (misal: ?search=konser&category=music)
        search_query = request.args.get('search', '')
        category_filter = request.args.get('category', '')
        current_user_id = get_jwt_identity()

        # Gunakan subquery jika ada token JWT
        if current_user_id:
            from sqlalchemy.sql import exists
            contributed_exists = exists().where(
                (EventContributor.event_id == Event.id) & 
                (EventContributor.photographer_id == current_user_id)
            )
            query = db.session.query(Event, contributed_exists.label('is_contributed'))
        else:
            query = db.session.query(Event)

        # Logika Pencarian (Search) berdasarkan Judul atau Lokasi
        if search_query:
            search_term = f"%{search_query}%"
            query = query.filter(db.or_(
                Event.title.ilike(search_term),
                Event.location_name.ilike(search_term)
            ))
        
        # Logika Filter berdasarkan Kategori
        if category_filter:
            query = query.filter(Event.category == category_filter)

        # Urutkan berdasarkan tanggal event (terbaru ke terlama)
        results = query.order_by(Event.event_date.desc()).all()

        data_list = []
        for res in results:
            if current_user_id:
                event, is_contributed = res
                d = event.to_dict()
                d["is_contributed"] = bool(is_contributed)
            else:
                event = res
                d = event.to_dict()
                d["is_contributed"] = False
            data_list.append(d)

        return jsonify({
            "status": "success",
            "message": "Data event berhasil diambil.",
            "data": data_list
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": f"Terjadi kesalahan: {str(e)}"}), 500

# ==========================================
# 2. READ SINGLE EVENT (GET)
# Endpoint: GET /api/v1/events/<id>
# ==========================================
@api_events_bp.route('/<int:id>', methods=['GET'])
def get_event(id):
    """
    Mendapatkan Detail Event berdasarkan ID
    ---
    tags:
      - Event
    parameters:
      - name: id
        in: path
        type: integer
        required: true
        description: ID Event yang ingin dilihat detailnya
    responses:
      200:
        description: Berhasil mendapatkan detail event
      404:
        description: Event tidak ditemukan
    """
    event = Event.query.get_or_404(id)
    return jsonify({
        "status": "success",
        "data": event.to_dict()
    }), 200

# ==========================================
# 3. CREATE EVENT (POST)
# Endpoint: POST /api/v1/events
# Dilindungi JWT, hanya untuk user yang login (Kreator/Fotografer)
# ==========================================
@api_events_bp.route('/', methods=['POST'])
@jwt_required()
def create_event():
    """
    Membuat Event Baru dengan Gambar (Butuh Login)
    ---
    tags:
      - Event
    security:
      - Bearer: []
    consumes:
      - multipart/form-data
    parameters:
      - in: formData
        name: title
        type: string
        required: true
        description: Judul event
      - in: formData
        name: category
        type: string
        description: Kategori event
      - in: formData
        name: event_date
        type: string
        description: Tanggal event (Format YYYY-MM-DD)
      - in: formData
        name: location_name
        type: string
        description: Nama lokasi event
      - in: formData
        name: image
        type: file
        description: File gambar poster/banner event (JPG/PNG)
    responses:
      201:
        description: Event berhasil dibuat
    """
    # Karena menggunakan multipart/form-data, kita gunakan request.form, bukan request.get_json()
    title = request.form.get('title')
    category = request.form.get('category')
    event_date_str = request.form.get('event_date')
    location_name = request.form.get('location_name')
    
    if not title:
        return jsonify({"status": "error", "message": "Judul (title) event wajib diisi."}), 400

    try:
        # 1. Parsing Tanggal
        event_date_obj = None
        if event_date_str:
            event_date_obj = datetime.strptime(event_date_str, '%Y-%m-%d').date()

        # 2. Logika Simpan Gambar
        image_file = request.files.get('image')
        saved_image_path = None

        if image_file and image_file.filename != '':
            # Bersihkan nama file dari karakter aneh
            filename = secure_filename(image_file.filename)
            # Tambahkan timestamp agar nama file unik (tidak tertimpa)
            unique_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
            
            # Buat folder static/uploads/events jika belum ada
            upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'events')
            os.makedirs(upload_folder, exist_ok=True)
            
            # Simpan file secara fisik
            file_path = os.path.join(upload_folder, unique_filename)
            image_file.save(file_path)
            
            # Catat path relatifnya untuk di database
            saved_image_path = f"/static/uploads/events/{unique_filename}"

        # 3. Simpan ke Database
        new_event = Event(
            title=title,
            category=category,
            event_date=event_date_obj,
            location_name=location_name,
            image_path=saved_image_path
        )
        
        db.session.add(new_event)
        db.session.commit()

        return jsonify({
            "status": "success",
            "message": "Event berhasil dibuat.",
            "data": new_event.to_dict()
        }), 201

    except ValueError:
        return jsonify({"status": "error", "message": "Format tanggal salah. Gunakan YYYY-MM-DD."}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": f"Gagal membuat event: {str(e)}"}), 500

# ==========================================
# 4. UPDATE EVENT (PUT)
# Endpoint: PUT /api/v1/events/<id>
# ==========================================
@api_events_bp.route('/<int:id>', methods=['PUT'])
@jwt_required()
def update_event(id):
    """
    Memperbarui Data Event (Butuh Login)
    ---
    tags:
      - Event
    security:
      - Bearer: []
    parameters:
      - name: id
        in: path
        type: integer
        required: true
        description: ID Event yang akan diperbarui
      - in: body
        name: body
        schema:
          type: object
          properties:
            title:
              type: string
              example: Konser Dewa 19 (Rescheduled)
            category:
              type: string
              example: Musik & Festival
            event_date:
              type: string
              example: "2026-08-18"
            location_name:
              type: string
              example: Alun-Alun Tegal
    responses:
      200:
        description: Event berhasil diperbarui
      401:
        description: Unauthorized
      404:
        description: Event tidak ditemukan
      500:
        description: Gagal memperbarui event
    """
    event = Event.query.get_or_404(id)
    data = request.get_json()

    try:
        if 'title' in data:
            event.title = data['title']
        if 'category' in data:
            event.category = data['category']
        if 'location_name' in data:
            event.location_name = data['location_name']
        if 'event_date' in data:
            if data['event_date']: # Jika tidak kosong
                event.event_date = datetime.strptime(data['event_date'], '%Y-%m-%d').date()
            else:
                event.event_date = None

        db.session.commit()
        
        return jsonify({
            "status": "success",
            "message": "Event berhasil diperbarui.",
            "data": event.to_dict()
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": f"Gagal memperbarui event: {str(e)}"}), 500

# ==========================================
# 5. DELETE EVENT (DELETE)
# Endpoint: DELETE /api/v1/events/<id>
# ==========================================
@api_events_bp.route('/<int:id>', methods=['DELETE'])
@jwt_required()
def delete_event(id):
    """
    Menghapus Event (Butuh Login)
    ---
    tags:
      - Event
    security:
      - Bearer: []
    parameters:
      - name: id
        in: path
        type: integer
        required: true
        description: ID Event yang akan dihapus
    responses:
      200:
        description: Event berhasil dihapus
      401:
        description: Unauthorized
      404:
        description: Event tidak ditemukan
      500:
        description: Gagal menghapus event
    """
    event = Event.query.get_or_404(id)
    
    try:
        db.session.delete(event)
        db.session.commit()
        
        return jsonify({
            "status": "success",
            "message": f"Event '{event.title}' berhasil dihapus."
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": f"Gagal menghapus event: {str(e)}"}), 500
    
@api_events_bp.route('/<int:event_id>/upload', methods=['POST'])
@jwt_required()
def upload_drive_api(event_id):
    """
    Setor Link Google Drive Album Event (Sisi Fotografer)
    ---
    tags:
      - Album & Foto
    security:
      - Bearer: []
    parameters:
      - name: event_id
        in: path
        type: integer
        required: true
        description: ID Event yang ingin ditambahkan albumnya
      - in: body
        name: body
        schema:
          type: object
          required:
            - drive_folder_link
            - price_digital
          properties:
            drive_folder_link:
              type: string
              example: "https://drive.google.com/drive/folders/1xyz..._abc"
            price_digital:
              type: integer
              example: 50000
            allow_physical_print:
              type: boolean
              example: true
    responses:
      201:
        description: Link berhasil disimpan, AI mulai memproses di background
      400:
        description: Input tidak lengkap atau Anda sudah menyetor foto untuk event ini
      401:
        description: Token tidak valid atau tidak ditemukan
      404:
        description: Event tidak ditemukan
      500:
        description: Terjadi kesalahan server internal
    """
    # 1. Ambil identitas fotografer dari JWT Token
    current_user_id = get_jwt_identity()

    # 2. Cek apakah event ada
    event = Event.query.get_or_404(event_id)
    
    # 3. Cek apakah fotografer sudah pernah join event ini
    existing_album = EventAlbum.query.filter_by(event_id=event_id, photographer_id=current_user_id).first()
    if existing_album:
        return jsonify({
            "status": "error", 
            "message": "Anda sudah pernah menyetor link Google Drive untuk event ini!"
        }), 400

    # 4. Ambil data dari JSON Body (Flutter akan mengirim format JSON)
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "Request body tidak boleh kosong."}), 400

    drive_link = data.get('drive_folder_link')
    price_digital = data.get('price_digital')
    allow_print = data.get('allow_physical_print', False) # Default False jika tidak diisi

    if not drive_link or price_digital is None:
        return jsonify({
            "status": "error", 
            "message": "Link Google Drive dan harga foto digital wajib diisi."
        }), 400

    try:
        # 5. Validasi dan ekstraksi Folder ID Google Drive
        folder_id = gdrive_service.extract_folder_id(drive_link)
        if not folder_id:
            return jsonify({
                "status": "error", 
                "message": "Link Google Drive tidak valid atau tidak dapat diekstrak ID-nya."
            }), 400
            
        # Pengecekan isi foto (opsional, bisa dipertahankan dari kodemu)
        photos = gdrive_service.list_photos(folder_id)
        print(f"DEBUG: API Berhasil menemukan {len(photos)} foto di Google Drive!")
        
        # 6. Simpan ke tabel event_albums
        new_album = EventAlbum(
            event_id=event.id,
            photographer_id=current_user_id,
            drive_folder_link=drive_link,
            price_digital=int(price_digital),
            allow_physical_print=bool(allow_print),
            status_ai='idle'
        )
        db.session.add(new_album)
        
        # 6b. Catat ke tabel event_contributors jika belum ada
        contributor = EventContributor.query.filter_by(event_id=event.id, photographer_id=current_user_id).first()
        if not contributor:
            new_contributor = EventContributor(
                event_id=event.id,
                photographer_id=current_user_id
            )
            db.session.add(new_contributor)
        
        db.session.commit()
        
        # 7. Trigger Background Task agar AI memproses foto tanpa membuat Flutter hang/timeout
        start_album_processing(current_app._get_current_object(), new_album.id)
        
        return jsonify({
            "status": "success",
            "message": "Link Google Drive berhasil disetorkan! Sistem AI kami sedang memproses ekstraksi wajah di latar belakang.",
            "data": {
                "album_id": new_album.id,
                "event_id": event.id,
                "status_ai": new_album.status_ai
            }
        }), 201

    except Exception as e:
        db.session.rollback()
        print(f"[!] API Error pada upload drive: {str(e)}")
        return jsonify({
            "status": "error", 
            "message": f"Gagal memproses album event: {str(e)}"
        }), 500

@api_events_bp.route('/<int:event_id>/matches', methods=['GET'])
@jwt_required()
def get_matched_photos(event_id):
    """
    Mengambil foto yang cocok dengan wajah user untuk event tertentu
    ---
    tags:
      - Event
    summary: "Dapatkan foto hasil pencarian wajah (Face Match)"
    security:
      - Bearer: []
    parameters:
      - name: event_id
        in: path
        type: integer
        required: true
        description: ID dari event yang ingin dicek
    responses:
      200:
        description: Berhasil mendapatkan daftar foto yang cocok
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            message:
              type: string
              example: Foto yang cocok ditemukan.
            data:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                    example: 125
                  preview_path:
                    type: string
                    example: "https://storage.fotomatch.com/photos/event_10_photo_125.jpg"
                  match_score:
                    type: number
                    format: float
                    example: 0.985
      500:
        description: Terjadi kesalahan pada server
    """
    current_user_id = get_jwt_identity()

    try:
        # Melakukan JOIN antara tabel Photo dan FaceMatch
        # Kita cari foto yang (event_id == event_id) DAN (user_id == current_user_id)
        matched_photos = db.session.query(Photo).join(FaceMatch, Photo.id == FaceMatch.photo_id) .filter(Photo.event_id == event_id) .filter(FaceMatch.user_id == current_user_id) .all()

        # Format respons
        result = []
        for photo in matched_photos:
            # Cari skor kecocokan spesifik untuk user ini dari tabel face_matches
            match = FaceMatch.query.filter_by(photo_id=photo.id, user_id=current_user_id).first()
            
            result.append({
                "id": photo.id,
                "preview_path": photo.preview_path, # Pastikan ini nama field di model Photo
                "match_score": match.match_score if match else 0
            })

        return jsonify({
            "status": "success",
            "message": "Foto yang cocok ditemukan.",
            "data": result
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": f"Terjadi kesalahan: {str(e)}"}), 500

@api_events_bp.route('/contributed', methods=['GET'])
@jwt_required()
def get_contributed_events():
    """
    Daftar Event Kontribusi Fotografer
    ---
    tags:
      - Event
    security:
      - Bearer: []
    responses:
      200:
        description: Berhasil mengambil daftar event kontribusi
      500:
        description: Terjadi kesalahan internal
    """
    try:
        current_user_id = get_jwt_identity()

        events = Event.query.join(EventContributor, Event.id == EventContributor.event_id)\
            .filter(EventContributor.photographer_id == current_user_id)\
            .order_by(Event.event_date.desc())\
            .all()

        return jsonify({
            "status": "success",
            "message": "Daftar event kontribusi berhasil diambil.",
            "data": [event.to_dict() for event in events]
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": f"Gagal mengambil daftar event kontribusi: {str(e)}"}), 500