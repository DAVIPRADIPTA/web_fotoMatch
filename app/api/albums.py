# from flask import Blueprint, request, jsonify, current_app
# from flask_jwt_extended import jwt_required, get_jwt_identity
# from app.models import Event, EventAlbum, User
# from app.extensions import db
# # Pastikan gdrive_service dan start_album_processing diimport dari tempat asalnya
# from app.services.gdrive import gdrive_service
# from app.services.processor import start_album_processing

# # Asumsi ini ditambahkan ke blueprint api_events_bp yang sudah dibuat sebelumnya
# @api_events_bp.route('/<int:event_id>/upload', methods=['POST'])
# @jwt_required()
# def upload_drive_api(event_id):
#     """
#     Setor Link Google Drive Album Event (Sisi Fotografer)
#     ---
#     tags:
#       - Album & Foto
#     security:
#       - Bearer: []
#     parameters:
#       - name: event_id
#         in: path
#         type: integer
#         required: true
#         description: ID Event yang ingin ditambahkan albumnya
#       - in: body
#         name: body
#         schema:
#           type: object
#           required:
#             - drive_folder_link
#             - price_digital
#           properties:
#             drive_folder_link:
#               type: string
#               example: "https://drive.google.com/drive/folders/1xyz..._abc"
#             price_digital:
#               type: integer
#               example: 50000
#             allow_physical_print:
#               type: boolean
#               example: true
#     responses:
#       201:
#         description: Link berhasil disimpan, AI mulai memproses di background
#       400:
#         description: Input tidak lengkap atau Anda sudah menyetor foto untuk event ini
#       401:
#         description: Token tidak valid atau tidak ditemukan
#       404:
#         description: Event tidak ditemukan
#       500:
#         description: Terjadi kesalahan server internal
#     """
#     # 1. Ambil identitas fotografer dari JWT Token
#     current_user_id = get_jwt_identity()

#     # 2. Cek apakah event ada
#     event = Event.query.get_or_404(event_id)
    
#     # 3. Cek apakah fotografer sudah pernah join event ini
#     existing_album = EventAlbum.query.filter_by(event_id=event_id, photographer_id=current_user_id).first()
#     if existing_album:
#         return jsonify({
#             "status": "error", 
#             "message": "Anda sudah pernah menyetor link Google Drive untuk event ini!"
#         }), 400

#     # 4. Ambil data dari JSON Body (Flutter akan mengirim format JSON)
#     data = request.get_json()
#     if not data:
#         return jsonify({"status": "error", "message": "Request body tidak boleh kosong."}), 400

#     drive_link = data.get('drive_folder_link')
#     price_digital = data.get('price_digital')
#     allow_print = data.get('allow_physical_print', False) # Default False jika tidak diisi

#     if not drive_link or price_digital is None:
#         return jsonify({
#             "status": "error", 
#             "message": "Link Google Drive dan harga foto digital wajib diisi."
#         }), 400

#     try:
#         # 5. Validasi dan ekstraksi Folder ID Google Drive
#         folder_id = gdrive_service.extract_folder_id(drive_link)
#         if not folder_id:
#             return jsonify({
#                 "status": "error", 
#                 "message": "Link Google Drive tidak valid atau tidak dapat diekstrak ID-nya."
#             }), 400
            
#         # Pengecekan isi foto (opsional, bisa dipertahankan dari kodemu)
#         photos = gdrive_service.list_photos(folder_id)
#         print(f"DEBUG: API Berhasil menemukan {len(photos)} foto di Google Drive!")
        
#         # 6. Simpan ke tabel event_albums
#         new_album = EventAlbum(
#             event_id=event.id,
#             photographer_id=current_user_id,
#             drive_folder_link=drive_link,
#             price_digital=int(price_digital),
#             allow_physical_print=bool(allow_print),
#             status_ai='idle'
#         )
#         db.session.add(new_album)
#         db.session.commit()
        
#         # 7. Trigger Background Task agar AI memproses foto tanpa membuat Flutter hang/timeout
#         start_album_processing(current_app._get_current_object(), new_album.id)
        
#         return jsonify({
#             "status": "success",
#             "message": "Link Google Drive berhasil disetorkan! Sistem AI kami sedang memproses ekstraksi wajah di latar belakang.",
#             "data": {
#                 "album_id": new_album.id,
#                 "event_id": event.id,
#                 "status_ai": new_album.status_ai
#             }
#         }), 201

#     except Exception as e:
#         db.session.rollback()
#         print(f"[!] API Error pada upload drive: {str(e)}")
#         return jsonify({
#             "status": "error", 
#             "message": f"Gagal memproses album event: {str(e)}"
#         }), 500