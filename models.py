from database import db


class Student(db.Model):
	__tablename__ = 'students'
	id = db.Column(db.Integer, primary_key=True)
	name = db.Column(db.String, nullable=False)
	roll_no = db.Column(db.String, unique=True, nullable=False)
	email = db.Column(db.String)
	parent_email = db.Column(db.String)
	phone = db.Column(db.String)
	photo_path = db.Column(db.String)
	password_hash = db.Column(db.String, nullable=False)
	class_id = db.Column(db.Integer, db.ForeignKey('classes.id'))


class Class(db.Model):
	__tablename__ = 'classes'
	id = db.Column(db.Integer, primary_key=True)
	name = db.Column(db.String, unique=True, nullable=False)


class Subject(db.Model):
	__tablename__ = 'subjects'
	id = db.Column(db.Integer, primary_key=True)
	subject_name = db.Column(db.String, nullable=False)
	is_core = db.Column(db.Boolean, default=False, nullable=False)
	is_elective = db.Column(db.Boolean, default=False, nullable=False)


class Teacher(db.Model):
	__tablename__ = 'teachers'
	id = db.Column(db.Integer, primary_key=True)
	name = db.Column(db.String, nullable=False)
	email = db.Column(db.String)
	password_hash = db.Column(db.String, nullable=False)


class TeacherSubject(db.Model):
	__tablename__ = 'teacher_subjects'
	id = db.Column(db.Integer, primary_key=True)
	teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=False)
	subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)


class StudentSubject(db.Model):
	__tablename__ = 'student_subjects'
	id = db.Column(db.Integer, primary_key=True)
	student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
	subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)


class Timetable(db.Model):
	__tablename__ = 'timetables'
	id = db.Column(db.Integer, primary_key=True)
	class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
	subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
	teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'))
	weekday = db.Column(db.Integer, nullable=False)  # 0=Mon ... 6=Sun
	start_time = db.Column(db.String, nullable=False)  # '09:00'
	end_time = db.Column(db.String, nullable=False)    # '10:00'


class StudentTimetable(db.Model):
	__tablename__ = 'student_timetables'
	id = db.Column(db.Integer, primary_key=True)
	student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
	subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
	weekday = db.Column(db.Integer, nullable=False)
	start_time = db.Column(db.String, nullable=False)
	end_time = db.Column(db.String, nullable=False)


class Attendance(db.Model):
	__tablename__ = 'attendance'
	id = db.Column(db.Integer, primary_key=True)
	student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
	subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'))
	class_id = db.Column(db.Integer, db.ForeignKey('classes.id'))
	timestamp = db.Column(db.DateTime, nullable=False)
	is_present = db.Column(db.Boolean, default=True)
	method = db.Column(db.String)  # 'face' | 'fingerprint' | 'manual'
