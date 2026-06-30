import json
import threading
import numpy as np
from app.extensions import db
from app.models import EventAlbum, Photo, FaceEmbedding, FaceMatch, User
from app.services.gdrive import gdrive_service
from app.services.face_engine import face_engine

# Ambang batas kecocokan AI (Semakin kecil = semakin ketat/mirip)
# 0.5 adalah standar yang sangat baik untuk model face_recognition
MATCH_THRESHOLD = 0.5 

# =====================================================================
# SKENARIO 1: USER BARU DAFTAR -> COCOKKAN DENGAN SEMUA FOTO LAMA
# =====================================================================
def run_background_matching(app, user_id, buyer_vector_json):
    with app.app_context():
        print(f"[*] AI Matcher: Memulai pencarian masal untuk User ID {user_id}...")
        
        # Dekode string JSON menjadi array numpy 1D
        buyer_vector = np.array(json.loads(buyer_vector_json))
        
        # Ambil semua wajah yang pernah ada di database
        all_event_faces = FaceEmbedding.query.all()
        match_count = 0
        
        for face in all_event_faces:
            db_vector = np.array(json.loads(face.embedding_vector))
            
            # Hitung jarak Euclidean (tingkat kemiripan)
            distance = np.linalg.norm(buyer_vector - db_vector)
            
            if distance < MATCH_THRESHOLD:
                # Cek duplikasi
                existing_match = FaceMatch.query.filter_by(user_id=user_id, photo_id=face.photo_id).first()
                
                if not existing_match:
                    new_match = FaceMatch(
                        user_id=user_id,
                        photo_id=face.photo_id,
                        match_score=float(distance),
                        is_confirmed=True # Langsung confirm agar muncul di aplikasi
                    )
                    db.session.add(new_match)
                    match_count += 1
        
        try:
            db.session.commit()
            print(f"[*] AI Matcher Selesai! Berhasil memanen {match_count} foto untuk User ID {user_id}.")
        except Exception as e:
            db.session.rollback()
            print(f"[!] AI Matcher Error saat commit database: {str(e)}")

def start_face_matching(app, user_id, buyer_vector_json):
    thread = threading.Thread(target=run_background_matching, args=(app, user_id, buyer_vector_json))
    thread.daemon = True
    thread.start()


# =====================================================================
# SKENARIO 2: DRIVE BARU DIUPLOAD -> COCOKKAN DENGAN SEMUA USER LAMA
# =====================================================================
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
                # Simpan ke tabel Photo
                new_photo = Photo(
                    album_id=album.id,
                    gdrive_file_id=g_photo['id'],
                    file_name=g_photo.get('name'),
                    original_path=g_photo.get('webContentLink'),
                    preview_path=g_photo.get('thumbnailLink'),
                    price_digital=album.price_digital
                )
                db.session.add(new_photo)
                db.session.commit() # Commit agar new_photo.id ter-generate

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