# aggregator.py
import statistics
from datetime import datetime

def aggregate_results(results_list):
    """Aggregate results from multiple LLMs using weighted average"""
    
    # Skip any results with errors
    valid_results = [r for r in results_list if "error" not in r]
    
    if not valid_results:
        return {
            "error": "No valid results from any LLM",
            "raw_results": results_list
        }
    
    # If only one valid result, return it
    if len(valid_results) == 1:
        return valid_results[0]["data"]
    
    # Initialize aggregated result
    aggregated = {
        "buy_price": {"min": 0, "max": 0, "explanation": ""},
        "max_profit_price": {"min": 0, "max": 0, "explanation": ""},
        "quick_sale_price": {"min": 0, "max": 0, "explanation": ""},
        "expected_sale_price": {"min": 0, "max": 0, "explanation": ""},
        "estimated_time_to_sell": {"min": 0, "max": 0, "unit": "days", "explanation": ""},
        "factors": [],
        "market_analysis": ""
    }
    
    # Calculate weighted averages for price ranges
    total_confidence = sum(r["confidence"] for r in valid_results)
    
    # Process regular price fields
    for price_type in ["buy_price", "max_profit_price", "quick_sale_price", "expected_sale_price"]:
        # Get values and weights for min and max
        min_values = [(r["data"][price_type]["min"], r["confidence"]) for r in valid_results]
        max_values = [(r["data"][price_type]["max"], r["confidence"]) for r in valid_results]
        
        # Calculate weighted averages
        aggregated[price_type]["min"] = round(sum(val * weight for val, weight in min_values) / total_confidence)
        aggregated[price_type]["max"] = round(sum(val * weight for val, weight in max_values) / total_confidence)
        
        # Use explanation from highest confidence result
        highest_conf_result = max(valid_results, key=lambda r: r["confidence"])
        aggregated[price_type]["explanation"] = highest_conf_result["data"][price_type]["explanation"]
    
    # Handle estimated time to sell - need to standardize units first
    time_mins = []
    time_maxs = []
    for result in valid_results:
        time_data = result["data"].get("estimated_time_to_sell", {})
        if not time_data:
            continue
            
        # Convert weeks to days if needed
        unit = time_data.get("unit", "days").lower()
        min_value = time_data.get("min", 0)
        max_value = time_data.get("max", 0)
        
        if unit == "weeks":
            min_value *= 7
            max_value *= 7
            
        time_mins.append((min_value, result["confidence"]))
        time_maxs.append((max_value, result["confidence"]))
    
    if time_mins and time_maxs:
        # Calculate weighted average for time estimates
        min_time_days = sum(val * weight for val, weight in time_mins) / total_confidence
        max_time_days = sum(val * weight for val, weight in time_maxs) / total_confidence
        
        # Decide whether to use days or weeks for output
        if min_time_days >= 14 and max_time_days >= 14:
            aggregated["estimated_time_to_sell"]["min"] = round(min_time_days / 7, 1)
            aggregated["estimated_time_to_sell"]["max"] = round(max_time_days / 7, 1)
            aggregated["estimated_time_to_sell"]["unit"] = "weeks"
        else:
            aggregated["estimated_time_to_sell"]["min"] = round(min_time_days)
            aggregated["estimated_time_to_sell"]["max"] = round(max_time_days)
            aggregated["estimated_time_to_sell"]["unit"] = "days"
            
        # Use explanation from highest confidence result
        aggregated["estimated_time_to_sell"]["explanation"] = highest_conf_result["data"].get("estimated_time_to_sell", {}).get("explanation", "")
    
    # Collect all unique factors
    all_factors = []
    for result in valid_results:
        all_factors.extend(result["data"]["factors"])
    
    # Keep unique factors
    aggregated["factors"] = list(set(all_factors))
    
    # Use market analysis from highest confidence result
    aggregated["market_analysis"] = highest_conf_result["data"]["market_analysis"]
    
    # Add metadata about sources
    aggregated["meta"] = {
        "sources": [r["source"] for r in valid_results],
        "price_range_variation": calculate_variation(valid_results),
        "timestamp": datetime.now().isoformat()
    }
    
    return aggregated

def calculate_variation(results):
    """Calculate variation in price predictions between models"""
    variation = {}
    
    for price_type in ["buy_price", "max_profit_price", "quick_sale_price", "expected_sale_price"]:
        min_values = [r["data"][price_type]["min"] for r in results]
        max_values = [r["data"][price_type]["max"] for r in results]
        
        # Calculate coefficient of variation (std dev / mean)
        if len(min_values) > 1:
            min_cv = statistics.stdev(min_values) / statistics.mean(min_values) if statistics.mean(min_values) > 0 else 0
            max_cv = statistics.stdev(max_values) / statistics.mean(max_values) if statistics.mean(max_values) > 0 else 0
            variation[price_type] = {
                "min_cv": round(min_cv, 2),
                "max_cv": round(max_cv, 2)
            }
    
    # Also calculate variation for time to sell
    time_mins = []
    time_maxs = []
    
    for result in results:
        time_data = result["data"].get("estimated_time_to_sell", {})
        if not time_data:
            continue
            
        # Convert weeks to days if needed
        unit = time_data.get("unit", "days").lower()
        min_value = time_data.get("min", 0)
        max_value = time_data.get("max", 0)
        
        if unit == "weeks":
            min_value *= 7
            max_value *= 7
            
        time_mins.append(min_value)
        time_maxs.append(max_value)
    
    if len(time_mins) > 1 and len(time_maxs) > 1:
        min_cv = statistics.stdev(time_mins) / statistics.mean(time_mins) if statistics.mean(time_mins) > 0 else 0
        max_cv = statistics.stdev(time_maxs) / statistics.mean(time_maxs) if statistics.mean(time_maxs) > 0 else 0
        
        variation["estimated_time_to_sell"] = {
            "min_cv": round(min_cv, 2),
            "max_cv": round(max_cv, 2)
        }
    
    return variation