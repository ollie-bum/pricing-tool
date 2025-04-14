# cache.py
import os
import time
import logging

logger = logging.getLogger(__name__)

# In-memory cache for development
in_memory_cache = {}

def get_cached_result(product_info):
    """Check if we have cached results for similar product"""
    if os.environ.get("USE_FIREBASE", "False").lower() == "true":
        return get_firebase_cached_result(product_info)
    else:
        return get_memory_cached_result(product_info)

def store_result(product_info, results):
    """Store results in cache"""
    if os.environ.get("USE_FIREBASE", "False").lower() == "true":
        return store_firebase_result(product_info, results)
    else:
        return store_memory_result(product_info, results)

# In-memory cache implementation
def get_memory_cached_result(product_info):
    # Create a simplified key for lookup (brand + model)
    cache_key = f"{product_info.get('brand', '')}-{product_info.get('model', '')}"
    
    if cache_key in in_memory_cache:
        cache_entry = in_memory_cache[cache_key]
        
        # Check if cache is fresh (less than 24 hours old)
        timestamp = cache_entry.get('timestamp', 0)
        current_time = int(time.time())
        if current_time - timestamp < 86400:  # 24 hours
            logger.info(f"Cache hit for {cache_key}")
            return cache_entry.get('results')
        else:
            logger.info(f"Cache expired for {cache_key}")
    
    return None

def store_memory_result(product_info, results):
    # Create a simplified key for storage
    cache_key = f"{product_info.get('brand', '')}-{product_info.get('model', '')}"
    
    in_memory_cache[cache_key] = {
        'product_info': product_info,
        'results': results,
        'timestamp': int(time.time())
    }
    
    logger.info(f"Stored results in memory cache for {cache_key}")

# Firebase implementation (used when USE_FIREBASE=true)
def get_firebase_cached_result(product_info):
    try:
        import firebase_admin
        from firebase_admin import firestore
        
        # Initialize Firebase if not already done
        if not firebase_admin._apps:
            from firebase_admin import credentials
            cred_path = os.environ.get("FIREBASE_CREDENTIALS_PATH")
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
        
        db = firestore.client()
        
        # Create a simplified key for lookup
        cache_key = f"{product_info.get('brand', '')}-{product_info.get('model', '')}"
        
        cache_ref = db.collection('pricing_cache').document(cache_key)
        doc = cache_ref.get()
        
        if doc.exists:
            data = doc.to_dict()
            timestamp = data.get('timestamp', 0)
            current_time = int(time.time())
            
            # Check if cache is fresh (less than 24 hours old)
            if current_time - timestamp < 86400:  # 24 hours
                logger.info(f"Firebase cache hit for {cache_key}")
                return data.get('results')
            else:
                logger.info(f"Firebase cache expired for {cache_key}")
    except Exception as e:
        logger.error(f"Error checking Firebase cache: {e}")
    
    return None

def store_firebase_result(product_info, results):
    try:
        import firebase_admin
        from firebase_admin import firestore
        
        # Initialize Firebase if not already done
        if not firebase_admin._apps:
            from firebase_admin import credentials
            cred_path = os.environ.get("FIREBASE_CREDENTIALS_PATH")
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
        
        db = firestore.client()
        
        # Create a simplified key for storage
        cache_key = f"{product_info.get('brand', '')}-{product_info.get('model', '')}"
        
        cache_ref = db.collection('pricing_cache').document(cache_key)
        cache_ref.set({
            'product_info': product_info,
            'results': results,
            'timestamp': int(time.time())
        })
        
        logger.info(f"Stored results in Firebase cache for {cache_key}")
    except Exception as e:
        logger.error(f"Error storing in Firebase cache: {e}")