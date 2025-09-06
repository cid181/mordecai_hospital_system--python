from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import OperationalError, IntegrityError
import time
import sys
from config import SQLALCHEMY_DATABASE_URI, SECRET_KEY, DEBUG

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
app.config['DEBUG'] = DEBUG
app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# 数据模型
class Drug(db.Model):
    __tablename__ = 'drugs'
    drug_name = db.Column(db.String(100), primary_key=True)
    price = db.Column(db.Float)
    stock = db.Column(db.Integer)
    
    def to_dict(self):
        return {
            'drug_name': self.drug_name,
            'price': self.price,
            'stock': self.stock
        }

class Doctor(db.Model):
    __tablename__ = 'doctors'
    doctor_id = db.Column(db.String(100), primary_key=True)
    doctor_name = db.Column(db.String(100))
    
    def to_dict(self):
        return {
            'doctor_id': self.doctor_id,
            'doctor_name': self.doctor_name
        }

class Prescription(db.Model):
    __tablename__ = 'prescriptions'
    prescription_id = db.Column(db.String(100), primary_key=True)
    doctor_id = db.Column(db.String(100), db.ForeignKey('doctors.doctor_id'))
    total_fee = db.Column(db.Float, default=0)
    
    doctor = db.relationship('Doctor', backref=db.backref('prescriptions', lazy=True))
    
    def to_dict(self):
        return {
            'prescription_id': self.prescription_id,
            'doctor_id': self.doctor_id,
            'total_fee': self.total_fee
        }

class PrescriptionDetail(db.Model):
    __tablename__ = 'prescription_details'
    id = db.Column(db.Integer, primary_key=True)
    prescription_id = db.Column(db.String(100), db.ForeignKey('prescriptions.prescription_id'))
    drug_name = db.Column(db.String(100), db.ForeignKey('drugs.drug_name'))
    quantity = db.Column(db.Integer)
    price = db.Column(db.Float)
    
    prescription = db.relationship('Prescription', backref=db.backref('details', lazy=True))
    drug = db.relationship('Drug', backref=db.backref('prescription_details', lazy=True))
    
    def to_dict(self):
        return {
            'id': self.id,
            'prescription_id': self.prescription_id,
            'drug_name': self.drug_name,
            'quantity': self.quantity,
            'price': self.price
        }

# 带重试机制的数据库操作函数
def execute_with_retry(func, max_retries=3, delay=2):
    for attempt in range(max_retries):
        try:
            return func()
        except OperationalError as e:
            if "Lost connection to MySQL server" in str(e) and attempt < max_retries - 1:
                print(f"数据库连接丢失，尝试重新连接 ({attempt + 1}/{max_retries})...")
                time.sleep(delay)
                continue
            else:
                raise e
        except Exception as e:
            raise e

# 创建数据库表
@app.before_first_request
def create_tables():
    try:
        db.create_all()
        print("数据库表创建成功")
    except Exception as e:
        print(f"创建数据库表时出错: {e}")
        sys.exit(1)

# 错误处理
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': '资源未找到'}), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return jsonify({'error': '服务器内部错误'}), 500

# 前端页面
@app.route('/')
def index():
    return render_template('index.html')

# API路由 - 药品管理
@app.route('/api/drugs', methods=['GET'])
def get_drugs():
    def query_drugs():
        drugs = Drug.query.all()
        return jsonify([drug.to_dict() for drug in drugs])
    
    return execute_with_retry(query_drugs)

@app.route('/api/drugs', methods=['POST'])
def add_drug():
    data = request.get_json()
    
    def insert_drug():
        drug = Drug(
            drug_name=data['drug_name'],
            price=data['price'],
            stock=data['stock']
        )
        db.session.add(drug)
        db.session.commit()
        return jsonify({'message': '药品添加成功', 'drug': drug.to_dict()})
    
    try:
        return execute_with_retry(insert_drug)
    except IntegrityError:
        return jsonify({'error': '药品已存在'}), 400
    except Exception as e:
        return jsonify({'error': f'添加药品时发生错误: {str(e)}'}), 500

@app.route('/api/drugs/<drug_name>', methods=['GET'])
def get_drug(drug_name):
    def query_drug():
        drug = Drug.query.filter_by(drug_name=drug_name).first()
        if drug:
            return jsonify(drug.to_dict())
        return jsonify({'error': '药品不存在'}), 404
    
    return execute_with_retry(query_drug)

