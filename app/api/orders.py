import uuid
# pyrefly: ignore [missing-import]
from flask import Blueprint, request, jsonify, current_app
# pyrefly: ignore [missing-import]
from flask_jwt_extended import get_jwt_identity, jwt_required
# pyrefly: ignore [missing-import]
import midtransclient
import requests
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import joinedload
from app.extensions import db
from app.models import User, Order, OrderItem, Shipping, Photo, EventAlbum

# Pastikan Blueprint sudah didefinisikan di atas jika belum ada
api_orders_bp = Blueprint('api_orders', __name__)

@api_orders_bp.route('/check-ongkir', methods=['POST'])
@jwt_required()
def check_ongkir():
    """
    Cek Harga Ongkos Kirim (Integrasi Biteship)
    ---
    tags:
      - Transaksi & Order
    security:
      - Bearer: []
    parameters:
      - in: body
        name: body
        schema:
          type: object
          required:
            - photographer_id
            - destination_postal_code
            - total_weight_gram
          properties:
            photographer_id:
              type: integer
              description: ID User (Fotografer) untuk mengambil kode pos asal
              example: 17
            destination_postal_code:
              type: string
              description: Kode pos alamat pembeli
              example: "40115"
            total_weight_gram:
              type: integer
              description: Total berat layanan cetak fisik & bingkai (dalam gram)
              example: 1500
    responses:
      200:
        description: Berhasil mendapatkan daftar layanan dan harga ongkir dari berbagai kurir
      400:
        description: Bad Request (Data tidak lengkap atau gagal dari Biteship)
      500:
        description: Internal Server Error
    """
    data = request.get_json()

    photographer_id = data.get('photographer_id')
    destination_postal_code = data.get('destination_postal_code')
    weight = data.get('total_weight_gram', 1000)

    if not all([photographer_id, destination_postal_code, weight]):
        return jsonify({"status": "error", "message": "ID Fotografer, kode pos tujuan, dan berat wajib diisi."}), 400

    try:
        # 1. Cari data fotografer untuk mendapatkan kode pos asalnya
        photographer = User.query.get(photographer_id)
        
        # PERHATIAN: Pastikan di model User-mu sudah ada kolom postal_code
        if not photographer or not getattr(photographer, 'postal_code', None):
            return jsonify({
                "status": "error", 
                "message": "Fotografer ini belum mengatur kode pos asalnya. Tidak dapat menghitung ongkir."
            }), 400
            
        origin_postal_code = photographer.postal_code

        # 2. Siapkan request ke server Biteship
        url = "https://api.biteship.com/v1/rates/couriers"
        
        headers = {
            "Authorization": f"Bearer {current_app.config['BITESHIP_API_KEY']}",
            "Content-Type": "application/json"
        }

        # 3. Format body JSON sesuai standar dokumentasi Biteship
        payload = {
            "origin_postal_code": str(origin_postal_code),
            "destination_postal_code": str(destination_postal_code),
            "couriers": "jne,sicepat,pos,jnt,anteraja", # Memanggil banyak kurir sekaligus
            "items": [
                {
                    "name": "Cetak Foto Frame",
                    "description": "Layanan cetak fisik FotoMatch",
                    "value": 50000, # Estimasi nilai barang untuk asuransi (bisa dinamis nantinya)
                    "length": 10, 
                    "width": 10, 
                    "height": 10, 
                    "weight": weight
                }
            ]
        }

        # 4. Tembak API Biteship (dengan timeout 10 detik)
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        
        # Tangkap balasan jika ternyata bukan JSON
        try:
            biteship_data = response.json()
        except Exception:
            return jsonify({
                "status": "error", 
                "message": f"Server Biteship membalas dengan format yang tidak dikenali. Status Code: {response.status_code}. Balasan Asli: {response.text}"
            }), 500

        # 5. Tangkap error resmi dari Biteship
        if response.status_code != 200:
            error_message = biteship_data.get('error', 'Gagal mendapatkan data ongkir dari Biteship')
            return jsonify({"status": "error", "message": f"Biteship Error: {error_message}"}), 400

        # 6. Susun dan kembalikan data
        return jsonify({
            "status": "success",
            "message": "Berhasil menghitung ongkir",
            "data": {
                "origin_postal_code": origin_postal_code,
                "destination_postal_code": destination_postal_code,
                "services": biteship_data.get('pricing', []) # Array yang berisi list harga dari JNE, Sicepat, dll
            }
        }), 200

    except requests.exceptions.Timeout:
        return jsonify({"status": "error", "message": "Server Biteship terlalu lama merespon (Timeout). Coba lagi nanti."}), 504
    except Exception as e:
        return jsonify({"status": "error", "message": f"Gagal mengecek ongkir: {str(e)}"}), 500
    
