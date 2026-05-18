import json
import threading
import numpy as np
from app.extensions import db
from app.models import FaceEmbedding, FaceMatch

def run_background_matching(app, user_id, buyer_vector_json):
    with app.app_context():
        print(f"[*] AI Matcher: Memulai pencarian masal untuk User ID {user_id}...")
        
        # 1. Dekode string JSON langsung menjadi 1 array numpy (128 dimensi)
        buyer_vector = np.array(json.loads(buyer_vector_json))
        
        all_event_faces = FaceEmbedding.query.all()
        
        THRESHOLD = 0.5 
        match_count = 0
        
        for face in all_event_faces:
            db_vector = np.array(face.get_embedding_array())
            
            # 2. Langsung hitung jarak Euclidean-nya
            distance = np.linalg.norm(buyer_vector - db_vector)
            
            # 3. Jika cocok, langsung catat
            if distance < THRESHOLD:
                # Cek agar tidak terjadi duplikasi jika sistem me-run ulang
                existing_match = FaceMatch.query.filter_by(user_id=user_id, photo_id=face.photo_id).first()
                
                if not existing_match:
                    new_match = FaceMatch(
                        user_id=user_id,
                        photo_id=face.photo_id,
                        match_score=float(distance),
                        is_confirmed=True 
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