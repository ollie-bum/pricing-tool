# backend/app.py
try:
    from werkzeug.urls import url_quote
except ImportError:
    try:
        from werkzeug.urls import quote as url_quote
    except ImportError:
        from urllib.parse import quote as url_quote

from flask import Flask, request, jsonify, redirect, url_for
from flask_cors import CORS
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import os
import json
import logging
import asyncio
from dotenv import load_dotenv
from datetime import datetime
import sys
import sqlite3
import bcrypt
import flask
import werkzeug
import csv
from io import StringIO
print("Python version:", sys.version)
print("Werkzeug version:", werkzeug.__version__)
print("Flask version:", flask.__version__)

# Relative imports for backend modules
from .llm_clients import get_claude_pricing, get_gemini_pricing, get_grok_pricing
from .aggregator import aggregate_results
from .cache import get_cached_result, store_result

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='../frontend-dist')
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "your-secure-secret-key")
CORS(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    db_path = '/opt/render/project/src/data/users.db'
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, username FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
        conn.close()
        return User(user[0], user[1]) if user else None
    except sqlite3.OperationalError as e:
        logger.error(f"Failed to connect to database {db_path}: {e}")
        return None

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

init_db()

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        db_path = '/opt/render/project/src/data/users.db'
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT id, username, password_hash FROM users WHERE username = ?", (username,))
            user = cursor.fetchone()
            conn.close()
            if user:
                if isinstance(password, str):
                    password = password.encode('utf-8')
                if bcrypt.checkpw(password, user[2]):
                    user_obj = User(user[0], user[1])
                    login_user(user_obj)
                    return jsonify({"success": True, "redirect": url_for('index')})
            return jsonify({"error": "Invalid username or password"}), 401
        except sqlite3.OperationalError as e:
            logger.error(f"Database error during login: {e}")
            return jsonify({"error": "Database unavailable"}), 500
    return app.send_static_file('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    print("📥 Received GET / request")
    return app.send_static_file('index.html')

@app.route('/bulk')
@login_required
def bulk():
    print("📥 Received GET /bulk request")
    return app.send_static_file('bulk.html')

@app.route('/api/price', methods=['POST'])
@login_required
def get_price_analysis():
    if not request.json:
        return jsonify({"error": "No JSON data provided"}), 400
    
    product_info = request.json
    use_sources = product_info.pop("use_sources", [])
    
    if not product_info.get('brand') or not product_info.get('model'):
        return jsonify({"error": "Brand and model are required"}), 400
    
    cached_results = get_cached_result(product_info)
    if cached_results and not request.json.get("skip_cache", False):
        return jsonify({
            "results": cached_results,
            "source": "cache",
            "cached_at": cached_results.get("meta", {}).get("timestamp", "unknown")
        })
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        llm_results = loop.run_until_complete(get_all_llm_pricing(product_info, use_sources))
        if not llm_results:
            return jsonify({
                "error": "No results from any LLM",
                "details": "All LLM requests failed or returned errors"
            }), 500
        
        final_results = aggregate_results(llm_results)
        if "error" in final_results:
            return jsonify({
                "error": "Failed to aggregate LLM results",
                "details": final_results["error"]
            }), 500
            
        if "meta" not in final_results:
            final_results["meta"] = {}
        final_results["meta"]["timestamp"] = datetime.now().isoformat()
        final_results["meta"]["models_used"] = [r["source"] for r in llm_results if "error" not in r]
        
        store_result(product_info, final_results)
        
        return jsonify({
            "results": final_results,
            "source": "llm",
            "llm_count": len(llm_results)
        })
    
    except Exception as e:
        logger.error(f"Error processing request: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        loop.close()

@app.route('/api/bulk_price', methods=['POST'])
@login_required
def bulk_price():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files['file']
    if not file.filename.endswith('.csv'):
        return jsonify({"error": "File must be a CSV"}), 400
    
    results = []
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        content = file.read().decode('utf-8')
        csv_reader = csv.DictReader(StringIO(content))
        for row in csv_reader:
            product_info = {
                "brand": row["brand"],
                "model": row["model"],
                "condition": row["condition"],
                "additional_details": row.get("additional_details", "")
            }
            if not product_info["brand"] or not product_info["model"]:
                results.append({"product": product_info, "error": "Brand and model are required"})
                continue
            cached = get_cached_result(product_info)
            if cached:
                results.append({"product": product_info, "results": cached, "source": "cache"})
            else:
                llm_results = loop.run_until_complete(get_all_llm_pricing(product_info, []))
                if llm_results:
                    final_results = aggregate_results(llm_results)
                    if "error" in final_results:
                        results.append({"product": product_info, "error": "Failed to aggregate LLM results: " + final_results["error"]})
                        continue
                    store_result(product_info, final_results)
                    results.append({"product": product_info, "results": final_results, "source": "llm"})
                else:
                    results.append({"product": product_info, "error": "No LLM results"})
        return jsonify({"results": results})
    except Exception as e:
        logger.error(f"Error processing bulk request: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        loop.close()

async def get_all_llm_pricing(product_info, use_sources):
    tasks = []
    if "claude" in use_sources or not use_sources:
        tasks.append(get_claude_pricing(product_info))
    if "gemini" in use_sources:
        tasks.append(get_gemini_pricing(product_info))
    if "grok" in use_sources:
        tasks.append(get_grok_pricing(product_info))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    valid_results = []
    for result in results:
        if isinstance(result, Exception):
            logger.error(f"LLM error: {result}")
        else:
            valid_results.append(result)
    return valid_results

@app.route('/api/models', methods=['GET'])
@login_required
def get_available_models():
    models = [
        {
            "id": "claude",
            "name": "Claude (Anthropic)",
            "available": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "description": "Specialized in nuanced pricing and luxury market awareness"
        },
        {
            "id": "gemini",
            "name": "Gemini (Google)",
            "available": bool(os.environ.get("GOOGLE_API_KEY")),
            "description": "Strong general market knowledge and trend awareness"
        },
        {
            "id": "grok",
            "name": "Grok (xAI)",
            "available": bool(os.environ.get("GROK_API_KEY")),
            "description": "Real-time market data and contemporary pricing insights"
        }
    ]
    return jsonify({
        "models": models,
        "default": "claude"
    })

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0"
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)