@api_orders_bp.route('/checkout', methods=['POST'])
@jwt_required()
def checkout():
    """
    Checkout Pesanan & Generate Link Pembayaran Midtrans
    ---
    tags:
      - Transaksi & Order
    summary: "Membuat pesanan baru dan menghasilkan URL pembayaran Midtrans"
    security:
      - Bearer: []
    parameters:
      - in: body
        name: body
        description: Data untuk melakukan checkout
        required: true
        schema:
          type: object
          required:
            - photographer_id
            - item_price
            - shipping_cost
          properties:
            photographer_id:
              type: integer
              description: ID fotografer yang dipilih
              example: 17
            item_price:
              type: integer
              description: Harga total barang/jasa cetak (dalam Rupiah)
              example: 50000
            shipping_cost:
              type: integer
              description: Harga ongkos kirim dari Biteship (dalam Rupiah)
              example: 34000
            destination_address:
              type: string
              description: Alamat tujuan pengiriman (jika ada cetak fisik)
              example: "Jl. Dipati Ukur No. 123, Bandung"
            courier_name:
              type: string
              description: Nama kurir yang dipilih
              example: "JNE - Reguler"
            items:
              type: array
              description: Daftar foto yang dibeli
              items:
                type: object
                required:
                  - photo_id
                  - purchase_type
                  - subtotal
                properties:
                  photo_id:
                    type: integer
                  purchase_type:
                    type: string
                    enum: [digital, physical]
                  subtotal:
                    type: integer
    responses:
      200:
        description: Berhasil membuat transaksi dan mengembalikan URL Midtrans Snap
      400:
        description: Bad Request (Data tidak lengkap)
      500:
        description: Internal Server Error (Gagal menghubungi Midtrans)
    """
    data = request.get_json()
    
    item_price = data.get('item_price', 0)
    shipping_cost = data.get('shipping_cost', 0)
    photographer_id = data.get('photographer_id')

    total_amount = item_price + shipping_cost
    
    # Generate Order ID unik
    order_id = f"FM-ORDER-{str(uuid.uuid4())[:8]}"

    try:
        # 1. Ambil identitas dari JWT
        current_user_identity = get_jwt_identity()
        
        # Coba cari user. Jika identity berupa angka (ID), pakai query.get. Jika string, pakai filter_by.
        if isinstance(current_user_identity, int) or str(current_user_identity).isdigit():
            buyer = User.query.get(int(current_user_identity))
        else:
            buyer = User.query.filter_by(email=current_user_identity).first()
        
        if not buyer:
            return jsonify({"status": "error", "message": "Pembeli tidak ditemukan."}), 404

        # 2. VALIDASI EMAIL KETAT UNTUK MIDTRANS
        safe_email = "customer@fotomatch.com" # Email cadangan
        if buyer.email and "@" in buyer.email:
            safe_email = buyer.email
        elif isinstance(current_user_identity, str) and "@" in current_user_identity:
            safe_email = current_user_identity

        # 3. Transaksi Database - Simpan Draft Order
        new_order = Order(
            order_number=order_id,
            buyer_id=buyer.id,
            photographer_id=photographer_id,
            total_price=total_amount,
            payment_status='unpaid'
        )
        db.session.add(new_order)
        db.session.flush()  # Dapatkan id baru untuk relasi items dan shipping

        # Simpan Order Items jika ada
        order_items_input = data.get('items', [])
        for item in order_items_input:
            photo_id = item.get('photo_id')
            purchase_type = item.get('purchase_type', 'digital')
            subtotal = item.get('subtotal', 0)

            # Validasi keberadaan foto
            photo = Photo.query.get(photo_id)
            if not photo:
                db.session.rollback()
                return jsonify({"status": "error", "message": f"Foto dengan ID {photo_id} tidak ditemukan"}), 400

            order_item = OrderItem(
                order_id=new_order.id,
                photo_id=photo_id,
                purchase_type=purchase_type,
                subtotal=subtotal
            )
            db.session.add(order_item)

        # Simpan Shipping jika ada pengiriman fisik atau ongkos kirim
        destination_address = data.get('destination_address')
        courier_name = data.get('courier_name', 'Default Courier')
        if shipping_cost > 0 or destination_address:
            shipping = Shipping(
                order_id=new_order.id,
                courier_name=courier_name,
                shipping_cost=shipping_cost,
                destination_address=destination_address or "Alamat tidak ditentukan",
                shipping_status='pending'
            )
            db.session.add(shipping)

        # 4. Inisialisasi Midtrans Snap Client
        snap = midtransclient.Snap(
            is_production=False, 
            server_key=current_app.config['MIDTRANS_SERVER_KEY']
        )
        
        # 5. Siapkan Parameter Transaksi (Payload untuk Midtrans)
        param = {
            "transaction_details": {
                "order_id": order_id,
                "gross_amount": total_amount
            },
            "customer_details": {
                "first_name": buyer.name,
                "email": safe_email,
            },
            "item_details": [
                {
                    "id": "ITEM-1",
                    "price": item_price,
                    "quantity": 1,
                    "name": "Layanan Cetak & Foto"
                }
            ]
        }

        if shipping_cost > 0:
            param["item_details"].append({
                "id": "ONGKIR-1",
                "price": shipping_cost,
                "quantity": 1,
                "name": "Ongkos Kirim"
            })

        # 6. Tembak API Midtrans
        transaction = snap.create_transaction(param)
        redirect_url = transaction['redirect_url']
        token = transaction['token']

        # Update order dengan Midtrans token
        new_order.midtrans_transaction_id = token

        # Commit transaksi
        db.session.commit()

        return jsonify({
            "status": "success",
            "message": "Berhasil membuat pesanan",
            "data": {
                "order_id": order_id,
                "total_amount": total_amount,
                "payment_url": redirect_url, 
                "payment_token": token
            }
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": f"Gagal membuat pembayaran Midtrans: {str(e)}"}), 500
    
@api_orders_bp.route('/midtrans-webhook', methods=['POST'])
def midtrans_webhook():
    """
    Midtrans Payment Notification Webhook
    ---
    tags:
      - Transaksi & Order
    summary: "Callback otomatis dari Midtrans untuk memperbarui status transaksi"
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            order_id:
              type: string
              example: "FM-ORDER-bb0924c0"
            transaction_status:
              type: string
              example: "settlement"
            fraud_status:
              type: string
              example: "accept"
    responses:
      200:
        description: Webhook berhasil diproses dan status database diperbarui
      400:
        description: Bad Request (Payload tidak valid)
      500:
        description: Internal Server Error
    """
    try:
        # 1. Ambil data notifikasi dari Midtrans
        notification = request.get_json()
        
        if not notification:
            return jsonify({"status": "error", "message": "Payload kosong"}), 400

        # 2. Inisialisasi Midtrans CoreApi (BUKAN Snap) untuk Webhook
        core_api = midtransclient.CoreApi(
            is_production=False,
            server_key=current_app.config['MIDTRANS_SERVER_KEY']
        )
        
        # Validasi menggunakan CoreApi agar aman dari manipulasi data (data tampering)
        status_response = core_api.transactions.notification(notification)
        
        order_id = status_response.get('order_id')
        transaction_status = status_response.get('transaction_status')
        fraud_status = status_response.get('fraud_status')

        print(f"--- NOTIFIKASI MASUK ---")
        print(f"Order ID: {order_id}")
        print(f"Status Transaksi: {transaction_status}")
        print(f"Fraud Status: {fraud_status}")
        print(f"-------------------------")

        # 3. Logika Pemetaan Status Pembayaran Midtrans ke Enum Database
        db_status = 'unpaid'
        if transaction_status == 'capture':
            if fraud_status == 'challenge':
                db_status = 'unpaid'
            elif fraud_status == 'accept':
                db_status = 'paid'
        elif transaction_status == 'settlement':
            db_status = 'paid'
        elif transaction_status == 'pending':
            db_status = 'unpaid'
        elif transaction_status in ['deny', 'cancel']:
            db_status = 'failed'
        elif transaction_status == 'expire':
            db_status = 'expired'

        # 4. Update status ke database
        order = Order.query.filter_by(order_number=order_id).first()
        if order:
            order.payment_status = db_status
            if status_response.get('transaction_id'):
                order.midtrans_transaction_id = status_response.get('transaction_id')
            
            # Update status pengiriman jika sudah lunas
            if db_status == 'paid':
                for shipping in order.shippings:
                    shipping.shipping_status = 'processing'

            db.session.commit()
            print(f"Mengubah status Order {order_id} di database menjadi: {db_status}")
        else:
            print(f"Order {order_id} tidak ditemukan di database.")

        return jsonify({
            "status": "success",
            "message": f"Status order {order_id} berhasil diperbarui menjadi {db_status}"
        }), 200

    except Exception as e:
        db.session.rollback()
        print(f"Webhook Error: {str(e)}")
        return jsonify({"status": "error", "message": f"Gagal memproses webhook: {str(e)}"}), 500

@api_orders_bp.route('/history/buyer', methods=['GET'])
@jwt_required()
def get_buyer_history():
    """
    Riwayat Pesanan Pembeli
    ---
    tags:
      - Transaksi & Order
    security:
      - Bearer: []
    responses:
      200:
        description: Berhasil mengambil riwayat pesanan pembeli
      500:
        description: Internal Server Error
    """
    try:
        current_user_identity = get_jwt_identity()
        if isinstance(current_user_identity, int) or str(current_user_identity).isdigit():
            buyer = User.query.get(int(current_user_identity))
        else:
            buyer = User.query.filter_by(email=current_user_identity).first()

        if not buyer:
            return jsonify({"status": "error", "message": "User tidak ditemukan"}), 404

        # Eager load items, photo, shippings, dan photographer untuk menghindari N+1 query
        orders = Order.query.filter_by(buyer_id=buyer.id)\
            .options(
                joinedload(Order.items).joinedload(OrderItem.photo),
                joinedload(Order.shippings),
                joinedload(Order.photographer)
            )\
            .order_by(Order.created_at.desc())\
            .all()

        orders_list = []
        for order in orders:
            shipping_info = None
            if order.shippings:
                ship = order.shippings[0]
                shipping_info = {
                    "courier_name": ship.courier_name,
                    "shipping_cost": ship.shipping_cost,
                    "tracking_number": ship.tracking_number,
                    "destination_address": ship.destination_address,
                    "shipping_status": ship.shipping_status.value if hasattr(ship.shipping_status, 'value') else ship.shipping_status
                }

            items_list = []
            for item in order.items:
                photo_info = None
                if item.photo:
                    photo_info = {
                        "id": item.photo.id,
                        "file_name": item.photo.file_name,
                        "preview_path": item.photo.preview_path,
                        "original_path": item.photo.original_path
                    }
                items_list.append({
                    "id": item.id,
                    "photo_id": item.photo_id,
                    "purchase_type": item.purchase_type.value if hasattr(item.purchase_type, 'value') else item.purchase_type,
                    "subtotal": item.subtotal,
                    "photo": photo_info
                })

            orders_list.append({
                "id": order.id,
                "order_number": order.order_number,
                "photographer": {
                    "id": order.photographer.id,
                    "name": order.photographer.name,
                    "email": order.photographer.email
                } if order.photographer else None,
                "midtrans_transaction_id": order.midtrans_transaction_id,
                "total_price": order.total_price,
                "payment_status": order.payment_status.value if hasattr(order.payment_status, 'value') else order.payment_status,
                "payment_type": order.payment_type,
                "created_at": order.created_at.isoformat() if order.created_at else None,
                "items": items_list,
                "shipping": shipping_info
            })

        return jsonify({
            "status": "success",
            "message": "Berhasil mengambil riwayat pesanan pembeli",
            "data": orders_list
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": f"Gagal mengambil riwayat pembeli: {str(e)}"}), 500

@api_orders_bp.route('/history/creator', methods=['GET'])
@jwt_required()
def get_creator_history():
    """
    Riwayat Penjualan Kreator (Fotografer)
    ---
    tags:
      - Transaksi & Order
    security:
      - Bearer: []
    responses:
      200:
        description: Berhasil mengambil riwayat penjualan fotografer
      500:
        description: Internal Server Error
    """
    try:
        current_user_identity = get_jwt_identity()
        if isinstance(current_user_identity, int) or str(current_user_identity).isdigit():
            creator = User.query.get(int(current_user_identity))
        else:
            creator = User.query.filter_by(email=current_user_identity).first()

        if not creator:
            return jsonify({"status": "error", "message": "User tidak ditemukan"}), 404

        # Eager load terkait Photo, Order, Shippings, dan Buyer dalam satu query JOIN yang efisien
        sales_items = db.session.query(OrderItem)\
            .join(Photo, OrderItem.photo_id == Photo.id)\
            .join(EventAlbum, Photo.album_id == EventAlbum.id)\
            .join(Order, OrderItem.order_id == Order.id)\
            .options(
                joinedload(OrderItem.photo),
                joinedload(OrderItem.order).joinedload(Order.shippings),
                joinedload(OrderItem.order).joinedload(Order.buyer)
            )\
            .filter(EventAlbum.photographer_id == creator.id)\
            .order_by(OrderItem.created_at.desc())\
            .all()

        sales_list = []
        for item in sales_items:
            order = item.order
            
            shipping_info = None
            if order and order.shippings:
                ship = order.shippings[0]
                shipping_info = {
                    "courier_name": ship.courier_name,
                    "shipping_cost": ship.shipping_cost,
                    "tracking_number": ship.tracking_number,
                    "destination_address": ship.destination_address,
                    "shipping_status": ship.shipping_status.value if hasattr(ship.shipping_status, 'value') else ship.shipping_status
                }

            photo_info = None
            if item.photo:
                photo_info = {
                    "id": item.photo.id,
                    "file_name": item.photo.file_name,
                    "preview_path": item.photo.preview_path,
                    "original_path": item.photo.original_path
                }

            sales_list.append({
                "order_item_id": item.id,
                "order_id": item.order_id,
                "order_number": order.order_number if order else None,
                "purchase_type": item.purchase_type.value if hasattr(item.purchase_type, 'value') else item.purchase_type,
                "subtotal": item.subtotal,
                "payment_status": order.payment_status.value if order and hasattr(order.payment_status, 'value') else (order.payment_status if order else None),
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "photo": photo_info,
                "buyer": {
                    "id": order.buyer.id,
                    "name": order.buyer.name,
                    "email": order.buyer.email
                } if order and order.buyer else None,
                "shipping": shipping_info
            })

        return jsonify({
            "status": "success",
            "message": "Berhasil mengambil riwayat penjualan fotografer",
            "data": sales_list
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": f"Gagal mengambil riwayat penjualan: {str(e)}"}), 500

@api_orders_bp.route('/<order_id>', methods=['GET'])
@jwt_required()
def get_order_detail(order_id):
    """
    Detail Pesanan Spesifik
    ---
    tags:
      - Transaksi & Order
    summary: "Mengambil detail lengkap pesanan spesifik"
    security:
      - Bearer: []
    parameters:
      - in: path
        name: order_id
        type: string
        required: true
        description: ID (integer) atau Nomor Order unik (FM-ORDER-xxxx)
    responses:
      200:
        description: Berhasil mengambil detail pesanan
      403:
        description: Forbidden (Bukan pembeli atau fotografer dari pesanan ini)
      404:
        description: Pesanan tidak ditemukan
      500:
        description: Internal Server Error
    """
    try:
        current_user_identity = get_jwt_identity()
        if isinstance(current_user_identity, int) or str(current_user_identity).isdigit():
            user = User.query.get(int(current_user_identity))
        else:
            user = User.query.filter_by(email=current_user_identity).first()

        if not user:
            return jsonify({"status": "error", "message": "User tidak ditemukan"}), 404

        # Cari berdasarkan id (integer) atau order_number (string)
        if order_id.isdigit():
            order = Order.query.filter((Order.id == int(order_id))).options(
                joinedload(Order.items).joinedload(OrderItem.photo),
                joinedload(Order.shippings),
                joinedload(Order.buyer),
                joinedload(Order.photographer)
            ).first()
        else:
            order = Order.query.filter((Order.order_number == order_id)).options(
                joinedload(Order.items).joinedload(OrderItem.photo),
                joinedload(Order.shippings),
                joinedload(Order.buyer),
                joinedload(Order.photographer)
            ).first()

        if not order:
            return jsonify({"status": "error", "message": "Order tidak ditemukan"}), 404

        # Validasi keamanan: Pastikan hanya pembeli (buyer) atau fotografer terkait yang bisa mengakses
        if order.buyer_id != user.id and order.photographer_id != user.id:
            return jsonify({"status": "error", "message": "Anda tidak memiliki akses ke pesanan ini."}), 403

        shipping_info = None
        if order.shippings:
            ship = order.shippings[0]
            shipping_info = {
                "courier_name": ship.courier_name,
                "shipping_cost": ship.shipping_cost,
                "tracking_number": ship.tracking_number,
                "destination_address": ship.destination_address,
                "shipping_status": ship.shipping_status.value if hasattr(ship.shipping_status, 'value') else ship.shipping_status
            }

        items_list = []
        for item in order.items:
            photo_info = None
            if item.photo:
                photo_info = {
                    "id": item.photo.id,
                    "file_name": item.photo.file_name,
                    "preview_path": item.photo.preview_path,
                    "original_path": item.photo.original_path
                }
            items_list.append({
                "id": item.id,
                "photo_id": item.photo_id,
                "purchase_type": item.purchase_type.value if hasattr(item.purchase_type, 'value') else item.purchase_type,
                "subtotal": item.subtotal,
                "photo": photo_info
            })

        order_data = {
            "id": order.id,
            "order_number": order.order_number,
            "buyer": {
                "id": order.buyer.id,
                "name": order.buyer.name,
                "email": order.buyer.email
            } if order.buyer else None,
            "photographer": {
                "id": order.photographer.id,
                "name": order.photographer.name,
                "email": order.photographer.email
            } if order.photographer else None,
            "midtrans_transaction_id": order.midtrans_transaction_id,
            "total_price": order.total_price,
            "payment_status": order.payment_status.value if hasattr(order.payment_status, 'value') else order.payment_status,
            "payment_type": order.payment_type,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "updated_at": order.updated_at.isoformat() if order.updated_at else None,
            "items": items_list,
            "shipping": shipping_info
        }

        return jsonify({
            "status": "success",
            "message": "Berhasil mendapatkan detail pesanan",
            "data": order_data
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": f"Gagal mendapatkan detail pesanan: {str(e)}"}), 500

@api_orders_bp.route('/<order_id>/complete', methods=['POST'])
@jwt_required()
def complete_order(order_id):
    """
    Selesaikan Pesanan
    ---
    tags:
      - Transaksi & Order
    summary: "Mengubah status pesanan menjadi completed oleh pembeli"
    security:
      - Bearer: []
    parameters:
      - in: path
        name: order_id
        type: string
        required: true
        description: ID (integer) atau Nomor Order unik (FM-ORDER-xxxx)
    responses:
      200:
        description: Pesanan berhasil diselesaikan
      400:
        description: Pesanan belum dibayar atau status tidak valid
      403:
        description: Forbidden (Bukan pemilik order)
      404:
        description: Pesanan tidak ditemukan
      500:
        description: Internal Server Error
    """
    try:
        current_user_identity = get_jwt_identity()
        if isinstance(current_user_identity, int) or str(current_user_identity).isdigit():
            user = User.query.get(int(current_user_identity))
        else:
            user = User.query.filter_by(email=current_user_identity).first()

        if not user:
            return jsonify({"status": "error", "message": "User tidak ditemukan"}), 404

        # Cari berdasarkan id (integer) atau order_number (string)
        if order_id.isdigit():
            order = Order.query.get(int(order_id))
        else:
            order = Order.query.filter_by(order_number=order_id).first()

        if not order:
            return jsonify({"status": "error", "message": "Order tidak ditemukan"}), 404

        # Validasi keamanan: Pastikan hanya pembeli (buyer_id) yang bisa menyelesaikan
        if order.buyer_id != user.id:
            return jsonify({"status": "error", "message": "Hanya pemilik pesanan yang dapat menyelesaikan pesanan ini."}), 403

        # Validasi status pembayaran: Harus sudah 'paid'
        current_status = order.payment_status.value if hasattr(order.payment_status, 'value') else order.payment_status
        if current_status != 'paid':
            return jsonify({"status": "error", "message": "Pesanan belum dibayar atau tidak valid untuk diselesaikan."}), 400

        # Ubah status pesanan menjadi 'completed'
        order.payment_status = 'completed'
        
        # Juga update status pengiriman ke 'delivered' jika ada
        for shipping in order.shippings:
            shipping.shipping_status = 'delivered'

        db.session.commit()

        return jsonify({
            "status": "success",
            "message": "Pesanan berhasil diselesaikan.",
            "data": {
                "order_number": order.order_number,
                "payment_status": "completed"
            }
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": f"Gagal menyelesaikan pesanan: {str(e)}"}), 500

@api_orders_bp.route('/<order_id>/refresh-status', methods=['GET'])
@jwt_required()
def refresh_order_status(order_id):
    """
    Sinkronisasi Status Pesanan dengan Midtrans
    ---
    tags:
      - Transaksi & Order
    summary: "Memaksa aplikasi melakukan sinkronisasi status terbaru ke Midtrans"
    security:
      - Bearer: []
    parameters:
      - in: path
        name: order_id
        type: string
        required: true
        description: ID (integer) atau Nomor Order unik (FM-ORDER-xxxx)
    responses:
      200:
        description: Status pesanan berhasil disinkronisasi
      404:
        description: Pesanan tidak ditemukan
      500:
        description: Internal Server Error
    """
    try:
        # Cari berdasarkan id (integer) atau order_number (string)
        if order_id.isdigit():
            order = Order.query.get(int(order_id))
        else:
            order = Order.query.filter_by(order_number=order_id).first()

        if not order:
            return jsonify({"status": "error", "message": "Order tidak ditemukan"}), 404

        # Panggil Midtrans Snap SDK untuk cek status transaksi
        snap = midtransclient.Snap(
            is_production=False, 
            server_key=current_app.config['MIDTRANS_SERVER_KEY']
        )
        
        try:
            status_response = snap.transactions.status(order.order_number)
        except Exception as midtrans_error:
            return jsonify({
                "status": "error", 
                "message": f"Gagal mengambil status dari Midtrans: {str(midtrans_error)}"
            }), 400

        transaction_status = status_response.get('transaction_status')
        fraud_status = status_response.get('fraud_status')

        # Logika Pemetaan Status Pembayaran Midtrans ke Enum Database
        db_status = 'unpaid'
        if transaction_status == 'capture':
            if fraud_status == 'challenge':
                db_status = 'unpaid'
            elif fraud_status == 'accept':
                db_status = 'paid'
        elif transaction_status == 'settlement':
            db_status = 'paid'
        elif transaction_status == 'pending':
            db_status = 'unpaid'
        elif transaction_status in ['deny', 'cancel']:
            db_status = 'failed'
        elif transaction_status == 'expire':
            db_status = 'expired'

        # Jika ada status completed di database dan lokal kita sudah completed, jangan override dengan 'paid' dari midtrans
        current_status = order.payment_status.value if hasattr(order.payment_status, 'value') else order.payment_status
        if current_status == 'completed' and db_status == 'paid':
            db_status = 'completed'

        # Update database
        order.payment_status = db_status
        if status_response.get('transaction_id'):
            order.midtrans_transaction_id = status_response.get('transaction_id')

        # Update status pengiriman jika lunas
        if db_status == 'paid':
            for shipping in order.shippings:
                if shipping.shipping_status == 'pending':
                    shipping.shipping_status = 'processing'

        db.session.commit()

        return jsonify({
            "status": "success",
            "message": "Status pesanan berhasil disinkronisasi dengan Midtrans.",
            "data": {
                "order_number": order.order_number,
                "payment_status": db_status,
                "midtrans_status": transaction_status
            }
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": f"Gagal mensinkronisasi status: {str(e)}"}), 500

@api_orders_bp.route('/<order_id>/ship', methods=['POST'])
@jwt_required()
def ship_order(order_id):
    """
    Kirim Pesanan Fisik (Input Resi)
    ---
    tags:
      - Transaksi & Order
    summary: "Menginput nomor resi pengiriman dan mengubah status menjadi shipped oleh fotografer"
    security:
      - Bearer: []
    parameters:
      - in: path
        name: order_id
        type: string
        required: true
        description: ID (integer) atau Nomor Order unik (FM-ORDER-xxxx)
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - tracking_number
          properties:
            tracking_number:
              type: string
              description: Nomor resi kurir pengiriman
              example: "JNEX-9988776655"
    responses:
      200:
        description: Status pengiriman berhasil diperbarui menjadi shipped
      400:
        description: Pesanan tidak memerlukan pengiriman fisik
      403:
        description: Forbidden (Bukan fotografer dari pesanan ini)
      404:
        description: Pesanan tidak ditemukan
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

        # Cari berdasarkan id (integer) atau order_number (string)
        if order_id.isdigit():
            order = Order.query.get(int(order_id))
        else:
            order = Order.query.filter_by(order_number=order_id).first()

        if not order:
            return jsonify({"status": "error", "message": "Order tidak ditemukan."}), 404

        # Validasi keamanan: Pastikan hanya fotografer pemilik order yang bisa memproses
        if order.photographer_id != user.id:
            return jsonify({"status": "error", "message": "Hanya fotografer dari pesanan ini yang dapat melakukan pengiriman."}), 403

        data = request.get_json()
        if not data or not data.get('tracking_number'):
            return jsonify({"status": "error", "message": "Nomor resi (tracking_number) wajib diisi."}), 400

        tracking_number = data.get('tracking_number')

        # Ambil record shipping terkait
        shipping = Shipping.query.filter_by(order_id=order.id).first()
        if not shipping:
            return jsonify({"status": "error", "message": "Pesanan ini tidak memerlukan pengiriman fisik."}), 400

        # Update status pengiriman
        shipping.shipping_status = 'shipped'
        shipping.tracking_number = tracking_number

        db.session.commit()

        return jsonify({
            "status": "success",
            "message": "Status pengiriman berhasil diperbarui menjadi shipped.",
            "data": {
                "order_number": order.order_number,
                "shipping_status": "shipped",
                "tracking_number": tracking_number
            }
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": f"Gagal memproses pengiriman: {str(e)}"}), 500