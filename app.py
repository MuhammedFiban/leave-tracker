from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from datetime import date, datetime
from functools import wraps
from models import db, Employee, LeaveRequest
from utils import count_calendar_days, accrued_days_up_to
from dotenv import load_dotenv, set_key
import os

load_dotenv()

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key-change-in-production')
db.init_app(app)

with app.app_context():
    db.create_all()

# ---------- Admin credentials from .env ----------
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')
if not ADMIN_EMAIL or not ADMIN_PASSWORD:
    raise ValueError("ADMIN_EMAIL and ADMIN_PASSWORD must be set in .env")

# ---------- Login required decorator ----------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ---------- Authentication routes (simple) ----------
@app.route('/')
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username == ADMIN_EMAIL and password == ADMIN_PASSWORD:
            session['logged_in'] = True
            session['username'] = username
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error="Invalid credentials.")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html',
                           username=session.get('username'),
                           current_year=date.today().year)

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    global ADMIN_EMAIL, ADMIN_PASSWORD
    dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
    if request.method == 'POST':
        new_email = request.form.get('email')
        new_password = request.form.get('password')
        if not new_email or not new_password:
            return render_template('settings.html', error="Both fields are required.", current_email=ADMIN_EMAIL)
        set_key(dotenv_path, 'ADMIN_EMAIL', new_email)
        set_key(dotenv_path, 'ADMIN_PASSWORD', new_password)
        load_dotenv(dotenv_path, override=True)
        ADMIN_EMAIL = os.getenv('ADMIN_EMAIL')
        ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')
        session.clear()
        return redirect(url_for('login'))
    return render_template('settings.html', current_email=ADMIN_EMAIL)

# ---------- API endpoints ----------
@app.route('/api/employees')
@login_required
def api_employees():
    today = date.today()
    employees = Employee.query.all()
    emp_ids = [e.id for e in employees]
    # Sum of taken days across all years (cumulative)
    taken_dict = dict(
        db.session.query(
            LeaveRequest.employee_id,
            db.func.sum(LeaveRequest.working_days)
        )
        .filter(LeaveRequest.employee_id.in_(emp_ids))
        .group_by(LeaveRequest.employee_id)
        .all()
    )
    result = []
    for emp in employees:
        taken = taken_dict.get(emp.id, 0.0) or 0.0
        accrued = accrued_days_up_to(emp.join_date, today)   # cumulative from join date
        remaining = max(0.0, accrued - taken)
        additional = max(0.0, taken - accrued)
        result.append({
            "id": emp.id,
            "name": emp.name,
            "joinDate": emp.join_date.isoformat(),
            "accrued": round(accrued, 1),
            "taken": round(taken, 1),
            "remaining": round(remaining, 1),
            "additional": round(additional, 1)
        })
    return jsonify(result)

@app.route('/api/leaves')
@login_required
def api_leaves():
    leaves = LeaveRequest.query.order_by(LeaveRequest.created_at.desc()).all()
    out = []
    for l in leaves:
        emp = Employee.query.get(l.employee_id)
        out.append({
            "id": l.id,
            "employeeId": l.employee_id,
            "employeeName": emp.name if emp else "Unknown",
            "startDate": l.start_date.isoformat(),
            "endDate": l.end_date.isoformat(),
            "days": l.working_days,
            "year": l.year,
            "createdAt": l.created_at.isoformat() if l.created_at else None
        })
    return jsonify(out)

@app.route('/api/leaves', methods=['POST'])
@login_required
def add_leave():
    data = request.json
    if not data or 'employeeId' not in data or 'startDate' not in data or 'endDate' not in data:
        return jsonify({"error": "Missing required fields"}), 400
    try:
        emp_id = int(data['employeeId'])
        start = datetime.strptime(data['startDate'], '%Y-%m-%d').date()
        end = datetime.strptime(data['endDate'], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400
    if start > end:
        return jsonify({"error": "End date before start date"}), 400
    if start.year != end.year:
        return jsonify({"error": "Leave cannot cross calendar years"}), 400
    days = count_calendar_days(start, end)
    if days == 0:
        return jsonify({"error": "Invalid date range"}), 400
    # No overlap check – overlapping leaves are allowed
    new_leave = LeaveRequest(
        employee_id=emp_id,
        start_date=start,
        end_date=end,
        working_days=days,
        year=start.year
    )
    db.session.add(new_leave)
    db.session.commit()
    return jsonify({"message": "Leave recorded", "id": new_leave.id}), 201

@app.route('/api/leaves/<int:leave_id>', methods=['DELETE'])
@login_required
def delete_leave(leave_id):
    leave = LeaveRequest.query.get(leave_id)
    if not leave:
        return jsonify({"error": "Not found"}), 404
    db.session.delete(leave)
    db.session.commit()
    return jsonify({"message": "Deleted"})

@app.route('/api/notifications')
@login_required
def notifications():
    today = date.today()
    active = LeaveRequest.query.filter(LeaveRequest.start_date <= today, LeaveRequest.end_date >= today).all()
    result = []
    for l in active:
        emp = Employee.query.get(l.employee_id)
        result.append({
            "employeeName": emp.name,
            "startDate": l.start_date.isoformat(),
            "endDate": l.end_date.isoformat(),
            "days": l.working_days,
            "startedToday": (l.start_date == today)
        })
    return jsonify(result)

@app.route('/api/employees', methods=['POST'])
@login_required
def add_employee():
    data = request.json
    if not data or 'name' not in data or 'joinDate' not in data:
        return jsonify({"error": "Missing name or joinDate"}), 400
    try:
        name = data['name'].strip()
        join_date = datetime.strptime(data['joinDate'], '%Y-%m-%d').date()
    except ValueError:
        return jsonify({"error": "Invalid date format for joinDate"}), 400
    existing = Employee.query.filter_by(name=name).first()
    if existing:
        return jsonify({"error": f"Employee with name '{name}' already exists."}), 400
    emp = Employee(name=name, join_date=join_date)
    db.session.add(emp)
    db.session.commit()
    return jsonify({"id": emp.id, "message": "Employee added"}), 201

@app.route('/api/employees/<int:emp_id>', methods=['DELETE'])
@login_required
def delete_employee(emp_id):
    employee = Employee.query.get(emp_id)
    if not employee:
        return jsonify({"error": "Employee not found"}), 404
    name = employee.name
    db.session.delete(employee)
    db.session.commit()
    return jsonify({"message": f"Employee {name} deleted successfully"}), 200

@app.route('/api/count-days')
@login_required
def count_days_preview():
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    if not start_str or not end_str:
        return jsonify({"error": "Missing start or end date"}), 400
    try:
        start = datetime.strptime(start_str, '%Y-%m-%d').date()
        end = datetime.strptime(end_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({"error": "Invalid date format"}), 400
    days = count_calendar_days(start, end)
    return jsonify({"days": days})

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)