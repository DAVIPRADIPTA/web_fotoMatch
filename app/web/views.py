from flask import Blueprint, render_template,request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models import Event,EventAlbum
from datetime import datetime
from app.extensions import db
from app.services.gdrive import gdrive_service
from flask import current_app
from app.services.processor import start_album_processing

# Inisialisasi Blueprint untuk rute-rute web dashboard
web_bp = Blueprint('web', __name__)


@web_bp.route('/fotografer/events')
@login_required
def select_event():
    # Ambil semua event
    events = Event.query.order_by(Event.event_date.desc()).all()
    
    # Ambil album milik fotografer yang sedang login saja
    my_albums = EventAlbum.query.filter_by(photographer_id=current_user.id).all()
    
    # Buat list berisi ID event yang sudah diikuti
    joined_event_ids = [album.event_id for album in my_albums]
    
    return render_template('fotografer/select_event.html', events=events, joined_event_ids=joined_event_ids)
@web_bp.route('/fotografer/events/new', methods=['GET', 'POST'])
@login_required
def create_event():
    if request.method == 'POST':
        title = request.form.get('title')
        category = request.form.get('category')
        event_date_str = request.form.get('event_date')
        location_name = request.form.get('location_name')

        try:
            # Ubah string tanggal dari form HTML menjadi objek Date Python
            event_date = datetime.strptime(event_date_str, '%Y-%m-%d').date()
            
            # Simpan ke tabel Event
            new_event = Event(
                title=title,
                category=category,
                event_date=event_date,
                location_name=location_name
            )
            db.session.add(new_event)
            db.session.commit()
            
            flash('Event berhasil dibuat! Silakan setor foto Anda.', 'success')
            return redirect(url_for('web.select_event'))
            
        except Exception as e:
            flash(f'Terjadi kesalahan saat menyimpan: {str(e)}', 'danger')
            db.session.rollback()

    return render_template('fotografer/create_event.html')

# --- FUNGSI BARU UNTUK INPUT LINK DRIVE ---
@web_bp.route('/fotografer/events/<int:event_id>/upload', methods=['GET', 'POST'])
@login_required
def upload_drive(event_id):
    # Cek apakah event-nya ada
    event = Event.query.get_or_404(event_id)
    
    # Cek apakah fotografer sudah pernah join event ini? Kalau sudah, tolak!
    existing_album = EventAlbum.query.filter_by(event_id=event_id, photographer_id=current_user.id).first()
    if existing_album:
        flash('Anda sudah menyetor foto untuk event ini!', 'warning')
        return redirect(url_for('web.select_event'))

    if request.method == 'POST':
        drive_link = request.form.get('drive_folder_link')
        price_digital = request.form.get('price_digital')
        # Checkbox akan bernilai True jika dicentang, False jika tidak
        allow_print = 'allow_physical_print' in request.form 

        try:
            # --- KODE TES GDRIVE ---
            folder_id = gdrive_service.extract_folder_id(drive_link)
            if folder_id:
                photos = gdrive_service.list_photos(folder_id)
                print(f"DEBUG: Berhasil menemukan {len(photos)} foto di Google Drive!")
            # -----------------------
            
            # Simpan ke tabel EventAlbum
            new_album = EventAlbum(
                event_id=event.id,
                photographer_id=current_user.id,
                drive_folder_link=drive_link,
                price_digital=int(price_digital),
                allow_physical_print=allow_print,
                status_ai='idle'
            )
            db.session.add(new_album)
            db.session.commit()
            
            # --- TRIGGGER BACKGROUND TASK DI SINI ---
            start_album_processing(current_app._get_current_object(), new_album.id)
            # ----------------------------------------
            
            flash('Link Google Drive berhasil disetor! AI akan segera memprosesnya.', 'success')
            return redirect(url_for('web.select_event'))

        except Exception as e:
            flash(f'Terjadi kesalahan: {str(e)}', 'danger')
            db.session.rollback()

    return render_template('fotografer/create_album.html', event=event)

