import json
import threading
from app.extensions import db
from app.models import EventAlbum, Photo, FaceEmbedding
from app.services.gdrive import gdrive_service
from app.services.face_engine import face_engine

def process_album_background(app, album_id):
    """
    Fungsi ini akan berjalan di belakang layar (background thread).
    Kita butuh variabel 'app' agar bisa tetap memakai database Flask.
    """
    with app.app_context():
        album = EventAlbum.query.get(album_id)
        if not album:
            return

        # 1. Ubah status jadi sedang diproses
        album.status_ai = 'processing'
        db.session.commit()
        print(f"[*] Memulai proses AI untuk Album ID: {album.id}")

        try:
            folder_id = gdrive_service.extract_folder_id(album.drive_folder_link)
            photos_in_drive = gdrive_service.list_photos(folder_id)
            print(f"[*] Ditemukan {len(photos_in_drive)} foto di GDrive.")

            for g_photo in photos_in_drive:
                # 2. Simpan data gambar ke tabel Photo
                new_photo = Photo(
                    album_id=album.id,
                    gdrive_file_id=g_photo['id'],
                    file_name=g_photo.get('name'),
                    original_path=g_photo.get('webContentLink'), # Menggunakan original_path
                    preview_path=g_photo.get('thumbnailLink'),   # Menggunakan preview_path
                    price_digital=album.price_digital            # Ambil harga dari settingan album
                )
                db.session.add(new_photo)
                db.session.commit() # Commit agar new_photo punya ID

                # 3. Unduh foto aslinya dan masukkan ke Mesin AI
                download_url = g_photo.get('webContentLink')
                if not download_url:
                    continue
                
                # Ekstrak wajah (bisa dapat 0, 1, atau 5 wajah dalam satu foto)
                face_vectors = face_engine.get_faces_from_url(download_url)

                # 4. Simpan angka-angka wajah ke tabel FaceEmbedding
                for vector in face_vectors:
                    vector_list = vector.tolist()
                    vector_json = json.dumps(vector_list)
                    
                    new_face = FaceEmbedding(
                        photo_id=new_photo.id,
                        embedding_vector=vector_json # Menggunakan embedding_vector
                    )
                    db.session.add(new_face)
                
                db.session.commit()
                print(f"[+] Selesai proses: {g_photo.get('name')} | Ditemukan {len(face_vectors)} wajah")

            # 5. Jika semua foto sudah selesai, ubah status
            album.status_ai = 'completed'
            db.session.commit()
            print(f"[*] YAY! Album ID {album.id} selesai diproses!")

        except Exception as e:
            album.status_ai = 'failed'
            db.session.commit()
            print(f"[!] GAGAL memproses Album ID {album.id}. Error: {e}")

def start_album_processing(app, album_id):
    """Fungsi pelatuk untuk memulai background thread"""
    thread = threading.Thread(target=process_album_background, args=(app, album_id))
    thread.daemon = True # Agar thread mati kalau server Flask dimatikan
    thread.start()