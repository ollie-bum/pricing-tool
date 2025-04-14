# llm_clients.py
import os
import requests
import json
import re
import logging
import anthropic
import google.generativeai as genai

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize clients
anthropic_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# Initialize Gemini
genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))
gemini_model = genai.GenerativeModel('gemini-pro')

# Placeholder for Grok
class GrokClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.x.ai/grok/v1"  # Replace with actual xAI API endpoint
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    async def create(self, model, messages, temperature, max_tokens):
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        try:
            # Use requests for simplicity; for async, consider aiohttp in production
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            
            result = response.json()
            return type('obj', (object,), {
                'choices': [
                    type('obj', (object,), {
                        'message': type('obj', (object,), {
                            'content': result.get('choices', [{}])[0].get('message', {}).get('content', '')
                        })
                    })
                ]
            })
        
        except Exception as e:
            logger.error(f"Grok API request failed: {e}")
            raise

# Initialize Grok (replace with actual when available)
grok_client = GrokClient(api_key=os.environ.get("GROK_API_KEY"))

def create_llm_prompt(product_info):
    """Create standardized prompt for all LLMs"""
    condition = product_info.get('condition', 'excellent')
    brand = product_info.get('brand', '')
    model = product_info.get('model', '')
    details = product_info.get('additional_details', '')
    
    prompt = f"""
    I need a market price analysis for a luxury item with the following details:
    
    Brand: {brand}
    Model: {model}
    Condition: {condition}
    Additional Details: {details}
    
    Please provide the following information:
    1. A price range I could comfortably buy this item at (when sourcing to resell)
    2. An initial listing price to maximize profit
    3. A price to list at if I want to sell quicker
    4. The most likely final sale price
    5. The estimated time to sell this item (in days or weeks)
    
    Include a brief explanation of factors affecting the pricing and time to sell, such as rarity, 
    collectible status, or market trends. Format your response as JSON with the following structure:
    {{
      "buy_price": {{
        "min": value,
        "max": value,
        "explanation": "reason for this price range"
      }},
      "max_profit_price": {{
        "min": value,
        "max": value,
        "explanation": "reason for this price range"
      }},
      "quick_sale_price": {{
        "min": value,
        "max": value,
        "explanation": "reason for this price range"
      }},
      "expected_sale_price": {{
        "min": value,
        "max": value,
        "explanation": "reason for this price range"
      }},
      "estimated_time_to_sell": {{
        "min": value,
        "max": value,
        "unit": "days OR weeks",
        "explanation": "factors affecting sale time"
      }},
      "factors": ["factor1", "factor2", "factor3"],
      "market_analysis": "brief analysis of current market for this item"
    }}
    """
    return prompt

async def get_claude_pricing(product_info):
    """Get pricing analysis from Claude"""
    prompt = create_llm_prompt(product_info)
    
    try:
        # Call Claude API
        response = anthropic_client.messages.create(
            model="claude-3-sonnet-20240229",
            max_tokens=2000,
            temperature=0.0,
            system="You are a luxury goods pricing expert with extensive knowledge of the resale market. Provide accurate price recommendations and sale time estimates based on current market data.",
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        # Extract JSON from Claude's response
        content = response.content[0].text
        
        # Try to extract JSON from the response
        try:
            # First try to parse the whole response as JSON
            pricing_data = json.loads(content)
        except json.JSONDecodeError:
            # If that fails, try to extract JSON using common patterns
            json_match = re.search(r'```json\s*([\s\S]*?)\s*```', content)
            if json_match:
                try:
                    pricing_data = json.loads(json_match.group(1))
                except:
                    return {
                        "error": "Could not parse JSON from Claude response",
                        "raw_response": content
                    }
            else:
                # No JSON block found, return the raw response
                return {
                    "error": "Could not extract JSON from Claude response",
                    "raw_response": content
                }
        
        return {
            "source": "claude",
            "data": pricing_data,
            "confidence": 0.9  # Claude typically provides high-quality pricing insights
        }
        
    except Exception as e:
        logger.error(f"Error getting pricing from Claude: {e}")
        return {"source": "claude", "error": str(e)}

async def get_gemini_pricing(product_info):
    """Get pricing analysis from Google Gemini"""
    prompt = create_llm_prompt(product_info)
    
    try:
        # Call Gemini API
        response = await gemini_model.generate_content_async(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.0,
                max_output_tokens=2000
            )
        )
        
        content = response.text
        
        # Try to extract JSON from the response
        try:
            # First try to parse the whole response as JSON
            pricing_data = json.loads(content)
        except json.JSONDecodeError:
            # If that fails, try to extract JSON using common patterns
            json_match = re.search(r'```json\s*([\s\S]*?)\s*```', content)
            if json_match:
                try:
                    pricing_data = json.loads(json_match.group(1))
                except:
                    return {
                        "error": "Could not parse JSON from Gemini response",
                        "raw_response": content
                    }
            else:
                # No JSON block found, return the raw response
                return {
                    "error": "Could not extract JSON from Gemini response",
                    "raw_response": content
                }
        
        return {
            "source": "gemini",
            "data": pricing_data,
            "confidence": 0.8  # Gemini has good knowledge but may be less specialized
        }
        
    except Exception as e:
        logger.error(f"Error getting pricing from Gemini: {e}")
        return {"source": "gemini", "error": str(e)}

async def get_grok_pricing(product_info):
    """Get pricing analysis from Grok"""
    prompt = create_llm_prompt(product_info)
    
    try:
        # Call Grok API (implementation may vary based on actual API structure)
        response = await grok_client.chat.completions.create(
            model="grok-1",
            messages=[
                {"role": "system", "content": "You are a luxury goods pricing expert with extensive knowledge of the resale market."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            max_tokens=2000
        )
        
        content = response.choices[0].message.content
        
        # Try to extract JSON from the response
        try:
            # First try to parse the whole response as JSON
            pricing_data = json.loads(content)
        except json.JSONDecodeError:
            # If that fails, try to extract JSON using common patterns
            json_match = re.search(r'```json\s*([\s\S]*?)\s*```', content)
            if json_match:
                try:
                    pricing_data = json.loads(json_match.group(1))
                except:
                    return {
                        "error": "Could not parse JSON from Grok response",
                        "raw_response": content
                    }
            else:
                # No JSON block found, return the raw response
                return {
                    "error": "Could not extract JSON from Grok response",
                    "raw_response": content
                }
        
        return {
            "source": "grok",
            "data": pricing_data,
            "confidence": 0.85  # Grok may have good market knowledge
        }
        
    except Exception as e:
        logger.error(f"Error getting pricing from Grok: {e}")
        return {"source": "grok", "error": str(e)}