# add_user.py
import sqlite3
import bcrypt
import argparse

def init_db():
    conn = sqlite3.connect('/opt/render/project/src/data/users.db')
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

def add_user(username, password):
    init_db()
    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    conn = sqlite3.connect('/opt/render/project/src/data/users.db')
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, password_hash))
        conn.commit()
        print(f"User '{username}' added successfully.")
    except sqlite3.IntegrityError:
        print(f"Error: Username '{username}' already exists.")
    finally:
        conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Add a user to the pricing tool database.")
    parser.add_argument("username", help="Username for the new user")
    parser.add_argument("password", help="Password for the new user")
    args = parser.parse_args()
    add_user(args.username, args.password)