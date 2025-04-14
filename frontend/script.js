// script.js
document.addEventListener('DOMContentLoaded', function() {
    // Get form and elements
    const form = document.getElementById('pricingForm');
    const submitButton = document.getElementById('submitButton');
    const loadingElement = document.getElementById('loading');
    const errorElement = document.getElementById('error');
    const errorMessage = document.getElementById('errorMessage');
    const resultsElement = document.getElementById('results');
    
    // API endpoint - replace with your actual endpoint when deployed
    const API_ENDPOINT = 'http://localhost:5000/api/price';
    
    // Check for available models
    fetchAvailableModels();
    
    // Format currency
    function formatCurrency(value) {
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD',
            minimumFractionDigits: 0,
            maximumFractionDigits: 0
        }).format(value);
    }
    
    // Format time range
    function formatTimeRange(min, max, unit) {
        if (min === max) {
            return `${min} ${unit}${min !== 1 ? 's' : ''}`;
        } else {
            return `${min}-${max} ${unit}s`;
        }
    }

    // Handle form submission
    form.addEventListener('submit', function(e) {
        e.preventDefault();
        
        // Get form values
        const brand = document.getElementById('brand').value;
        const model = document.getElementById('model').value;
        const condition = document.getElementById('condition').value;
        const additionalDetails = document.getElementById('additionalDetails').value;
        
        // Get selected LLM models
        const selectedModels = getSelectedModels();
        
        // Show loading state
        submitButton.disabled = true;
        submitButton.innerText = 'Analyzing...';
        loadingElement.style.display = 'flex';
        errorElement.style.display = 'none';
        resultsElement.style.display = 'none';
        
        // Prepare request data
        const requestData = {
            brand,
            model,
            condition,
            additional_details: additionalDetails,
            use_sources: selectedModels,
            skip_cache: document.getElementById('skipCache').checked
        };

        // Call the API
        fetch(API_ENDPOINT, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestData)
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            return response.json();
        })
        .then(data => {
            // Display results
            displayResults(data.results);
            
            // Show source information
            showSourceInfo(data);
        })
        .catch(error => {
            // Show error
            errorMessage.innerText = error.message || 'An error occurred while fetching the price analysis.';
            errorElement.style.display = 'block';
        })
        .finally(() => {
            // Reset UI state
            submitButton.disabled = false;
            submitButton.innerText = 'Get Price Analysis';
            loadingElement.style.display = 'none';
        });
    });

    // Get selected LLM models
    function getSelectedModels() {
        const checkboxes = document.querySelectorAll('.llm-checkbox:checked');
        return Array.from(checkboxes).map(checkbox => checkbox.value);
    }
    
    // Fetch available models from the API
    function fetchAvailableModels() {
        const modelsEndpoint = API_ENDPOINT.replace('/price', '/models');
        
        fetch(modelsEndpoint)
            .then(response => {
                if (!response.ok) {
                    throw new Error('Failed to fetch available models');
                }
                return response.json();
            })
            .then(data => {
                updateModelAvailability(data.models);
            })
            .catch(error => {
                console.error('Error fetching available models:', error);
                // If we can't fetch models, assume only Claude is available
                const checkboxes = document.querySelectorAll('.llm-checkbox');
                checkboxes.forEach(checkbox => {
                    if (checkbox.value !== 'claude') {
                        checkbox.disabled = true;
                        checkbox.checked = false;
                        checkbox.parentNode.classList.add('unavailable');
                    }
                });
            });
    }
    
    // Update UI based on available models
    function updateModelAvailability(models) {
        models.forEach(model => {
            const checkbox = document.getElementById(`${model.id}Model`);
            if (checkbox) {
                checkbox.disabled = !model.available;
                if (!model.available) {
                    checkbox.checked = false;
                    checkbox.parentNode.classList.add('unavailable');
                    checkbox.parentNode.setAttribute('title', 'API key not configured');
                }
            }
        });
    }
    
    // Display the results in the UI
    function displayResults(results) {
        // Buy price
        document.getElementById('buyPriceRange').innerText = 
            `${formatCurrency(results.buy_price.min)} - ${formatCurrency(results.buy_price.max)}`;
        document.getElementById('buyPriceExplanation').innerText = results.buy_price.explanation;
        
        // Max profit price
        document.getElementById('maxProfitRange').innerText = 
            `${formatCurrency(results.max_profit_price.min)} - ${formatCurrency(results.max_profit_price.max)}`;
        document.getElementById('maxProfitExplanation').innerText = results.max_profit_price.explanation;
        
        // Quick sale price
        document.getElementById('quickSaleRange').innerText = 
            `${formatCurrency(results.quick_sale_price.min)} - ${formatCurrency(results.quick_sale_price.max)}`;
        document.getElementById('quickSaleExplanation').innerText = results.quick_sale_price.explanation;
        
        // Expected sale price
        document.getElementById('expectedSaleRange').innerText = 
            `${formatCurrency(results.expected_sale_price.min)} - ${formatCurrency(results.expected_sale_price.max)}`;
        document.getElementById('expectedSaleExplanation').innerText = results.expected_sale_price.explanation;
        
        // Time to sell
        if (results.estimated_time_to_sell) {
            document.getElementById('timeToSellRange').innerText = 
                formatTimeRange(
                    results.estimated_time_to_sell.min, 
                    results.estimated_time_to_sell.max, 
                    results.estimated_time_to_sell.unit
                );
            document.getElementById('timeToSellExplanation').innerText = 
                results.estimated_time_to_sell.explanation;
        }
        
        // Market analysis
        document.getElementById('marketAnalysis').innerText = results.market_analysis;
        
        // Factors
        const factorsList = document.getElementById('factorsList');
        factorsList.innerHTML = ''; // Clear existing list
        
        results.factors.forEach(factor => {
            const li = document.createElement('li');
            li.innerText = factor;
            factorsList.appendChild(li);
        });
        
        // Add model info if available
        if (results.meta && results.meta.models_used) {
            addModelInfoToResults(results.meta);
        }
        
        // Show results
        resultsElement.style.display = 'block';
    }
    
    // Add model info to results
    function addModelInfoToResults(meta) {
        // Check if meta-info section already exists
        let metaInfoSection = document.querySelector('.meta-info');
        
        if (!metaInfoSection) {
            // Create meta info section
            metaInfoSection = document.createElement('div');
            metaInfoSection.className = 'meta-info';
            
            // Add it after market analysis
            const marketAnalysis = document.querySelector('.market-analysis');
            marketAnalysis.appendChild(metaInfoSection);
        }
        
        // Create content for meta info section
        let metaContent = '<h4>AI Models Used</h4><ul class="models-used">';
        
        meta.models_used.forEach(model => {
            const modelName = getModelDisplayName(model);
            metaContent += `<li class="model-${model}">${modelName}</li>`;
        });
        
        metaContent += '</ul>';
        
        // Add timestamp if available
        if (meta.timestamp) {
            const date = new Date(meta.timestamp);
            metaContent += `<div class="timestamp">Analysis generated: ${date.toLocaleString()}</div>`;
        }
        
        // Add variation info if available
        if (meta.price_range_variation) {
            metaContent += '<div class="variation-info"><h4>Model Agreement</h4>';
            
            const variationData = meta.price_range_variation;
            const categories = Object.keys(variationData);
            
            if (categories.length > 0) {
                metaContent += '<ul class="variation-list">';
                
                for (const category of categories) {
                    const variation = variationData[category];
                    const avgVariation = (variation.min_cv + variation.max_cv) / 2;
                    let agreement = 'High';
                    
                    if (avgVariation > 0.3) {
                        agreement = 'Low';
                    } else if (avgVariation > 0.15) {
                        agreement = 'Medium';
                    }
                    
                    // Get human-readable price category name
                    let categoryName = category.replace('_price', '').replace('_', ' ');
                    if (category === 'estimated_time_to_sell') {
                        categoryName = 'Time to Sell';
                    }
                    categoryName = categoryName.charAt(0).toUpperCase() + categoryName.slice(1);
                    
                    metaContent += `<li>${categoryName}: <span class="agreement-${agreement.toLowerCase()}">${agreement} Agreement</span></li>`;
                }
                
                metaContent += '</ul>';
            }
            
            metaContent += '</div>';
        }
        
        // Add to page
        metaInfoSection.innerHTML = metaContent;
    }
    
    // Show source information
    function showSourceInfo(data) {
        // Remove any existing badge
        const existingBadge = document.querySelector('.source-badge');
        if (existingBadge) {
            existingBadge.remove();
        }
        
        // Create source badge
        let sourceBadge = document.createElement('div');
        sourceBadge.className = 'source-badge';
        
        if (data.source === 'cache') {
            sourceBadge.classList.add('cache-source');
            sourceBadge.innerHTML = '<span>Cached Result</span>';
            if (data.cached_at) {
                const date = new Date(data.cached_at);