@app.route('/api/drugs/<drug_name>', methods=['PUT'])
def update_drug(drug_name):
    data = request.get_json()
    
    def update():
        drug = Drug.query.filter_by(drug_name=drug_name).first()
        if not drug:
            return jsonify({'error': '药品不存在'}), 404
        
        if 'price' in data:
            drug.price = data['price']
        if 'stock' in data:
            drug.stock = data['stock']
        
        db.session.commit()
        return jsonify({'message': '药品更新成功', 'drug': drug.to_dict()})
    
    return execute_with_retry(update)

@app.route('/api/drugs/<drug_name>', methods=['DELETE'])
def delete_drug(drug_name):
    def delete():
        drug = Drug.query.filter_by(drug_name=drug_name).first()
        if not drug:
            return jsonify({'error': '药品不存在'}), 404
        
        # 检查是否有处方明细关联到此药品
        details = PrescriptionDetail.query.filter_by(drug_name=drug_name).all()
        if details:
            return jsonify({
                'error': '无法删除药品，存在关联的处方明细',
                'detail_count': len(details)
            }), 400
        
        db.session.delete(drug)
        db.session.commit()
        return jsonify({'message': '药品删除成功'})
    
    return execute_with_retry(delete)

# API路由 - 医生管理
@app.route('/api/doctors', methods=['GET'])
def get_doctors():
    def query_doctors():
        doctors = Doctor.query.all()
        return jsonify([doctor.to_dict() for doctor in doctors])
    
    return execute_with_retry(query_doctors)

@app.route('/api/doctors', methods=['POST'])
def add_doctor():
    data = request.get_json()
    
    def insert_doctor():
        doctor = Doctor(
            doctor_id=data['doctor_id'],
            doctor_name=data['doctor_name']
        )
        db.session.add(doctor)
        db.session.commit()
        return jsonify({'message': '医生添加成功', 'doctor': doctor.to_dict()})
    
    try:
        return execute_with_retry(insert_doctor)
    except IntegrityError:
        return jsonify({'error': '医生ID已存在'}), 400
    except Exception as e:
        return jsonify({'error': f'添加医生时发生错误: {str(e)}'}), 500

@app.route('/api/doctors/<doctor_id>', methods=['GET'])
def get_doctor(doctor_id):
    def query_doctor():
        doctor = Doctor.query.filter_by(doctor_id=doctor_id).first()
        if doctor:
            return jsonify(doctor.to_dict())
        return jsonify({'error': '医生不存在'}), 404
    
    return execute_with_retry(query_doctor)

@app.route('/api/doctors/<doctor_id>', methods=['PUT'])
def update_doctor(doctor_id):
    data = request.get_json()
    
    def update():
        doctor = Doctor.query.filter_by(doctor_id=doctor_id).first()
        if not doctor:
            return jsonify({'error': '医生不存在'}), 404
        
        if 'doctor_name' in data:
            doctor.doctor_name = data['doctor_name']
        
        db.session.commit()
        return jsonify({'message': '医生更新成功', 'doctor': doctor.to_dict()})
    
    return execute_with_retry(update)

@app.route('/api/doctors/<doctor_id>', methods=['DELETE'])
def delete_doctor(doctor_id):
    def delete():
        doctor = Doctor.query.filter_by(doctor_id=doctor_id).first()
        if not doctor:
            return jsonify({'error': '医生不存在'}), 404
        
        # 检查是否有处方关联到此医生
        prescriptions = Prescription.query.filter_by(doctor_id=doctor_id).all()
        if prescriptions:
            return jsonify({
                'error': '无法删除医生，存在关联的处方',
                'prescription_count': len(prescriptions)
            }), 400
        
        db.session.delete(doctor)
        db.session.commit()
        return jsonify({'message': '医生删除成功'})
    
    return execute_with_retry(delete)

# API路由 - 处方管理
@app.route('/api/prescriptions', methods=['GET'])
def get_prescriptions():
    def query_prescriptions():
        prescriptions = Prescription.query.all()
        return jsonify([prescription.to_dict() for prescription in prescriptions])
    
    return execute_with_retry(query_prescriptions)

