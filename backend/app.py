# app.py

# At the top of your app.py file
try:
    from werkzeug.urls import url_quote
except ImportError:
    # Fallback for newer Werkzeug versions
    try:
        from werkzeug.urls import quote as url_quote
    except ImportError:
        # Last resort fallback
        from urllib.parse import quote as url_quote

from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import json
import logging
import asyncio
from dotenv import load_dotenv
from datetime import datetime
import sys
import flask
import werkzeug
print("Python version:", sys.version)
print("Werkzeug version:", werkzeug.__version__)
print("Flask version:", flask.__version__)

# Import our modules
from backend.llm_clients import get_claude_pricing, get_gemini_pricing, get_grok_pricing
from backend.aggregator import aggregate_results
from backend.cache import get_cached_result, store_result

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

async def get_all_llm_pricing(product_info, use_sources):
    """Get pricing from all enabled LLMs in parallel"""
    tasks = []
    
    if "claude" in use_sources or not use_sources:
        tasks.append(get_claude_pricing(product_info))
    
    if "gemini" in use_sources:
        tasks.append(get_gemini_pricing(product_info))
        
    if "grok" in use_sources:
        tasks.append(get_grok_pricing(product_info))
    
    # Run all tasks concurrently
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Filter out exceptions
    valid_results = []
    for result in results:
        if isinstance(result, Exception):
            logger.error(f"LLM error: {result}")
        else:
            valid_results.append(result)
    
    return valid_results

@app.route('/api/price', methods=['POST'])
def get_price_analysis():
    """API endpoint to get price analysis for a luxury item"""
    if not request.json:
        return jsonify({"error": "No JSON data provided"}), 400
    
    # Extract product info and options from request
    product_info = request.json
    use_sources = product_info.pop("use_sources", [])  # Empty list means use default (Claude only)
    
    # Check for required fields
    if not product_info.get('brand') or not product_info.get('model'):
        return jsonify({"error": "Brand and model are required"}), 400
    
    # Check cache for existing results
    cached_results = get_cached_result(product_info)
    if cached_results and not request.json.get("skip_cache", False):
        return jsonify({
            "results": cached_results,
            "source": "cache",
            "cached_at": cached_results.get("meta", {}).get("timestamp", "unknown")
        })
    
    # Set up async event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        # Get pricing from all enabled LLMs
        llm_results = loop.run_until_complete(get_all_llm_pricing(product_info, use_sources))
        
        # If we got no valid results
        if not llm_results:
            return jsonify({
                "error": "No results from any LLM",
                "details": "All LLM requests failed or returned errors"
            }), 500
        
        # Aggregate results
        final_results = aggregate_results(llm_results)
        
        # Add timestamp
        if "meta" not in final_results:
            final_results["meta"] = {}
        final_results["meta"]["timestamp"] = datetime.now().isoformat()
        final_results["meta"]["models_used"] = [r["source"] for r in llm_results if "error" not in r]
        
        # Store results in cache
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

@app.route('/api/models', methods=['GET'])
def get_available_models():
    """Return available LLM models and their status"""
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
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0"
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)