import face_recognition
import cv2
import numpy as np
import requests
# from deepface import DeepFace

class FaceEngine:
    def __init__(self):
        pass

    def get_faces_from_url(self, image_url):
        """
        Mengunduh gambar dari URL dan mengembalikan list vektor wajah.
        """
        try:
            # 1. Download gambar dari Google Drive (Thumbnail/WebContent)
            response = requests.get(image_url)
            if response.status_code != 200:
                print(f"Gagal download gambar: {image_url}")
                return []

            # 2. Ubah data gambar menjadi format matriks OpenCV/NumPy
            image_array = np.asarray(bytearray(response.content), dtype=np.uint8)
            img = cv2.imdecode(image_array, cv2.IMREAD_COLOR)

            # 3. face_recognition butuh format RGB, sedangkan OpenCV pakai BGR
            rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

            # 4. Cari letak semua wajah di foto tersebut
            face_locations = face_recognition.face_locations(rgb_img)
            
            if not face_locations:
                return [] # Tidak ada wajah ditemukan

            # 5. Ekstrak wajah menjadi Vektor (128 dimensi angka)
            face_encodings = face_recognition.face_encodings(rgb_img, face_locations)

            print(f"AI Menemukan {len(face_encodings)} wajah dalam foto!")
            return face_encodings

            # try:
            #     # DeepFace akan mencari wajah dan langsung mengubahnya jadi vektor
            #     # Kita pakai model 'Facenet' agar outputnya sama-sama 128 angka
            #     results = DeepFace.represent(
            #         img_path=img, 
            #         model_name="Facenet", 
            #         enforce_detection=True # Akan error jika tidak ada wajah
            #     )
                
            #     # DeepFace mengembalikan list of dictionary, kita ambil angka 'embedding'-nya saja
            #     # dan kita ubah jadi numpy array agar cocok dengan script processor.py kita
            #     face_encodings = [np.array(res['embedding']) for res in results]
                
            #     print(f"AI (DeepFace) menemukan {len(face_encodings)} wajah dalam foto!")
            #     return face_encodings
                
            # except ValueError:
            #     # DeepFace akan melempar ValueError jika enforce_detection=True dan wajah tidak ditemukan
            #     print(f"AI (DeepFace) tidak menemukan wajah dalam foto ini.")
            #     return []

        except Exception as e:
            print(f"Error pada Face Engine: {e}")
            return []
    
    def get_face_from_file_stream(self, file_stream):
        """
        Membaca file gambar langsung dari request API Mobile (Flutter)
        dan mengekstrak tepat 1 wajah untuk profil pelari.
        """
        try:
            # 1. Baca data byte dari file yang diupload pelari
            file_bytes = np.frombuffer(file_stream.read(), np.uint8)
            img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)

            if img is None:
                return {"status": "error", "message": "File gambar tidak valid atau rusak."}

            # 2. face_recognition butuh format RGB
            rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

            # 3. Cari letak wajah pelari
            face_locations = face_recognition.face_locations(rgb_img)

            if len(face_locations) == 0:
                return {"status": "error", "message": "Wajah tidak terdeteksi. Coba di tempat yang lebih terang."}
            elif len(face_locations) > 1:
                return {"status": "error", "message": "Terdeteksi lebih dari satu wajah! Pastikan hanya wajah Anda di foto."}

            # 4. Ekstrak vektor wajah (128 dimensi)
            face_encodings = face_recognition.face_encodings(rgb_img, face_locations)
            
            # Kita ubah array numpy menjadi list biasa agar siap dijadikan JSON
            return {"status": "success", "vector": face_encodings[0].tolist()}

        except Exception as e:
            return {"status": "error", "message": f"Terjadi kesalahan sistem AI: {str(e)}"}

face_engine = FaceEngine()