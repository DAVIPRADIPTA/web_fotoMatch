import json
import threading
import os
import tempfile
import face_recognition
import io
from googleapiclient.http import MediaIoBaseDownload
from app.extensions import db
from app.models import EventAlbum, Photo, FaceEmbedding, User, FaceMatch, TemporaryScan
from app.services.gdrive import gdrive_service
from app.services.face_engine import face_engine
import numpy as np

MATCH_THRESHOLD = 0.5 
def process_album_background(app, album_id):
    with app.app_context():
        album = EventAlbum.query.get(album_id)
        if not album:
            return

        album.status_ai = 'processing'
        db.session.commit()
        print(f"[*] Memulai proses AI untuk Album ID: {album.id}")

        try:
            folder_id = gdrive_service.extract_folder_id(album.drive_folder_link)
            photos_in_drive = gdrive_service.list_photos(folder_id)
            print(f"[*] Ditemukan {len(photos_in_drive)} foto di GDrive.")

            # KUNCI: Ambil semua user yang sudah punya face_embedding SEBELUM looping foto
            all_users = User.query.filter(User.face_embedding_user.isnot(None)).all()

            for g_photo in photos_in_drive:
                file_id = g_photo['id']
                
                # 1. Buat link permanen secara manual
                # Link original untuk di-download setelah pembeli membayar
                permanent_original_link = f"https://drive.google.com/uc?export=download&id={file_id}"
                
                # Link preview (thumbnail) dengan ukuran ringan untuk ditampilkan di Flutter (tidak akan expired)
                permanent_preview_link = f"https://drive.google.com/thumbnail?id={file_id}&sz=w500"
                # 1. Pastikan kamu sudah query albumnya
                
                # 2. Simpan ke tabel Photo
                new_photo = Photo(
                    event_id=album.event_id,
                    album_id=album.id,
                    gdrive_file_id=file_id,
                    file_name=g_photo.get('name'),
                    original_path=permanent_original_link, # Gunakan link manual
                    preview_path=permanent_preview_link,   # Gunakan link manual
                    price_digital=album.price_digital
                )
                db.session.add(new_photo)
                db.session.commit()

                download_url = g_photo.get('webContentLink')
                if not download_url:
                    continue
                
                # Ekstrak wajah dari foto GDrive
                face_vectors = face_engine.get_faces_from_url(download_url)

                for vector in face_vectors:
                    vector_list = vector.tolist()
                    vector_json = json.dumps(vector_list)
                    
                    # 1. Simpan ke FaceEmbedding
                    new_face = FaceEmbedding(
                        photo_id=new_photo.id,
                        embedding_vector=vector_json
                    )
                    db.session.add(new_face)
                    db.session.commit() # Commit agar new_face tersimpan dengan aman
                    
                    # 2. CROSS-MATCHING: Adu wajah baru ini dengan SEMUA user lama
                    for user in all_users:
                        user_vector = np.array(json.loads(user.face_embedding_user))
                        
                        # Hitung kemiripan
                        distance = np.linalg.norm(vector - user_vector)
                        
                        if distance < MATCH_THRESHOLD:
                            existing_match = FaceMatch.query.filter_by(user_id=user.id, photo_id=new_photo.id).first()
                            
                            if not existing_match:
                                new_match = FaceMatch(
                                    user_id=user.id,
                                    photo_id=new_photo.id,
                                    match_score=float(distance),
                                    is_confirmed=True
                                )
                                db.session.add(new_match)
                                print(f"    [+] MATCH DITEMUKAN! Foto {g_photo.get('name')} milik User ID {user.id}")
                
                db.session.commit()
                print(f"[+] Selesai mengekstrak & mencocokkan: {g_photo.get('name')} | Ditemukan {len(face_vectors)} wajah")

            # Jika semua foto sudah selesai, ubah status
            album.status_ai = 'completed'
            db.session.commit()
            print(f"[*] YAY! Album ID {album.id} selesai diproses dan dicocokkan sepenuhnya!")

        except Exception as e:
            album.status_ai = 'error' # Ubah ke 'error' sesuai ENUM database-mu
            db.session.commit()
            print(f"[!] GAGAL memproses Album ID {album.id}. Error: {e}")

def start_album_processing(app, album_id):
    thread = threading.Thread(target=process_album_background, args=(app, album_id))
    thread.daemon = True
    thread.start()

def process_buyer_scan_background(app, user_id, folder_id):
    with app.app_context():
        print(f"[*] Memulai scan folder GDrive {folder_id} untuk User ID: {user_id}")
        user = User.query.get(user_id)
        if not user or not user.face_embedding_user:
            print(f"[!] User {user_id} tidak ditemukan atau tidak memiliki face embedding.")
            return

        try:
            user_vector = np.array(json.loads(user.face_embedding_user))
        except Exception as e:
            print(f"[!] Gagal decode face embedding user {user_id}: {e}")
            return

        try:
            photos_in_drive = gdrive_service.list_photos(folder_id)
            print(f"[*] Ditemukan {len(photos_in_drive)} foto untuk di-scan.")

            for g_photo in photos_in_drive:
                file_id = g_photo['id']
                
                # Setup link permanen
                permanent_original_link = f"https://drive.google.com/uc?export=download&id={file_id}"
                permanent_preview_link = f"https://drive.google.com/thumbnail?id={file_id}&sz=w500"

                # Unduh gambar secara sementara ke /tmp
                temp_file_path = os.path.join(tempfile.gettempdir(), f"scan_{user_id}_{file_id}.jpg")
                
                try:
                    # Download menggunakan Google Drive API client
                    request_media = gdrive_service.service.files().get_media(fileId=file_id)
                    with io.FileIO(temp_file_path, 'wb') as fh:
                        downloader = MediaIoBaseDownload(fh, request_media)
                        done = False
                        while done is False:
                            status, done = downloader.next_chunk()

                    # Cari wajah dalam gambar
                    image = face_recognition.load_image_file(temp_file_path)
                    face_locations = face_recognition.face_locations(image)
                    face_encodings = face_recognition.face_encodings(image, face_locations)

                    # Bandingkan setiap wajah
                    for face_encoding in face_encodings:
                        distance = np.linalg.norm(face_encoding - user_vector)
                        if distance < MATCH_THRESHOLD:
                            # Cocok! Simpan ke TemporaryScan
                            new_scan = TemporaryScan(
                                user_id=user_id,
                                gdrive_file_id=file_id,
                                preview_path=permanent_preview_link,
                                download_url=permanent_original_link,
                                match_score=float(distance)
                            )
                            db.session.add(new_scan)
                            print(f"    [+] MATCH DITEMUKAN! Foto {g_photo.get('name')} cocok dengan User ID {user_id}")
                            break # Cukup satu wajah yang cocok per foto

                    db.session.commit()

                except Exception as file_error:
                    db.session.rollback()
                    print(f"[!] Gagal memproses file GDrive {file_id}: {file_error}")

                finally:
                    # Hapus file fisik dari /tmp agar tidak memenuhi server
                    if os.path.exists(temp_file_path):
                        try:
                            os.remove(temp_file_path)
                        except Exception as delete_error:
                            print(f"[!] Gagal menghapus file sementara {temp_file_path}: {delete_error}")

            print(f"[*] Selesai men-scan folder {folder_id} untuk User ID: {user_id}")

        except Exception as e:
            print(f"[!] GAGAL menjalankan proses scan folder untuk User ID {user_id}. Error: {e}")

def start_buyer_scan(app, user_id, folder_id):
    thread = threading.Thread(target=process_buyer_scan_background, args=(app, user_id, folder_id))
    thread.daemon = True
    thread.start()