"""
Mock AI Model Server - 25 Models for INESDATA
==============================================

Adapted from AIModelHub. Serves 25 mock models in 5 groups:
- Group 1: Computer Vision - Medical Imaging (5 models)
- Group 2: NLP - Sentiment Analysis (5 models)
- Group 3: Regression - Health Metrics (5 models)
- Group 4: Tabular Classification - Flora (5 models)
- Group 5: Fraud Detection - Transactional (5 models)

Each group shares the same input schema for benchmarking.
Port: 8080
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime
import time
import random

app = Flask(__name__)
CORS(app)

execution_log = []

# ============================================================================
# GROUP 1: COMPUTER VISION - MEDICAL IMAGING
# Input: image_url (string), image_size (string)
# ============================================================================

def chest_xray_classifier(data):
    time.sleep(random.uniform(0.1, 0.3))
    conditions = ['Normal', 'Pneumonia', 'COVID-19', 'Tuberculosis', 'Lung Cancer']
    predicted = random.choice(conditions)
    return {
        'model': 'Chest X-Ray Classifier',
        'prediction': predicted,
        'confidence': round(random.uniform(0.75, 0.95), 3),
        'processing_time_ms': round(random.uniform(80, 300), 2)
    }

def pneumonia_detector(data):
    time.sleep(random.uniform(0.1, 0.3))
    result = random.choice(['No_Pneumonia', 'Bacterial_Pneumonia', 'Viral_Pneumonia'])
    return {
        'model': 'Pneumonia Detector',
        'prediction': result,
        'confidence': round(random.uniform(0.78, 0.96), 3),
        'severity': random.choice(['Mild', 'Moderate', 'Severe']) if 'Pneumonia' in result else 'None',
        'processing_time_ms': round(random.uniform(70, 280), 2)
    }

def covid19_screener(data):
    time.sleep(random.uniform(0.1, 0.3))
    result = random.choice(['Negative', 'Positive', 'Probable'])
    return {
        'model': 'COVID-19 Screener',
        'prediction': result,
        'confidence': round(random.uniform(0.72, 0.94), 3),
        'recommendation': 'PCR test recommended' if result != 'Negative' else 'No further action needed',
        'processing_time_ms': round(random.uniform(90, 320), 2)
    }

def lung_nodule_detector(data):
    time.sleep(random.uniform(0.1, 0.3))
    has_nodule = random.choice([True, False])
    return {
        'model': 'Lung Nodule Detector',
        'has_nodule': has_nodule,
        'nodule_type': random.choice(['Benign', 'Malignant', 'Indeterminate']) if has_nodule else 'None',
        'confidence': round(random.uniform(0.76, 0.93), 3),
        'risk_score': round(random.uniform(0.1, 0.9), 2) if has_nodule else 0.0,
        'processing_time_ms': round(random.uniform(100, 340), 2)
    }

def tuberculosis_classifier(data):
    time.sleep(random.uniform(0.1, 0.3))
    result = random.choice(['Normal', 'TB_Active', 'TB_Latent', 'TB_Suspected'])
    return {
        'model': 'Tuberculosis Classifier',
        'prediction': result,
        'confidence': round(random.uniform(0.74, 0.92), 3),
        'follow_up': 'Sputum test recommended' if 'TB' in result else 'None',
        'processing_time_ms': round(random.uniform(80, 300), 2)
    }

# ============================================================================
# GROUP 2: NLP - SENTIMENT ANALYSIS
# Input: text (string)
# ============================================================================

def ecommerce_sentiment(data):
    time.sleep(random.uniform(0.05, 0.2))
    text = data.get('text', '')
    positive_words = ['good', 'great', 'excellent', 'love', 'amazing']
    negative_words = ['bad', 'terrible', 'hate', 'awful', 'horrible']
    pos_count = sum(word in text.lower() for word in positive_words)
    neg_count = sum(word in text.lower() for word in negative_words)
    if pos_count > neg_count:
        sentiment, score = 'positive', random.uniform(0.7, 0.95)
    elif neg_count > pos_count:
        sentiment, score = 'negative', random.uniform(0.7, 0.95)
    else:
        sentiment, score = 'neutral', random.uniform(0.45, 0.65)
    return {
        'model': 'E-commerce Sentiment Analyzer',
        'sentiment': sentiment,
        'confidence': round(score, 3),
        'rating_prediction': round(random.uniform(1, 5), 1),
        'processing_time_ms': round(random.uniform(50, 200), 2)
    }

def twitter_sentiment(data):
    time.sleep(random.uniform(0.05, 0.2))
    sentiment = random.choice(['positive', 'negative', 'neutral'])
    return {
        'model': 'Twitter Sentiment Analyzer',
        'sentiment': sentiment,
        'confidence': round(random.uniform(0.68, 0.92), 3),
        'emotion': random.choice(['joy', 'anger', 'sadness', 'surprise', 'neutral']),
        'processing_time_ms': round(random.uniform(40, 180), 2)
    }

def product_review_classifier(data):
    time.sleep(random.uniform(0.05, 0.2))
    sentiment = random.choice(['very_positive', 'positive', 'neutral', 'negative', 'very_negative'])
    return {
        'model': 'Product Review Classifier',
        'sentiment': sentiment,
        'confidence': round(random.uniform(0.71, 0.94), 3),
        'star_rating': round(random.uniform(1, 5), 1),
        'processing_time_ms': round(random.uniform(50, 200), 2)
    }

def customer_feedback_analyzer(data):
    time.sleep(random.uniform(0.05, 0.2))
    sentiment = random.choice(['satisfied', 'dissatisfied', 'neutral'])
    return {
        'model': 'Customer Feedback Analyzer',
        'sentiment': sentiment,
        'confidence': round(random.uniform(0.69, 0.93), 3),
        'satisfaction_score': round(random.uniform(0, 100), 1),
        'action_required': random.choice([True, False]),
        'processing_time_ms': round(random.uniform(60, 200), 2)
    }

def social_media_sentiment(data):
    time.sleep(random.uniform(0.05, 0.2))
    sentiment = random.choice(['positive', 'negative', 'neutral', 'mixed'])
    return {
        'model': 'Social Media Sentiment',
        'sentiment': sentiment,
        'confidence': round(random.uniform(0.70, 0.91), 3),
        'virality_score': round(random.uniform(0, 100), 1),
        'engagement_prediction': random.choice(['High', 'Medium', 'Low']),
        'processing_time_ms': round(random.uniform(50, 200), 2)
    }

# ============================================================================
# GROUP 3: REGRESSION - HEALTH METRICS
# Input: weight_kg (float), height_m (float)
# ============================================================================

def bmi_calculator(data):
    time.sleep(random.uniform(0.05, 0.15))
    weight_kg = float(data.get('weight_kg', 70.0))
    height_m = float(data.get('height_m', 1.75))
    bmi = weight_kg / (height_m ** 2)
    if bmi < 18.5: category = 'Underweight'
    elif bmi < 25: category = 'Normal'
    elif bmi < 30: category = 'Overweight'
    else: category = 'Obese'
    return {
        'model': 'BMI Calculator',
        'bmi': round(bmi, 2),
        'category': category,
        'weight_kg': weight_kg,
        'height_m': height_m,
        'processing_time_ms': round(random.uniform(50, 150), 2)
    }

def body_fat_estimator(data):
    time.sleep(random.uniform(0.05, 0.15))
    weight_kg = float(data.get('weight_kg', 70.0))
    height_m = float(data.get('height_m', 1.75))
    bmi = weight_kg / (height_m ** 2)
    body_fat = (1.20 * bmi) + (0.23 * 30) - 5.4
    body_fat = max(5, min(50, body_fat))
    return {
        'model': 'Body Fat Estimator',
        'body_fat_percentage': round(body_fat, 1),
        'category': 'Athletic' if body_fat < 20 else 'Average' if body_fat < 30 else 'High',
        'lean_mass_kg': round(weight_kg * (1 - body_fat / 100), 1),
        'processing_time_ms': round(random.uniform(50, 150), 2)
    }

def bmr_calculator(data):
    time.sleep(random.uniform(0.05, 0.15))
    weight_kg = float(data.get('weight_kg', 70.0))
    height_m = float(data.get('height_m', 1.75))
    height_cm = height_m * 100
    bmr = (10 * weight_kg) + (6.25 * height_cm) - (5 * 30) + 5
    return {
        'model': 'BMR Calculator',
        'bmr_calories': round(bmr, 0),
        'sedentary': round(bmr * 1.2, 0),
        'moderate_activity': round(bmr * 1.55, 0),
        'very_active': round(bmr * 1.9, 0),
        'processing_time_ms': round(random.uniform(50, 150), 2)
    }

def ideal_weight_predictor(data):
    time.sleep(random.uniform(0.05, 0.15))
    height_m = float(data.get('height_m', 1.75))
    ideal_weight = 48 + 2.7 * (height_m * 100 - 152.4) / 2.54
    ideal_weight = max(45, min(120, ideal_weight))
    return {
        'model': 'Ideal Weight Predictor',
        'ideal_weight_kg': round(ideal_weight, 1),
        'healthy_range_min': round(ideal_weight * 0.9, 1),
        'healthy_range_max': round(ideal_weight * 1.1, 1),
        'processing_time_ms': round(random.uniform(50, 150), 2)
    }

def health_risk_assessor(data):
    time.sleep(random.uniform(0.05, 0.15))
    weight_kg = float(data.get('weight_kg', 70.0))
    height_m = float(data.get('height_m', 1.75))
    bmi = weight_kg / (height_m ** 2)
    if bmi < 18.5: risk_score = 30
    elif bmi < 25: risk_score = 10
    elif bmi < 30: risk_score = 40
    else: risk_score = 70
    return {
        'model': 'Health Risk Assessor',
        'risk_score': risk_score,
        'risk_level': 'Low' if risk_score < 30 else 'Moderate' if risk_score < 50 else 'High',
        'recommendations': ['Maintain healthy diet', 'Regular exercise', 'Annual checkup'],
        'processing_time_ms': round(random.uniform(50, 150), 2)
    }

# ============================================================================
# GROUP 4: TABULAR CLASSIFICATION - FLORA
# Input: sepal_length, sepal_width, petal_length, petal_width (floats)
# ============================================================================

def iris_classifier(data):
    time.sleep(random.uniform(0.05, 0.2))
    petal_length = float(data.get('petal_length', 4.0))
    if petal_length < 2.5: species = 'setosa'
    elif petal_length < 5.0: species = 'versicolor'
    else: species = 'virginica'
    return {
        'model': 'Iris Classifier',
        'prediction': species,
        'confidence': round(random.uniform(0.85, 0.98), 3),
        'processing_time_ms': round(random.uniform(50, 200), 2)
    }

def flower_type_classifier(data):
    time.sleep(random.uniform(0.05, 0.2))
    prediction = random.choice(['Rose', 'Tulip', 'Sunflower', 'Daisy', 'Lily'])
    return {
        'model': 'Flower Type Classifier',
        'prediction': prediction,
        'confidence': round(random.uniform(0.82, 0.96), 3),
        'color_prediction': random.choice(['Red', 'Yellow', 'White', 'Pink', 'Purple']),
        'processing_time_ms': round(random.uniform(50, 200), 2)
    }

def plant_species_identifier(data):
    time.sleep(random.uniform(0.05, 0.2))
    prediction = random.choice(['Ficus', 'Monstera', 'Pothos', 'Snake Plant', 'Peace Lily'])
    return {
        'model': 'Plant Species Identifier',
        'prediction': prediction,
        'confidence': round(random.uniform(0.79, 0.94), 3),
        'care_difficulty': random.choice(['Easy', 'Moderate', 'Difficult']),
        'processing_time_ms': round(random.uniform(60, 220), 2)
    }

def botanical_classifier(data):
    time.sleep(random.uniform(0.05, 0.2))
    prediction = random.choice(['Rosaceae', 'Asteraceae', 'Fabaceae', 'Lamiaceae', 'Solanaceae'])
    return {
        'model': 'Botanical Classifier',
        'family': prediction,
        'confidence': round(random.uniform(0.81, 0.95), 3),
        'genus_count': random.randint(50, 500),
        'processing_time_ms': round(random.uniform(50, 200), 2)
    }

def flora_recognition(data):
    time.sleep(random.uniform(0.05, 0.2))
    prediction = random.choice(['Flowering Plant', 'Conifer', 'Fern', 'Succulent', 'Grass'])
    return {
        'model': 'Flora Recognition',
        'category': prediction,
        'confidence': round(random.uniform(0.83, 0.97), 3),
        'edible': random.choice([True, False]),
        'processing_time_ms': round(random.uniform(50, 200), 2)
    }

# ============================================================================
# GROUP 5: FRAUD DETECTION - TRANSACTIONAL
# Input: amount (float), merchant_category (string), location (string), timestamp (string)
# ============================================================================

def fraud_detector(data):
    time.sleep(random.uniform(0.05, 0.2))
    amount = float(data.get('amount', 100.0))
    fraud_score = random.uniform(-0.1, 0.2)
    if amount > 1000: fraud_score += 0.3
    if data.get('location') == 'international': fraud_score += 0.2
    fraud_score = max(0.0, min(1.0, fraud_score))
    return {
        'model': 'Fraud Detector',
        'is_fraud': fraud_score > 0.5,
        'fraud_probability': round(fraud_score, 3),
        'risk_level': 'High' if fraud_score > 0.7 else 'Medium' if fraud_score > 0.4 else 'Low',
        'processing_time_ms': round(random.uniform(50, 200), 2)
    }

def credit_card_fraud(data):
    time.sleep(random.uniform(0.05, 0.2))
    amount = float(data.get('amount', 100.0))
    fraud_score = random.uniform(0.1, 0.9)
    if amount > 2000: fraud_score = min(fraud_score + 0.2, 1.0)
    return {
        'model': 'Credit Card Fraud Detector',
        'is_fraud': fraud_score > 0.55,
        'fraud_score': round(fraud_score, 3),
        'decision': 'Block' if fraud_score > 0.8 else 'Review' if fraud_score > 0.5 else 'Approve',
        'processing_time_ms': round(random.uniform(50, 220), 2)
    }

def payment_anomaly_detector(data):
    time.sleep(random.uniform(0.05, 0.2))
    anomaly_score = random.uniform(0.0, 1.0)
    return {
        'model': 'Payment Anomaly Detector',
        'is_anomaly': anomaly_score > 0.6,
        'anomaly_score': round(anomaly_score, 3),
        'deviation_percentage': round(random.uniform(0, 150), 1),
        'processing_time_ms': round(random.uniform(40, 180), 2)
    }

def transaction_risk_scorer(data):
    time.sleep(random.uniform(0.05, 0.2))
    amount = float(data.get('amount', 100.0))
    risk_score = random.uniform(0, 100)
    if amount > 5000: risk_score = min(risk_score + 30, 100)
    return {
        'model': 'Transaction Risk Scorer',
        'risk_score': round(risk_score, 1),
        'risk_band': 'Very High' if risk_score > 80 else 'High' if risk_score > 60 else 'Medium' if risk_score > 40 else 'Low',
        'recommended_action': 'Deny' if risk_score > 80 else 'Manual Review' if risk_score > 60 else 'Approve',
        'processing_time_ms': round(random.uniform(50, 200), 2)
    }

def financial_fraud_classifier(data):
    time.sleep(random.uniform(0.05, 0.2))
    prediction = random.choice(['Card Fraud', 'Identity Theft', 'Account Takeover', 'Legitimate', 'Suspicious'])
    return {
        'model': 'Financial Fraud Classifier',
        'fraud_type': prediction,
        'confidence': round(random.uniform(0.75, 0.95), 3),
        'requires_investigation': prediction != 'Legitimate',
        'processing_time_ms': round(random.uniform(60, 240), 2)
    }

# ============================================================================
# API ENDPOINTS
# ============================================================================

def _handle(fn, name, endpoint):
    start = time.time()
    try:
        data = request.get_json(force=True, silent=True) or {}
        result = fn(data)
        log_execution(name, endpoint, 'success', start)
        return jsonify(result), 200
    except Exception as e:
        log_execution(name, endpoint, 'error', start)
        return jsonify({'error': str(e)}), 500

# Group 1
@app.route('/api/v1/vision/chest-xray', methods=['POST'])
def api_chest_xray():
    return _handle(chest_xray_classifier, 'Chest X-Ray Classifier', '/api/v1/vision/chest-xray')

@app.route('/api/v1/vision/pneumonia', methods=['POST'])
def api_pneumonia():
    return _handle(pneumonia_detector, 'Pneumonia Detector', '/api/v1/vision/pneumonia')

@app.route('/api/v1/vision/covid19', methods=['POST'])
def api_covid19():
    return _handle(covid19_screener, 'COVID-19 Screener', '/api/v1/vision/covid19')

@app.route('/api/v1/vision/lung-nodule', methods=['POST'])
def api_lung_nodule():
    return _handle(lung_nodule_detector, 'Lung Nodule Detector', '/api/v1/vision/lung-nodule')

@app.route('/api/v1/vision/tuberculosis', methods=['POST'])
def api_tuberculosis():
    return _handle(tuberculosis_classifier, 'Tuberculosis Classifier', '/api/v1/vision/tuberculosis')

# Group 2
@app.route('/api/v1/nlp/ecommerce-sentiment', methods=['POST'])
def api_ecommerce_sentiment():
    return _handle(ecommerce_sentiment, 'E-commerce Sentiment', '/api/v1/nlp/ecommerce-sentiment')

@app.route('/api/v1/nlp/twitter-sentiment', methods=['POST'])
def api_twitter_sentiment():
    return _handle(twitter_sentiment, 'Twitter Sentiment', '/api/v1/nlp/twitter-sentiment')

@app.route('/api/v1/nlp/product-review', methods=['POST'])
def api_product_review():
    return _handle(product_review_classifier, 'Product Review Classifier', '/api/v1/nlp/product-review')

@app.route('/api/v1/nlp/customer-feedback', methods=['POST'])
def api_customer_feedback():
    return _handle(customer_feedback_analyzer, 'Customer Feedback Analyzer', '/api/v1/nlp/customer-feedback')

@app.route('/api/v1/nlp/social-media', methods=['POST'])
def api_social_media():
    return _handle(social_media_sentiment, 'Social Media Sentiment', '/api/v1/nlp/social-media')

# Group 3
@app.route('/api/v1/health/bmi', methods=['POST'])
def api_bmi():
    return _handle(bmi_calculator, 'BMI Calculator', '/api/v1/health/bmi')

@app.route('/api/v1/health/body-fat', methods=['POST'])
def api_body_fat():
    return _handle(body_fat_estimator, 'Body Fat Estimator', '/api/v1/health/body-fat')

@app.route('/api/v1/health/bmr', methods=['POST'])
def api_bmr():
    return _handle(bmr_calculator, 'BMR Calculator', '/api/v1/health/bmr')

@app.route('/api/v1/health/ideal-weight', methods=['POST'])
def api_ideal_weight():
    return _handle(ideal_weight_predictor, 'Ideal Weight Predictor', '/api/v1/health/ideal-weight')

@app.route('/api/v1/health/risk-assessment', methods=['POST'])
def api_health_risk():
    return _handle(health_risk_assessor, 'Health Risk Assessor', '/api/v1/health/risk-assessment')

# Group 4
@app.route('/api/v1/classification/iris', methods=['POST'])
def api_iris():
    return _handle(iris_classifier, 'Iris Classifier', '/api/v1/classification/iris')

@app.route('/api/v1/classification/flower', methods=['POST'])
def api_flower():
    return _handle(flower_type_classifier, 'Flower Type Classifier', '/api/v1/classification/flower')

@app.route('/api/v1/classification/plant', methods=['POST'])
def api_plant():
    return _handle(plant_species_identifier, 'Plant Species Identifier', '/api/v1/classification/plant')

@app.route('/api/v1/classification/botanical', methods=['POST'])
def api_botanical():
    return _handle(botanical_classifier, 'Botanical Classifier', '/api/v1/classification/botanical')

@app.route('/api/v1/classification/flora', methods=['POST'])
def api_flora():
    return _handle(flora_recognition, 'Flora Recognition', '/api/v1/classification/flora')

# Group 5
@app.route('/api/v1/fraud/transaction', methods=['POST'])
def api_fraud_transaction():
    return _handle(fraud_detector, 'Fraud Detector', '/api/v1/fraud/transaction')

@app.route('/api/v1/fraud/credit-card', methods=['POST'])
def api_credit_card():
    return _handle(credit_card_fraud, 'Credit Card Fraud', '/api/v1/fraud/credit-card')

@app.route('/api/v1/fraud/anomaly', methods=['POST'])
def api_anomaly():
    return _handle(payment_anomaly_detector, 'Payment Anomaly Detector', '/api/v1/fraud/anomaly')

@app.route('/api/v1/fraud/risk-scorer', methods=['POST'])
def api_risk_scorer():
    return _handle(transaction_risk_scorer, 'Transaction Risk Scorer', '/api/v1/fraud/risk-scorer')

@app.route('/api/v1/fraud/classifier', methods=['POST'])
def api_fraud_classifier():
    return _handle(financial_fraud_classifier, 'Financial Fraud Classifier', '/api/v1/fraud/classifier')

# ============================================================================
# UTILITY ENDPOINTS
# ============================================================================

def log_execution(model, endpoint, status, start_time):
    execution_log.append({
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'model': model,
        'endpoint': endpoint,
        'status': status,
        'duration': round((time.time() - start_time) * 1000, 2)
    })
    if len(execution_log) > 200:
        execution_log.pop(0)

@app.route('/api/v1/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'healthy',
        'models': 25,
        'groups': 5,
        'total_requests': len(execution_log),
        'timestamp': datetime.now().isoformat()
    }), 200

@app.route('/', methods=['GET'])
def root():
    return jsonify({
        'service': 'INESDATA ML Model Server',
        'models': 25,
        'groups': 5,
        'status': 'healthy',
        'endpoints': {
            'health': '/api/v1/health',
            'group1_vision': ['/api/v1/vision/chest-xray', '/api/v1/vision/pneumonia', '/api/v1/vision/covid19', '/api/v1/vision/lung-nodule', '/api/v1/vision/tuberculosis'],
            'group2_nlp': ['/api/v1/nlp/ecommerce-sentiment', '/api/v1/nlp/twitter-sentiment', '/api/v1/nlp/product-review', '/api/v1/nlp/customer-feedback', '/api/v1/nlp/social-media'],
            'group3_health': ['/api/v1/health/bmi', '/api/v1/health/body-fat', '/api/v1/health/bmr', '/api/v1/health/ideal-weight', '/api/v1/health/risk-assessment'],
            'group4_flora': ['/api/v1/classification/iris', '/api/v1/classification/flower', '/api/v1/classification/plant', '/api/v1/classification/botanical', '/api/v1/classification/flora'],
            'group5_fraud': ['/api/v1/fraud/transaction', '/api/v1/fraud/credit-card', '/api/v1/fraud/anomaly', '/api/v1/fraud/risk-scorer', '/api/v1/fraud/classifier']
        }
    }), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
