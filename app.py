from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from database import db
from models import Student, Subject, StudentSubject, Class, Teacher, Timetable, StudentTimetable, Attendance, TeacherSubject
from sqlalchemy import func
import os
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from face_recog import FaceService
from pathlib import Path

# Use dynamic imports so the code runs even if optional packages are not installed
import importlib

# dotenv: load environment variables from a .env file when available
try:
	dotenv_mod = importlib.import_module('dotenv')
	load_dotenv = getattr(dotenv_mod, 'load_dotenv', lambda: None)
except Exception:
	def load_dotenv():
		return None

load_dotenv()

# Optional Supabase client (used to upload student photos to Supabase Storage)
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
SUPABASE_PHOTO_BUCKET = os.getenv('SUPABASE_PHOTO_BUCKET', 'student_photos')
supabase = None
if SUPABASE_URL and SUPABASE_KEY:
	try:
		supabase_mod = importlib.import_module('supabase')
		create_client = getattr(supabase_mod, 'create_client', None)
		if create_client:
			supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
	except Exception:
		supabase = None

UPLOAD_DIR = os.path.join(os.getcwd(), 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

DEFAULT_CLASSES = ["CSE-A", "CSE-B", "ECE-A", "ECE-B", "EE"]

face_service = FaceService(supabase_client=supabase)


def save_photo_file(upload, identifier: str) -> str | None:
	if not upload or not upload.filename:
		return None
	fname = secure_filename(f"{identifier}_{upload.filename}")
	full_path = os.path.join(UPLOAD_DIR, fname)
	upload.save(full_path)
	return f"/uploads/{fname}"

app = Flask(__name__)
# Configure database from environment variable
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///attendance.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'secretkey')  # needed for forms & flash messages

# Initialize the database
db.init_app(app)
migrate = Migrate(app, db)

def reset_sequence(table_name):
    """Reset the sequence for a table to the max ID + 1"""
    try:
        if db.engine.dialect.name == 'postgresql':
            db.session.execute(f"""
                SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), 
                COALESCE((SELECT MAX(id) FROM "{table_name}"), 1), true);
            """)
            db.session.commit()
    except Exception as e:
        print(f"Warning: Could not reset sequence for {table_name}. Error: {str(e)}")
        db.session.rollback()

with app.app_context():
    try:
        # Create tables only if they don't exist (preserves existing data)
        db.create_all()
        
        # Reset sequences for all tables
        if db.engine.dialect.name == 'postgresql':
            reset_sequence('classes')
            reset_sequence('students')
            reset_sequence('subjects')
            reset_sequence('teachers')
            reset_sequence('teacher_subjects')
            reset_sequence('student_subjects')
            reset_sequence('timetables')
            reset_sequence('student_timetables')
            reset_sequence('attendance')
        
        # Initialize default classes if they don't exist
        existing_classes = {c.name for c in Class.query.all()}
        for cname in DEFAULT_CLASSES:
            if cname not in existing_classes:
                try:
                    db.session.add(Class(name=cname))
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    print(f"Warning: Could not add class {cname}. It may already exist. Error: {str(e)}")
        
        # Create a default admin user if it doesn't exist
        if not Teacher.query.filter_by(email='admin@school.com').first():
            try:
                admin = Teacher(
                    name='Admin',
                    email='admin@school.com',
                    password_hash=generate_password_hash('admin123')
                )
                db.session.add(admin)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"Warning: Could not create admin user. Error: {str(e)}")
    except Exception as e:
        print(f"Warning: Database initialization error: {str(e)}")
        db.session.rollback()


@app.route('/')
def home():
	return render_template("base.html")


@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
	return send_from_directory(UPLOAD_DIR, filename)


# Login choice
@app.route('/login')
def login_choice():
	return render_template('login_choice.html')


