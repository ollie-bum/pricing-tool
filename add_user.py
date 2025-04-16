# add_user.py
import sqlite3
import bcrypt
import argparse
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_db():
    db_dir = '/opt/render/project/src/data'
    db_path = os.path.join(db_dir, 'users.db')
    try:
        os.makedirs(db_dir, exist_ok=True)
    except Exception as e:
        logger.error(f"Failed to create directory {db_dir}: {e}")
        return
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()
    except sqlite3.OperationalError as e:
        logger.error(f"Failed to initialize database {db_path}: {e}")

def add_user(username, password):
    init_db()
    db_path = '/opt/render/project/src/data/users.db'
    try:
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, password_hash))
        conn.commit()
        print(f"User '{username}' added successfully.")
    except sqlite3.IntegrityError:
        print(f"Error: Username '{username}' already exists.")
    except sqlite3.OperationalError as e:
        print(f"Error: Failed to access database: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Add a user to the pricing tool database.")
    parser.add_argument("username", help="Username for the new user")
    parser.add_argument("password", help="Password for the new user")
    args = parser.parse_args()
    add_user(args.username, args.password)