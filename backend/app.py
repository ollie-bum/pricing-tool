# backend/app.py
try:
    from werkzeug.urls import url_quote
except ImportError:
    try:
        from werkzeug.urls import quote as url_quote
    except ImportError:
        from urllib.parse import quote as url_quote

from flask import Flask, request, jsonify, redirect, url_for, render_template
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
from io import StringIO, BytesIO
from google.cloud import storage
from google.oauth2 import service_account
from google.auth import compute_engine
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

app = Flask(__name__, static_folder='../frontend-dist', template_folder='../templates')
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "your-secure-secret-key")
app.config['SESSION_COOKIE_DOMAIN'] = '.maisonbum.com'  # Share session cookie across subdomains
app.config['SESSION_COOKIE_SECURE'] = True  # Ensure cookie is sent over HTTPS
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # Allow cross-subdomain requests
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

# Subdomain routing middleware
@app.before_request
def handle_subdomain():
    # Skip middleware for /login, static files, API routes, and debug endpoint to prevent redirect loop
    if request.path == '/login' or request.path.startswith('/frontend-dist') or request.path.startswith('/api') or request.path == '/debug_oidc_token':
        return
    
    host = request.host.lower()
    if host == 'pricingtool.maisonbum.com':
        if request.path != '/pricing/single':
            return redirect(url_for('index'))
    elif host == 'pricingtoolbulk.maisonbum.com':
        if request.path != '/pricing/bulk':
            return redirect(url_for('bulk'))
    # Default behavior for other routes

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        host = request.host.lower()
        if host == 'pricingtoolbulk.maisonbum.com':
            return redirect(url_for('bulk'))
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
                    host = request.host.lower()
                    if host == 'pricingtoolbulk.maisonbum.com':
                        return jsonify({"success": True, "redirect": url_for('bulk')})
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

@app.route('/pricing/single')
@login_required
def index():
    print("📥 Received GET /pricing/single request")
    return render_template('index.html.jinja2')

@app.route('/pricing/bulk')
@login_required
def bulk():
    print("📥 Received GET /pricing/bulk request")
    return render_template('bulk.html.jinja2')

@app.route('/debug_oidc_token')
@login_required
def debug_oidc_token():
    # Log the OIDC token provided by Render
    token = os.environ.get('RENDER_OIDC_TOKEN', 'No token found')
    logger.info(f"Render OIDC Token: {token}")
    return jsonify({"oidc_token": token})

@app.route('/api/price', methods=['POST'])
@login_required
async def get_price_analysis():
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

async def process_product_batch(products, use_sources):
    """Process a batch of products by combining them into a single LLM request"""
    if not products:
        return []
    
    # Combine prompts for all products in the batch
    combined_prompt = ""
    for idx, product in enumerate(products):
        if not product["brand"] or not product["model"]:
            return [{"product": product, "error": "Brand and model are required"} for product in products]
        
        # Check cache for each product
        cached = get_cached_result(product)
        if cached:
            return [{"product": product, "results": cached, "source": "cache"} for product in products]
        
        condition = product.get('condition', 'excellent')
        brand = product.get('brand', '')
        model = product.get('model', '')
        details = product.get('additional_details', '')
        prompt = f"""
        Item {idx + 1}:
        Brand: {brand}
        Model: {model}
        Condition: {condition}
        Additional Details: {details}
        """
        combined_prompt += prompt + "\n"
    
    combined_prompt += """
    For each item listed above, provide a market price analysis with the following details:
    1. A price range to buy the item at (for resale)
    2. An initial listing price to maximize profit
    3. A price to list at for a quick sale
    4. The most likely final sale price
    5. The estimated time to sell (in days or weeks)
    Include explanations for each price range and time to sell, considering factors like rarity, collectible status, or market trends. Format the response as a JSON array where each element corresponds to an item in the order listed, with the structure:
    [
      {
        "buy_price": {"min": value, "max": value, "explanation": "reason"},
        "max_profit_price": {"min": value, "max": value, "explanation": "reason"},
        "quick_sale_price": {"min": value, "max": value, "explanation": "reason"},
        "expected_sale_price": {"min": value, "max": value, "explanation": "reason"},
        "estimated_time_to_sell": {"min": value, "max": value, "unit": "days OR weeks", "explanation": "factors"},
        "factors": ["factor1", "factor2"],
        "market_analysis": "brief analysis"
      },
      ...
    ]
    """
    
    # Query LLMs with the combined prompt
    llm_results = await get_all_llm_pricing({"combined_prompt": combined_prompt}, use_sources)
    logger.info(f"LLM results for batch: {llm_results}")
    
    if not llm_results:
        return [{"product": product, "error": "No LLM results"} for product in products]
    
    final_results = aggregate_results(llm_results)
    if "error" in final_results:
        return [{"product": product, "error": "Failed to aggregate LLM results: " + final_results["error"]} for product in products]
    
    # Ensure the results match the number of products
    if not isinstance(final_results, list) or len(final_results) != len(products):
        return [{"product": product, "error": "Unexpected LLM response format"} for product in products]
    
    # Store results in cache and return
    batch_results = []
    for product, result in zip(products, final_results):
        store_result(product, result)
        batch_results.append({"product": product, "results": result, "source": "llm"})
    
    return batch_results