# Attendance page (webcam)
@app.route('/attendance', methods=['GET', 'POST'])
def attendance_page():
	if request.method == 'POST':
		code = request.form.get('code', '')
		if code != 'ADMIN':
			flash('Invalid access code.', 'error')
			return render_template('attendance.html', show_code_form=True)
		session['attendance_authorized'] = True
		return render_template('attendance.html', show_code_form=False)
	
	# Check if already authorized
	if session.get('attendance_authorized'):
		return render_template('attendance.html', show_code_form=False)
	
	return render_template('attendance.html', show_code_form=True)


# Register choice
@app.route('/register')
def register_choice():
	return render_template('register_choice.html')


# Student Registration
@app.route('/register/student', methods=["GET", "POST"])
def register_student():
	if request.method == "POST":
		name = request.form["name"]
		roll_no = request.form["roll_no"]
		email = request.form.get("email")
		parent_email = request.form.get("parent_email")
		phone = request.form.get("phone")
		password = request.form["password"]
		class_id = request.form.get("class_id") or None
		photo = request.files.get("photo")
		if not photo or not photo.filename:
			flash("Passport photo is required.", "error")
			classes = Class.query.all()
			return render_template("register.html", classes=classes)

		photo_path = save_photo_file(photo, roll_no)

		student = Student(
			name=name,
			roll_no=roll_no,
			email=email,
			parent_email=parent_email,
			phone=phone,
			password_hash=generate_password_hash(password),
			class_id=class_id,
			photo_path=photo_path,
		)

		try:
			db.session.add(student)
			db.session.commit()

			# Get all core subjects
			core_subjects = Subject.query.filter_by(is_core=True).all()
			
			# Add only non-existing student-subject relationships
			for subj in core_subjects:
				try:
					# Check if the relationship already exists
					existing = StudentSubject.query.filter_by(
						student_id=student.id,
						subject_id=subj.id
					).first()
					if not existing:
						db.session.add(StudentSubject(student_id=student.id, subject_id=subj.id))
						db.session.commit()
				except Exception as e:
					db.session.rollback()
					# If we get a unique violation, the relationship already exists
					if 'unique' not in str(e).lower():
						raise

			# Enroll face embedding if we have a photo
			if photo_path:
				# Enroll using the local saved file (photo_path is like "/uploads/...")
				face_service.enroll_from_path(photo_path, student.id)

				# Try to upload the saved photo to Supabase Storage (if configured)
				if supabase is not None:
					try:
						# Map served path to filesystem path
						local_path = os.path.join(os.getcwd(), photo_path.lstrip('/'))
						if os.path.exists(local_path):
							with open(local_path, 'rb') as fd:
								data = fd.read()
							# Use student id as filename to avoid collisions
							remote_name = f"{student.id}.jpg"
							# upload; some supabase clients accept bytes
							supabase.storage.from_(SUPABASE_PHOTO_BUCKET).upload(remote_name, data)
							# Obtain public URL for the uploaded object
							pub = supabase.storage.from_(SUPABASE_PHOTO_BUCKET).get_public_url(remote_name)
							public_url = None
							if isinstance(pub, dict):
								public_url = pub.get('publicURL') or pub.get('public_url') or pub.get('publicUrl')
							if public_url:
								student.photo_path = public_url
								db.session.commit()
					except Exception as _e:
						# Non-fatal: keep local file and enrollment, but inform admin
						flash(f"Photo uploaded locally but failed to upload to Supabase: {_e}", 'warning')

				# Also upsert the student row to Supabase (so new registrations appear there)
				if supabase is not None:
					try:
						payload = {
							'id': int(student.id),
							'name': student.name,
							'roll_no': student.roll_no,
							'email': student.email,
							'parent_email': student.parent_email,
							'phone': student.phone,
							'photo_path': student.photo_path,
							'class_id': student.class_id,
						}
						# Upsert by primary key 'id' so manual rows are preserved and new ones added
						supabase.table('students').upsert(payload).execute()
					except Exception:
						# non-fatal
						pass

			flash("Student registered successfully! Please set up Subjects, Teachers, and Timetable.", "success")
			return redirect(url_for("subjects"))
		except Exception as e:
			db.session.rollback()
			flash(f"An error occurred during registration: {str(e)}", "error")

	# Handle GET request
	classes = Class.query.all()
	return render_template("register.html", classes=classes)


