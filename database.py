from flask_sqlalchemy import SQLAlchemy

# Single SQLAlchemy instance to be used across the app
# Initialized in app.py via db.init_app(app)
db = SQLAlchemy()
