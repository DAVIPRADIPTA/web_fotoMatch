import os
import re
from google.oauth2 import service_account
from googleapiclient.discovery import build

class GDriveService:
    def __init__(self):
        # Arahkan ke file JSON yang tadi kamu download
        self.creds_path = os.path.join(os.path.dirname(__file__), '../../gdrive_credentials.json')
        self.scopes = ['https://www.googleapis.com/auth/drive.readonly']
        
        self.creds = service_account.Credentials.from_service_account_file(
            self.creds_path, scopes=self.scopes
        )
        self.service = build('drive', 'v3', credentials=self.creds)

    def extract_folder_id(self, url):
        """Mengekstrak ID folder dari URL Google Drive yang disetor user"""
        match = re.search(r'folders/([\w-]+)', url)
        return match.group(1) if match else None

    def list_photos(self, folder_id):
        """Mengambil daftar semua file foto (.jpg atau .png) di dalam folder"""
        query = f"'{folder_id}' in parents and (mimeType = 'image/jpeg' or mimeType = 'image/png') and trashed = false"
        
        results = self.service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, webContentLink, thumbnailLink)"
        ).execute()
        
        return results.get('files', [])

# Inisialisasi agar bisa dipakai di tempat lain
gdrive_service = GDriveService()