# Teacher Registration (ADMIN code required)
@app.route('/register/teacher', methods=['GET', 'POST'])
def register_teacher():
	if request.method == 'POST':
		admin_code = request.form.get('admin_code')
		if admin_code != 'ADMIN':
			flash('You cannot register as teacher. Invalid code.', 'error')
			return redirect(url_for('register_teacher'))
		name = request.form['name']
		email = request.form.get('email')
		password = request.form['password']
		db.session.add(Teacher(name=name, email=email, password_hash=generate_password_hash(password)))
		db.session.commit()
		flash('Teacher registered successfully. You can login now.', 'success')
		return redirect(url_for('login_teacher'))
	return render_template('register_teacher.html')


# Edit student timetable entries
@app.route('/student/<int:student_id>/timetable', methods=["GET", "POST"])
def edit_student_timetable(student_id: int):
    student = Student.query.get_or_404(student_id)
    if request.method == 'POST':
        weekday = int(request.form['weekday'])
        subject_id = int(request.form['subject_id'])
        start_time = request.form['start_time']
        end_time = request.form['end_time']
        
        # Check for overlapping time slots
        overlapping = StudentTimetable.query.filter(
            StudentTimetable.student_id == student.id,
            StudentTimetable.weekday == weekday,
            (
                (StudentTimetable.start_time <= start_time < StudentTimetable.end_time) |
                (StudentTimetable.start_time < end_time <= StudentTimetable.end_time) |
                ((start_time <= StudentTimetable.start_time) & (end_time >= StudentTimetable.end_time))
            )
        ).first()
        
        if overlapping:
            flash('This time slot overlaps with an existing entry', 'error')
        else:
            entry = StudentTimetable(
                student_id=student.id,
                subject_id=subject_id,
                weekday=weekday,
                start_time=start_time,
                end_time=end_time,
            )
            db.session.add(entry)
            db.session.commit()
            flash('Timetable entry added successfully', 'success')
        
        return redirect(url_for('edit_student_timetable', student_id=student.id))
    
    subjects = Subject.query.all()
    # Order by weekday and then by start time
    rows = StudentTimetable.query.filter_by(
        student_id=student.id
    ).order_by(
        StudentTimetable.weekday,
        StudentTimetable.start_time
    ).all()
    
    # Create a dictionary to organize timetable by day
    timetable_by_day = {i: [] for i in range(7)}  # 0-6 for Monday-Sunday
    for entry in rows:
        timetable_by_day[entry.weekday].append(entry)
    
    # Sort each day's entries by start time
    for day in timetable_by_day:
        timetable_by_day[day] = sorted(timetable_by_day[day], key=lambda x: x.start_time)
    
    return render_template(
        'student_timetable.html',
        student=student,
        subjects=subjects,
        rows=rows,
        timetable_by_day=timetable_by_day
    )


# Student timetable view (for logged-in students)
@app.route('/dashboard/student/timetable', methods=['GET', 'POST'])
def student_timetable_view():
	student_id = session.get('student_id')
	if not student_id:
		return redirect(url_for('login_student'))
	
	student = Student.query.get_or_404(student_id)
	
	# Handle edit/delete
	if request.method == 'POST':
		action = request.form.get('action')
		if action == 'add':
			weekday = int(request.form['weekday'])
			subject_id = int(request.form['subject_id'])
			start_time = request.form['start_time']
			end_time = request.form['end_time']
			entry = StudentTimetable(
				student_id=student.id,
				subject_id=subject_id,
				weekday=weekday,
				start_time=start_time,
				end_time=end_time,
			)
			db.session.add(entry)
			db.session.commit()
			flash('Timetable entry added successfully!', 'success')
		elif action == 'delete':
			entry_id = int(request.form['entry_id'])
			entry = StudentTimetable.query.filter_by(id=entry_id, student_id=student_id).first()
			if entry:
				db.session.delete(entry)
				db.session.commit()
				flash('Timetable entry deleted successfully!', 'success')
		elif action == 'update':
			entry_id = int(request.form['entry_id'])
			entry = StudentTimetable.query.filter_by(id=entry_id, student_id=student_id).first()
			if entry:
				entry.weekday = int(request.form['weekday'])
				entry.subject_id = int(request.form['subject_id'])
				entry.start_time = request.form['start_time']
				entry.end_time = request.form['end_time']
				db.session.commit()
				flash('Timetable entry updated successfully!', 'success')
		return redirect(url_for('student_timetable_view'))
	
	# Get student's subjects
	student_subjects = db.session.query(Subject).join(
		StudentSubject, Subject.id == StudentSubject.subject_id
	).filter(StudentSubject.student_id == student_id).all()
	
	rows = StudentTimetable.query.filter_by(student_id=student.id).order_by(StudentTimetable.weekday, StudentTimetable.start_time).all()
	return render_template('student_timetable_view.html', student=student, subjects=student_subjects, rows=rows)


