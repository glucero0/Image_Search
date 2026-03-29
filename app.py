import os
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import requests

base_dir = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.join(base_dir, 'templates')

app = Flask(__name__, template_folder=template_dir)
CORS(app)

def brave_image_search(query, api_key):
    url = "https://api.search.brave.com/res/v1/images/search"
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": api_key
    }
    params = {
        "q": query,
        "safesearch": "off",
        "count": 150
    }
    
    response = requests.get(url, headers=headers, params=params)
    
    if response.status_code == 403:
        raise Exception("Access Denied: Check your Brave API subscription.")
    if response.status_code != 200:
        raise Exception(f"Brave API error: {response.status_code}")
        
    return response.json().get('results', [])

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search():
    data = request.json
    query = data.get('query')
    api_key = data.get('apiKey')
    
    try:
        results = brave_image_search(query, api_key)
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)