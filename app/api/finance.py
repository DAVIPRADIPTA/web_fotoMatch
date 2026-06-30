from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.extensions import db
from app.models import User, Order, OrderItem, Photo, EventAlbum, Withdrawal
from decimal import Decimal

api_finance_bp = Blueprint('api_finance', __name__)

@api_finance_bp.route('/wallet', methods=['GET'])
@jwt_required()
def get_wallet():
    """
    Informasi Dompet & Riwayat Penarikan Dana (Kreator)
    ---
    tags:
      - Keuangan
    security:
      - Bearer: []
    responses:
      200:
        description: Berhasil mengambil informasi dompet
      404:
        description: User tidak ditemukan
      500:
        description: Internal Server Error
    """
    try:
        current_user_id = get_jwt_identity()
        if isinstance(current_user_id, int) or str(current_user_id).isdigit():
            user = User.query.get(int(current_user_id))
        else:
            user = User.query.filter_by(email=current_user_id).first()

        if not user:
            return jsonify({"status": "error", "message": "User tidak ditemukan."}), 404

        # 1. Hitung total uang masuk (pendapatan) secara dinamis
        # Foto Digital: Order.payment_status in ('paid', 'completed')
        digital_revenue = db.session.query(db.func.sum(OrderItem.subtotal))\
            .join(Photo, OrderItem.photo_id == Photo.id)\
            .join(EventAlbum, Photo.album_id == EventAlbum.id)\
            .join(Order, OrderItem.order_id == Order.id)\
            .filter(EventAlbum.photographer_id == user.id)\
            .filter(OrderItem.purchase_type == 'digital')\
            .filter(Order.payment_status.in_(['paid', 'completed']))\
            .scalar()

        # Foto Fisik: Order.payment_status == 'completed'
        physical_revenue = db.session.query(db.func.sum(OrderItem.subtotal))\
            .join(Photo, OrderItem.photo_id == Photo.id)\
            .join(EventAlbum, Photo.album_id == EventAlbum.id)\
            .join(Order, OrderItem.order_id == Order.id)\
            .filter(EventAlbum.photographer_id == user.id)\
            .filter(OrderItem.purchase_type == 'physical')\
            .filter(Order.payment_status == 'completed')\
            .scalar()

        total_revenue = (float(digital_revenue) if digital_revenue is not None else 0.0) + \
                        (float(physical_revenue) if physical_revenue is not None else 0.0)

        # 2. Hitung total uang keluar (penarikan dana)
        # SUM(amount) dari Withdrawal
        # filter: photographer_id == user.id DAN status IN ('pending', 'success')
        withdrawal_query = db.session.query(db.func.sum(Withdrawal.amount))\
            .filter(Withdrawal.photographer_id == user.id)\
            .filter(Withdrawal.status.in_(['pending', 'success']))\
            .scalar()

        total_withdrawn = float(withdrawal_query) if withdrawal_query is not None else 0.0

        # 3. Hitung saldo aktif
        active_balance = total_revenue - total_withdrawn

        # 4. Ambil riwayat penarikan dana
        withdrawals = Withdrawal.query.filter_by(photographer_id=user.id)\
            .order_by(Withdrawal.created_at.desc())\
            .all()

        withdrawals_list = []
        for w in withdrawals:
            withdrawals_list.append({
                "id": w.id,
                "amount": float(w.amount),
                "bank_name": w.bank_name,
                "account_number": w.account_number,
                "account_name": w.account_name,
                "status": w.status.value if hasattr(w.status, 'value') else w.status,
                "created_at": w.created_at.isoformat() if w.created_at else None,
                "updated_at": w.updated_at.isoformat() if w.updated_at else None
            })

        return jsonify({
            "status": "success",
            "message": "Berhasil mengambil informasi dompet.",
            "data": {
                "saldo_aktif": active_balance,
                "total_pendapatan": total_revenue,
                "withdrawals": withdrawals_list
            }
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": f"Gagal memproses informasi dompet: {str(e)}"}), 500


@api_finance_bp.route('/withdraw', methods=['POST'])
@jwt_required()
def request_withdrawal():
    """
    Pengajuan Penarikan Dana (Withdrawal)
    ---
    tags:
      - Keuangan
    security:
      - Bearer: []
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - amount
            - bank_name
            - account_number
            - account_name
          properties:
            amount:
              type: number
              description: Jumlah dana yang ingin ditarik
              example: 100000
            bank_name:
              type: string
              description: Nama bank tujuan
              example: "BCA"
            account_number:
              type: string
              description: Nomor rekening tujuan
              example: "1234567890"
            account_name:
              type: string
              description: Nama pemilik rekening
              example: "Davi Pradipta"
    responses:
      201:
        description: Pengajuan penarikan dana berhasil diajukan
      400:
        description: Saldo tidak mencukupi atau input tidak lengkap
      404:
        description: User tidak ditemukan
      500:
        description: Internal Server Error
    """
    current_user_id = get_jwt_identity()
    try:
        if isinstance(current_user_id, int) or str(current_user_id).isdigit():
            user = User.query.get(int(current_user_id))
        else:
            user = User.query.filter_by(email=current_user_id).first()

        if not user:
            return jsonify({"status": "error", "message": "User tidak ditemukan."}), 404

        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "Request body tidak boleh kosong."}), 400

        amount_val = data.get('amount')
        bank_name = data.get('bank_name')
        account_number = data.get('account_number')
        account_name = data.get('account_name')

        if not all([amount_val, bank_name, account_number, account_name]):
            return jsonify({"status": "error", "message": "Semua field (amount, bank_name, account_number, account_name) wajib diisi."}), 400

        try:
            amount = Decimal(str(amount_val))
            if amount <= 0:
                raise ValueError()
        except Exception:
            return jsonify({"status": "error", "message": "Jumlah penarikan harus berupa angka positif."}), 400

        # 1. Hitung saldo aktif saat ini
        # Foto Digital: Order.payment_status in ('paid', 'completed')
        digital_revenue = db.session.query(db.func.sum(OrderItem.subtotal))\
            .join(Photo, OrderItem.photo_id == Photo.id)\
            .join(EventAlbum, Photo.album_id == EventAlbum.id)\
            .join(Order, OrderItem.order_id == Order.id)\
            .filter(EventAlbum.photographer_id == user.id)\
            .filter(OrderItem.purchase_type == 'digital')\
            .filter(Order.payment_status.in_(['paid', 'completed']))\
            .scalar()

        # Foto Fisik: Order.payment_status == 'completed'
        physical_revenue = db.session.query(db.func.sum(OrderItem.subtotal))\
            .join(Photo, OrderItem.photo_id == Photo.id)\
            .join(EventAlbum, Photo.album_id == EventAlbum.id)\
            .join(Order, OrderItem.order_id == Order.id)\
            .filter(EventAlbum.photographer_id == user.id)\
            .filter(OrderItem.purchase_type == 'physical')\
            .filter(Order.payment_status == 'completed')\
            .scalar()

        total_revenue_digital = Decimal(str(digital_revenue)) if digital_revenue is not None else Decimal('0.00')
        total_revenue_physical = Decimal(str(physical_revenue)) if physical_revenue is not None else Decimal('0.00')
        total_revenue = total_revenue_digital + total_revenue_physical

        withdrawal_query = db.session.query(db.func.sum(Withdrawal.amount))\
            .filter(Withdrawal.photographer_id == user.id)\
            .filter(Withdrawal.status.in_(['pending', 'success']))\
            .scalar()

        total_withdrawn = Decimal(str(withdrawal_query)) if withdrawal_query is not None else Decimal('0.00')

        active_balance = total_revenue - total_withdrawn

        # 2. Validasi saldo mencukupi
        if amount > active_balance:
            return jsonify({"status": "error", "message": "Saldo tidak mencukupi."}), 400

        # 3. Buat entri penarikan baru
        new_withdrawal = Withdrawal(
            photographer_id=user.id,
            amount=amount,
            bank_name=bank_name,
            account_number=account_number,
            account_name=account_name,
            status='pending'
        )
        db.session.add(new_withdrawal)
        db.session.commit()

        return jsonify({
            "status": "success",
            "message": "Pengajuan penarikan dana berhasil diajukan dengan status pending.",
            "data": {
                "id": new_withdrawal.id,
                "amount": float(new_withdrawal.amount),
                "status": "pending"
            }
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": f"Gagal mengajukan penarikan dana: {str(e)}"}), 500