# Subjects CRUD
@app.route('/subjects', methods=["GET", "POST"])
def subjects():
	if request.method == "POST":
		name = request.form["subject_name"]
		is_core = True if request.form.get("is_core") == "on" else False
		is_elective = True if request.form.get("is_elective") == "on" else False
		db.session.add(Subject(subject_name=name, is_core=is_core, is_elective=is_elective))
		db.session.commit()
		flash("Subject added successfully!", "success")
		return redirect(url_for('subjects'))
	subs = Subject.query.all()
	return render_template('subjects.html', subjects=subs)


@app.route('/classes', methods=["GET", "POST"])
def classes():
	if request.method == "POST":
		name = request.form["name"]
		db.session.add(Class(name=name))
		db.session.commit()
		return redirect(url_for('classes'))
	classes = Class.query.all()
	return render_template('classes.html', classes=classes)


@app.route('/teachers', methods=["GET", "POST"])
def teachers():
	if request.method == "POST":
		name = request.form["name"]
		subject_id = int(request.form["subject_id"])
		# Create teacher with default password (can be changed later)
		teacher = Teacher(name=name, email=None, password_hash=generate_password_hash('default123'))
		db.session.add(teacher)
		db.session.flush()  # Get the teacher ID
		# Link teacher to subject
		teacher_subject = TeacherSubject(teacher_id=teacher.id, subject_id=subject_id)
		db.session.add(teacher_subject)
		db.session.commit()
		flash("Teacher added successfully!", "success")
		return redirect(url_for('teachers'))
	
	# Get all teacher-subject relationships
	teacher_subjects = db.session.query(
		Teacher.name.label('teacher_name'),
		Subject.subject_name.label('subject_name')
	).join(TeacherSubject, Teacher.id == TeacherSubject.teacher_id).join(
		Subject, TeacherSubject.subject_id == Subject.id
	).all()
	
	subjects = Subject.query.all()
	return render_template('teachers.html', teacher_subjects=teacher_subjects, subjects=subjects)


@app.route('/timetable', methods=["GET", "POST"])
def timetable():
	if request.method == "POST":
		class_id = int(request.form["class_id"])
		subject_id = int(request.form["subject_id"])
		teacher_id = request.form.get("teacher_id")
		weekday = int(request.form["weekday"])  # 0..6
		start_time = request.form["start_time"]
		end_time = request.form["end_time"]
		entry = Timetable(
			class_id=class_id,
			subject_id=subject_id,
			teacher_id=int(teacher_id) if teacher_id else None,
			weekday=weekday,
			start_time=start_time,
			end_time=end_time,
		)
		db.session.add(entry)
		db.session.commit()
		return redirect(url_for('timetable'))
	classes = Class.query.all()
	subjects = Subject.query.all()
	teachers = Teacher.query.all()
	rows = Timetable.query.all()
	return render_template('timetable.html', classes=classes, subjects=subjects, teachers=teachers, rows=rows)