@app.route('/api/prescriptions', methods=['POST'])
def add_prescription():
    data = request.get_json()
    
    # 验证必需字段
    if not data.get('prescription_id'):
        return jsonify({'error': '处方ID不能为空'}), 400
    if not data.get('doctor_id'):
        return jsonify({'error': '医生ID不能为空'}), 400
    
    def insert_prescription():
        # 检查处方是否已存在
        existing_prescription = Prescription.query.filter_by(prescription_id=data['prescription_id']).first()
        if existing_prescription:
            return jsonify({'error': '处方ID已存在'}), 400
        
        # 检查医生是否存在
        doctor = Doctor.query.filter_by(doctor_id=data['doctor_id']).first()
        if not doctor:
            return jsonify({'error': '医生不存在'}), 400
        
        prescription = Prescription(
            prescription_id=data['prescription_id'],
            doctor_id=data['doctor_id']
        )
        db.session.add(prescription)
        db.session.commit()
        return jsonify({'message': '处方创建成功', 'prescription': prescription.to_dict()})
    
    try:
        return execute_with_retry(insert_prescription)
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'创建处方时发生错误: {str(e)}'}), 500

@app.route('/api/prescriptions/<prescription_id>', methods=['GET'])
def get_prescription(prescription_id):
    def query_prescription():
        prescription = Prescription.query.filter_by(prescription_id=prescription_id).first()
        if prescription:
            return jsonify(prescription.to_dict())
        return jsonify({'error': '处方不存在'}), 404
    
    return execute_with_retry(query_prescription)

@app.route('/api/prescriptions/<prescription_id>', methods=['DELETE'])
def delete_prescription(prescription_id):
    def delete():
        prescription = Prescription.query.filter_by(prescription_id=prescription_id).first()
        if not prescription:
            return jsonify({'error': '处方不存在'}), 404
        
        # 先删除相关的处方明细
        PrescriptionDetail.query.filter_by(prescription_id=prescription_id).delete()
        # 再删除处方
        db.session.delete(prescription)
        db.session.commit()
        return jsonify({'message': '处方删除成功'})
    
    return execute_with_retry(delete)

@app.route('/api/prescriptions/<prescription_id>/details', methods=['GET'])
def get_prescription_details(prescription_id):
    def query_details():
        details = PrescriptionDetail.query.filter_by(prescription_id=prescription_id).all()
        return jsonify([detail.to_dict() for detail in details])
    
    return execute_with_retry(query_details)

@app.route('/api/prescriptions/<prescription_id>/details', methods=['POST'])
def add_prescription_detail(prescription_id):
    data = request.get_json()
    
    # 验证必需字段
    if not data.get('drug_name'):
        return jsonify({'error': '药品名称不能为空'}), 400
    if not data.get('quantity') or data.get('quantity') <= 0:
        return jsonify({'error': '药品数量必须大于0'}), 400
    
    def insert_detail():
        # 检查处方是否存在
        prescription = Prescription.query.filter_by(prescription_id=prescription_id).first()
        if not prescription:
            return jsonify({'error': '处方不存在'}), 400
        
        # 检查药品是否存在
        drug = Drug.query.filter_by(drug_name=data['drug_name']).first()
        if not drug:
            return jsonify({'error': '药品不存在'}), 400
        
        # 检查库存是否足够
        if drug.stock < data['quantity']:
            return jsonify({'error': f'药品库存不足，当前库存: {drug.stock}'}), 400
        
        detail = PrescriptionDetail(
            prescription_id=prescription_id,
            drug_name=data['drug_name'],
            quantity=data['quantity'],
            price=drug.price
        )
        
        db.session.add(detail)
        
        # 更新药品库存
        drug.stock -= data['quantity']
        
        db.session.commit()
        return jsonify({'message': '处方明细添加成功', 'detail': detail.to_dict()})
    
    try:
        return execute_with_retry(insert_detail)
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'添加处方明细时发生错误: {str(e)}'}), 500

@app.route('/api/prescriptions/<prescription_id>/calculate', methods=['POST'])
def calculate_prescription(prescription_id):
    def calculate():
        prescription = Prescription.query.filter_by(prescription_id=prescription_id).first()
        if not prescription:
            return jsonify({'error': '处方不存在'}), 404
        
        details = PrescriptionDetail.query.filter_by(prescription_id=prescription_id).all()
        total_fee = sum(detail.quantity * detail.price for detail in details)
        
        prescription.total_fee = total_fee
        db.session.commit()
        return jsonify({'message': '处方总费用计算成功', 'total_fee': total_fee})
    
    return execute_with_retry(calculate)

if __name__ == '__main__':
    app.run(debug=DEBUG)