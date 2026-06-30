import os
from datetime import datetime
# pyrefly: ignore [missing-import]
from werkzeug.utils import secure_filename
# pyrefly: ignore [missing-import]
from flask import Blueprint, jsonify, request, current_app
# pyrefly: ignore [missing-import]
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models import StudioService, Studio
from app.extensions import db
# ... (API GET yang sebelumnya tetap ada di sini) ...

api_studios_bp = Blueprint('api_studios', __name__)

@api_studios_bp.route('/services', methods=['POST'])
@jwt_required()
def create_studio_service():
    """
    Tambah Layanan Cetak/Bingkai Baru (Sisi Fotografer)
    ---
    tags:
      - Studio & Layanan
    security:
      - Bearer: []
    consumes:
      - multipart/form-data
    parameters:
      - in: formData
        name: service_name
        type: string
        required: true
        description: Nama layanan (contoh. Bingkai Kayu Minimalis)
      - in: formData
        name: service_type
        type: string
        required: true
        enum: [print, frame]
        description: Jenis layanan
      - in: formData
        name: additional_price
        type: integer
        required: true
        description: Harga layanan (contoh. 35000)
      - in: formData
        name: image
        type: file
        description: Foto preview bingkai (opsional tapi disarankan)
    responses:
      201:
        description: Layanan berhasil ditambahkan
    """
    current_user_id = get_jwt_identity()
    
    service_name = request.form.get('service_name')
    service_type = request.form.get('service_type')
    additional_price = request.form.get('additional_price')

    if not service_name or not service_type or additional_price is None:
        return jsonify({"status": "error", "message": "Data nama, tipe, dan harga wajib diisi."}), 400

    try:
        # Logika Simpan Gambar (Jika fotografer melampirkan foto bingkai)
        image_file = request.files.get('image')
        saved_image_path = None

        if image_file and image_file.filename != '':
            filename = secure_filename(image_file.filename)
            unique_filename = f"frame_{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
            
            # Simpan di folder khusus bingkai
            upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'frames')
            os.makedirs(upload_folder, exist_ok=True)
            
            file_path = os.path.join(upload_folder, unique_filename)
            image_file.save(file_path)
            
            saved_image_path = f"/static/uploads/frames/{unique_filename}"

        # Simpan ke Database
        new_service = StudioService(
            user_id=current_user_id,
            service_name=service_name,
            service_type=service_type,
            additional_price=int(additional_price),
            image_path=saved_image_path
        )
        
        db.session.add(new_service)
        db.session.commit()

        return jsonify({
            "status": "success",
            "message": "Layanan studio berhasil ditambahkan.",
            "data": new_service.to_dict()
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": f"Gagal menambah layanan: {str(e)}"}), 500