# Auth: student
@app.route('/login/student', methods=['GET', 'POST'])
def login_student():
	if request.method == 'POST':
		roll_no = request.form['roll_no']
		password = request.form['password']
		st = Student.query.filter_by(roll_no=roll_no).first()
		if st and check_password_hash(st.password_hash, password):
			session['student_id'] = st.id
			return redirect(url_for('student_dashboard'))
		flash('Invalid credentials', 'error')
	return render_template('login_student.html')


@app.route('/login/teacher', methods=['GET', 'POST'])
def login_teacher():
	if request.method == 'POST':
		name = request.form.get('name', '').strip()
		password = request.form.get('password', '').strip()
		
		# Check if a teacher with this name exists
		teacher = Teacher.query.filter(Teacher.name.ilike(f'%{name}%')).first()
		
		# Common password check (case-insensitive)
		if teacher and password.upper() == 'ADMIN':
			session['teacher_id'] = teacher.id
			return redirect(url_for('teacher_dashboard'))
			
		# Don't reveal that the name exists or not, just show invalid credentials
		flash('Invalid credentials', 'error')
	return render_template('login_teacher.html')


@app.route('/logout')
def logout():
	session.clear()
	return redirect(url_for('home'))


# Attendance recognition endpoint
@app.post('/attendance/recognize')
def attendance_recognize():
	if not session.get('attendance_authorized'):
		return jsonify({'error': 'unauthorized'}), 403

	files = request.files.getlist('file')
	if not files:
		return jsonify({'error': 'no file(s)'}), 400

	try:
		import cv2
		import numpy as np
	except ImportError:
		return jsonify({'error': 'opencv-python not installed'}), 500

	# Process multiple frames (client should send several frames) and require
	# a majority agreement to accept a match (reduces false positives).
	preds = []
	for f in files:
		data = f.read()
		npimg = np.frombuffer(data, np.uint8)
		img = cv2.imdecode(npimg, cv2.IMREAD_COLOR)
		if img is None:
			continue
		pid = face_service.predict_student_id(img)
		preds.append(pid)

	# Determine majority vote
	from collections import Counter
	if not preds:
		flash('No valid frames received', 'error')
		return jsonify({'student_id': None, 'message': 'bad image frames'})

	cnt = Counter(preds)
	# Most common predicted id and its count
	best_id, best_count = cnt.most_common(1)[0]
	# require majority (over half of frames) and not None
	if best_id is None or best_count <= (len(preds) // 2):
		flash('No face match found (inconsistent frames)', 'error')
		return jsonify({'student_id': None, 'message': 'face not recognized'})

	student_id = best_id

	# Get student info
	student = Student.query.get(student_id)
	if not student:
		flash('Student not found', 'error')
		return jsonify({'error': 'student not found'}), 404

	# Determine current class/subject from student's personal timetable
	now = datetime.now()
	weekday = now.weekday()  # 0..6
	now_str = now.strftime('%H:%M')

	# Get all timetable entries for today, ordered by time
	rows = StudentTimetable.query.filter_by(
		student_id=student_id,
		weekday=weekday
	).order_by(
		StudentTimetable.start_time
	).all()

	subject_id = None
	current_subject = None

	# Find the current time slot
	for r in rows:
		if r.start_time <= now_str <= r.end_time:
			subject_id = r.subject_id
			current_subject = Subject.query.get(subject_id)
			break

	if subject_id and current_subject:
		# Check if attendance is already marked for this subject today
		existing = Attendance.query.filter(
			Attendance.student_id == student_id,
			Attendance.subject_id == subject_id,
			func.date(Attendance.timestamp) == now.date()
		).first()

		if not existing:
			# Mark attendance
			att = Attendance(
				student_id=student_id,
				subject_id=subject_id,
				class_id=student.class_id,
				timestamp=now,
				is_present=True,
				method='face'
			)
			db.session.add(att)
			db.session.commit()
			# Also insert into Supabase attendance table (if configured)
			if supabase is not None:
				try:
					payload = {
						'id': int(att.id),
						'student_id': int(att.student_id),
						'subject_id': att.subject_id,
						'class_id': att.class_id,
						'timestamp': att.timestamp.isoformat(),
						'is_present': bool(att.is_present),
						'method': att.method,
					}
					supabase.table('attendance').upsert(payload).execute()
				except Exception:
					pass
			flash(f'Attendance marked for {student.name} in {current_subject.subject_name}', 'success')
			return jsonify({
				'student_id': student_id,
				'student_name': student.name,
				'subject_id': subject_id,
				'subject_name': current_subject.subject_name,
				'message': 'attendance marked'
			})
		else:
			flash(f'Attendance already marked for {student.name} in {current_subject.subject_name}', 'info')
			return jsonify({
				'student_id': student_id,
				'student_name': student.name,
				'subject_id': subject_id,
				'subject_name': current_subject.subject_name,
				'message': 'attendance already marked'
			})
	else:
		# No matching time slot
		flash(f'No matching class found for {student.name} at this time', 'warning')
		return jsonify({
			'student_id': student_id,
			'student_name': student.name,
			'subject_id': None,
			'message': 'no matching class'
		})


@app.route('/attendance/get-subjects')
def get_student_subjects():
	if not session.get('attendance_authorized'):
		return jsonify({'error': 'unauthorized'}), 403
	student_id = request.args.get('student_id', type=int)
	if not student_id:
		return jsonify({'error': 'student_id required'}), 400
	
	subjects = db.session.query(Subject).join(
		StudentSubject, Subject.id == StudentSubject.subject_id
	).filter(StudentSubject.student_id == student_id).all()
	
	return jsonify({
		'subjects': [{'id': s.id, 'name': s.subject_name} for s in subjects]
	})


@app.post('/attendance/manual')
def manual_attendance():
	if not session.get('attendance_authorized'):
		return jsonify({'error': 'unauthorized'}), 403
	student_id = request.form.get('student_id', type=int)
	day = request.form.get('day', type=int)
	subject_id = request.form.get('subject_id', type=int)
	
	if not all([student_id, day is not None, subject_id]):
		return jsonify({'success': False, 'error': 'Missing required fields'}), 400
	
	try:
		att = Attendance(
			student_id=student_id,
			subject_id=subject_id,
			class_id=None,
			timestamp=datetime.now(),
			is_present=True,
			method='manual'
		)
		db.session.add(att)
		db.session.commit()
		# Also push manual attendance to Supabase when available
		if supabase is not None:
			try:
				payload = {
					'id': int(att.id),
					'student_id': int(att.student_id),
					'subject_id': att.subject_id,
					'class_id': att.class_id,
					'timestamp': att.timestamp.isoformat(),
					'is_present': bool(att.is_present),
					'method': att.method,
				}
				supabase.table('attendance').upsert(payload).execute()
			except Exception:
				pass
		return jsonify({'success': True, 'message': 'Attendance marked successfully'})
	except Exception as e:
		db.session.rollback()
		return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/dashboard/student')
def student_dashboard():
	student_id = session.get('student_id')
	if not student_id:
		return redirect(url_for('login_student'))
	st = Student.query.get(student_id)
	# Get student's subjects
	student_subjects = db.session.query(Subject).join(
		StudentSubject, Subject.id == StudentSubject.subject_id
	).filter(StudentSubject.student_id == student_id).all()
	
	# overall
	total = Attendance.query.filter_by(student_id=student_id).count()
	present = Attendance.query.filter_by(student_id=student_id, is_present=True).count()
	absent = total - present
	
	# per-subject stats
	per_subject = []
	for s in student_subjects:
		st_total = Attendance.query.filter_by(student_id=student_id, subject_id=s.id).count()
		st_present = Attendance.query.filter_by(student_id=student_id, subject_id=s.id, is_present=True).count()
		st_absent = st_total - st_present
		if st_total > 0:
			pct = round(100.0 * st_present / st_total, 1)
		else:
			pct = 0
		per_subject.append({
			'id': s.id,
			'name': s.subject_name, 
			'present': st_present, 
			'absent': st_absent,
			'total': st_total, 
			'percent': pct
		})
	return render_template('dashboard_student.html', student=st, total=total, present=present, absent=absent, per_subject=per_subject)


@app.route('/dashboard/student/profile', methods=['GET', 'POST'])
def student_profile():
	student_id = session.get('student_id')
	if not student_id:
		return redirect(url_for('login_student'))
	st = Student.query.get_or_404(student_id)
	if request.method == 'POST':
		# Check if this is a profile update (not a delete request)
		if 'delete' not in request.form:
			st.name = request.form.get('name', st.name)
			st.email = request.form.get('email')
			st.parent_email = request.form.get('parent_email')
			st.phone = request.form.get('phone')
			class_id = request.form.get('class_id')
			st.class_id = int(class_id) if class_id else None
			new_photo = request.files.get('photo')
			if new_photo and new_photo.filename:
				photo_path = save_photo_file(new_photo, st.roll_no)
				if photo_path:
					st.photo_path = photo_path
					face_service.enroll_from_path(photo_path, st.id)
			db.session.commit()
			# Also upsert updated student to Supabase when configured
			if supabase is not None:
				try:
					payload = {
						'id': int(st.id),
						'name': st.name,
						'roll_no': st.roll_no,
						'email': st.email,
						'parent_email': st.parent_email,
						'phone': st.phone,
						'photo_path': st.photo_path,
						'class_id': st.class_id,
					}
					supabase.table('students').upsert(payload).execute()
				except Exception:
					pass
			flash('Profile updated successfully.', 'success')
			return redirect(url_for('student_profile'))
	classes = Class.query.all()
	return render_template('student_profile.html', student=st, classes=classes)


@app.route('/dashboard/student/profile/delete', methods=['POST'])
def delete_student_profile():
	student_id = session.get('student_id')
	if not student_id:
		flash('You must be logged in to delete your profile.', 'error')
		return redirect(url_for('login_student'))
	
	st = Student.query.get_or_404(student_id)
	
	try:
		# Delete all related records
		# 1. Delete StudentSubject records
		StudentSubject.query.filter_by(student_id=student_id).delete()
		
		# 2. Delete StudentTimetable records
		StudentTimetable.query.filter_by(student_id=student_id).delete()
		
		# 3. Delete Attendance records
		Attendance.query.filter_by(student_id=student_id).delete()
		
		# 4. Delete face embedding file (local) and remove from Supabase table if present
		emb_file = Path('data/embeddings') / f'{student_id}.npy'
		if emb_file.exists():
			emb_file.unlink()
		if supabase is not None:
			try:
				# remove embedding row(s) for this student
				supabase.table('face_embeddings').delete().eq('student_id', student_id).execute()
			except Exception:
				pass
		
		# 5. Delete photo file
		if st.photo_path:
			# photo_path is like "/uploads/filename.jpg"
			photo_file = os.path.join(os.getcwd(), st.photo_path.lstrip('/'))
			if os.path.exists(photo_file):
				os.remove(photo_file)
		
		# 6. Delete the student record
		db.session.delete(st)
		db.session.commit()
		# Also delete student row from Supabase (if configured)
		if supabase is not None:
			try:
				# delete student row
				supabase.table('students').delete().eq('id', student_id).execute()
				# try to delete photo from storage as well
				try:
					remote_name = f"{student_id}.jpg"
					supabase.storage.from_(SUPABASE_PHOTO_BUCKET).remove([remote_name])
				except Exception:
					pass
			except Exception:
				pass
		
		# Clear session
		session.clear()
		
		flash('Your profile has been permanently deleted.', 'success')
		return redirect(url_for('home'))
	except Exception as e:
		db.session.rollback()
		flash(f'An error occurred while deleting your profile: {str(e)}', 'error')
		return redirect(url_for('student_profile'))


@app.route('/dashboard/teacher')
def teacher_dashboard():
	teacher_id = session.get('teacher_id')
	if not teacher_id:
		return redirect(url_for('login_teacher'))
	students = Student.query.all()
	return render_template('dashboard_teacher.html', students=students)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
