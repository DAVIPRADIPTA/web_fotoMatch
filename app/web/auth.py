from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import firebase_admin.auth
from app.models import User
from app.extensions import db

web_auth_bp = Blueprint('web_auth', __name__)

@web_auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('web.select_event'))
    
    # Logic Login Manual
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('web.select_event'))
        
        flash('Email atau Password salah!', 'danger')
        
    return render_template('auth/login.html', firebase_config=current_app.config['FIREBASE_CONFIG'])

@web_auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        name = request.form.get('name')
        password = request.form.get('password')

        if User.query.filter_by(email=email).first():
            flash('Email sudah terdaftar!', 'warning')
            return redirect(url_for('web_auth.register'))

        new_user = User(
            name=name,
            email=email,
            password=generate_password_hash(password, method='pbkdf2:sha256'),
            role='photographer', # Default untuk web register
            auth_provider='manual'
        )
        db.session.add(new_user)
        db.session.commit()
        
        flash('Registrasi berhasil! Silakan login.', 'success')
        return redirect(url_for('web_auth.login'))

    return render_template('auth/register.html')

@web_auth_bp.route('/auth/firebase-verify', methods=['POST'])
def firebase_verify():
    data = request.get_json()
    id_token = data.get('idToken')

    if not id_token:
        return jsonify({'error': 'Token tidak ditemukan'}), 400

    try:
        # 1. Verifikasi token menggunakan Firebase Admin SDK
        # Ini akan mengecek apakah token tersebut benar-benar dari Google/Firebase
        decoded_token = firebase_admin.auth.verify_id_token(id_token)
        uid = decoded_token['uid']
        email = decoded_token.get('email')
        name = decoded_token.get('name', 'Fotografer')

        # 2. Cari user di database MySQL kita berdasarkan email
        user = User.query.filter_by(email=email).first()

        if not user:
            # Jika user belum terdaftar, buat akun baru otomatis (role fotografer)
            user = User(
                firebase_uid=uid,
                email=email,
                name=name,
                role='photographer',
                auth_provider='google'
            )
            db.session.add(user)
            db.session.commit()
            # Refresh agar kita mendapatkan ID yang baru saja digenerate MySQL
            db.session.refresh(user)
        else:
            # Jika user sudah ada tapi belum ada firebase_uid (pernah daftar manual)
            if not user.firebase_uid:
                user.firebase_uid = uid
                user.auth_provider = 'google'
                db.session.commit()

        # 3. KUNCI UTAMA: Membuat sesi login resmi di server (stempel satpam)
        # remember=True agar user tidak gampang ter-logout sendiri
        login_user(user, remember=True)

        # DEBUG: Muncul di terminal kamu saat login sukses
        print(f"DEBUG: Sukses login Google. User: {user.email}")

        return jsonify({
            'message': 'Login berhasil', 
            'redirect': url_for('web.select_event')
        }), 200

    except Exception as e:
        print(f"Error verifikasi Firebase: {e}")
        return jsonify({'error': 'Token tidak valid atau kadaluarsa'}), 401