from flask import Blueprint, request, jsonify
from app.extensions import db
from app.models import User
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    
    if User.query.filter_by(email=data.get('email')).first():
        return jsonify({"message": "Email sudah terdaftar"}), 400
    
    hashed_password = generate_password_hash(data.get('password'), method='pbkdf2:sha256')
    
    new_user = User(
        name=data.get('name'),
        email=data.get('email'),
        password=hashed_password,
        role=data.get('role', 'buyer')
    )
    
    db.session.add(new_user)
    db.session.commit()
    
    access_token = create_access_token(identity=str(new_user.id))
    
    return jsonify({
        "message": "User berhasil dibuat",
        "access_token": access_token,
        "role": new_user.role
    }), 201

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    user = User.query.filter_by(email=data.get('email')).first()
    
    if not user or not check_password_hash(user.password, data.get('password')):
        return jsonify({"message": "Email atau password salah"}), 401
    
    access_token = create_access_token(identity=str(user.id))
    
    return jsonify({
        "message": "Login berhasil",
        "access_token": access_token,
        "user": {
            "name": user.name,
            "email": user.email,
            "role": user.role
        }
    }), 200

@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def me():
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    return jsonify({
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role
    }), 200