async def process_product(product, use_sources):
    """Process a single product (fallback for non-batched processing)"""
    if not product["brand"] or not product["model"]:
        return {"product": product, "error": "Brand and model are required"}
    
    cached = get_cached_result(product)
    if cached:
        return {"product": product, "results": cached, "source": "cache"}
    
    llm_results = await get_all_llm_pricing(product, use_sources)
    logger.info(f"LLM results for {product['brand']} {product['model']}: {llm_results}")
    if llm_results:
        final_results = aggregate_results(llm_results)
        if "error" in final_results:
            return {"product": product, "error": "Failed to aggregate LLM results: " + final_results["error"]}
        store_result(product, final_results)
        return {"product": product, "results": final_results, "source": "llm"}
    else:
        return {"product": product, "error": "No LLM results"}

@app.route('/api/bulk_price', methods=['POST'])
@login_required
async def bulk_price():
    # Check if processing from GCS
    gcs_bucket = request.form.get('gcs_bucket')
    gcs_file_path = request.form.get('gcs_file_path')
    
    if gcs_bucket and gcs_file_path:
        # Initialize GCS client using Workload Identity
        credentials = compute_engine.IDTokenCredentials(
            audience=f"//iam.googleapis.com/projects/{os.environ.get('GOOGLE_CLOUD_PROJECT')}/locations/global/workloadIdentityPools/render-identity-pool/providers/render-oidc",
            target_audience=f"//iam.googleapis.com/projects/{os.environ.get('GOOGLE_CLOUD_PROJECT')}/locations/global/workloadIdentityPools/render-identity-pool/providers/render-oidc"
        )
        storage_client = storage.Client(credentials=credentials, project=os.environ.get("GOOGLE_CLOUD_PROJECT"))
        bucket = storage_client.bucket(gcs_bucket)
        blob = bucket.blob(gcs_file_path)
        
        # Download CSV from GCS
        try:
            content = blob.download_as_text()
        except Exception as e:
            logger.error(f"Error downloading file from GCS: {e}")
            return jsonify({"error": f"Failed to download file from GCS: {str(e)}"}), 500
    else:
        # Use uploaded file
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400
        file = request.files['file']
        if not file.filename.endswith('.csv'):
            return jsonify({"error": "File must be a CSV"}), 400
        content = file.read().decode('utf-8')
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        csv_reader = csv.DictReader(StringIO(content))
        products = []
        csv_rows = []
        for row in csv_reader:
            product = {
                "brand": row["brand"],
                "model": row["model"],
                "condition": row["condition"],
                "additional_details": row.get("additional_details", "")
            }
            products.append(product)
            csv_rows.append(row)
        
        # Query all available LLMs
        use_sources = ["claude", "gemini", "grok"]
        
        # Process in batches of 10
        batch_size = 10
        final_results = []
        for i in range(0, len(products), batch_size):
            batch = products[i:i + batch_size]
            batch_results = await process_product_batch(batch, use_sources)
            final_results.extend(batch_results)
            if i + batch_size < len(products):
                await asyncio.sleep(12)  # Throttle to avoid rate limits
        
        # Prepare updated CSV with pricing data
        updated_rows = []
        for product_result, original_row in zip(final_results, csv_rows):
            row = original_row.copy()
            if "error" in product_result:
                row["buy_price_min"] = ""
                row["buy_price_max"] = ""
                row["max_profit_price_min"] = ""
                row["max_profit_price_max"] = ""
                row["quick_sale_price_min"] = ""
                row["quick_sale_price_max"] = ""
                row["expected_sale_price_min"] = ""
                row["expected_sale_price_max"] = ""
                row["time_to_sell_min"] = ""
                row["time_to_sell_max"] = ""
                row["time_to_sell_unit"] = ""
                row["error"] = product_result["error"]
            else:
                result = product_result["results"]
                row["buy_price_min"] = result["buy_price"]["min"]
                row["buy_price_max"] = result["buy_price"]["max"]
                row["max_profit_price_min"] = result["max_profit_price"]["min"]
                row["max_profit_price_max"] = result["max_profit_price"]["max"]
                row["quick_sale_price_min"] = result["quick_sale_price"]["min"]
                row["quick_sale_price_max"] = result["quick_sale_price"]["max"]
                row["expected_sale_price_min"] = result["expected_sale_price"]["min"]
                row["expected_sale_price_max"] = result["expected_sale_price"]["max"]
                row["time_to_sell_min"] = result["estimated_time_to_sell"]["min"]
                row["time_to_sell_max"] = result["estimated_time_to_sell"]["max"]
                row["time_to_sell_unit"] = result["estimated_time_to_sell"]["unit"]
                row["error"] = ""
            updated_rows.append(row)
        
        # Write updated CSV back to GCS if applicable
        if gcs_bucket and gcs_file_path:
            output = StringIO()
            fieldnames = list(csv_rows[0].keys()) + [
                "buy_price_min", "buy_price_max",
                "max_profit_price_min", "max_profit_price_max",
                "quick_sale_price_min", "quick_sale_price_max",
                "expected_sale_price_min", "expected_sale_price_max",
                "time_to_sell_min", "time_to_sell_max", "time_to_sell_unit",
                "error"
            ]
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for row in updated_rows:
                writer.writerow(row)
            
            try:
                blob.upload_from_string(output.getvalue(), content_type='text/csv')
                logger.info(f"Updated CSV uploaded to GCS: {gcs_file_path}")
            except Exception as e:
                logger.error(f"Error uploading updated CSV to GCS: {e}")
                return jsonify({"error": f"Failed to upload updated CSV to GCS: {str(e)}"}), 500
        
        return jsonify({"results": final_results})
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