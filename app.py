from flask import Flask, request, jsonify, Response
import requests
import os
from threading import Lock
import json
import time

app = Flask(__name__)

# File to store the tunnel URL
URL_FILE = "/tmp/tunnel_url.txt"
# Lock for thread-safe file operations
file_lock = Lock()
# Flag to indicate URL updates
url_updated = False

def read_tunnel_url():
    """Read the tunnel URL from file."""
    try:
        with file_lock:
            if os.path.exists(URL_FILE):
                with open(URL_FILE, 'r') as f:
                    return f.read().strip()
    except Exception as e:
        print(f"Error reading URL file: {e}")
    return None

def write_tunnel_url(url):
    """Write the tunnel URL to file."""
    try:
        with file_lock:
            with open(URL_FILE, 'w') as f:
                f.write(url)
        return True
    except Exception as e:
        print(f"Error writing URL file: {e}")
        return False

def validate_request_data(data):
    """Validate the request data for the API."""
    try:
        if not isinstance(data, dict):
            return False, "Request data must be a JSON object"
        
        required_fields = ['model', 'prompt']
        for field in required_fields:
            if field not in data:
                return False, f"Missing required field: {field}"
        
        if not isinstance(data['prompt'], str):
            return False, "Prompt must be a string"
            
        return True, None
    except Exception as e:
        return False, f"Validation error: {str(e)}"

@app.route('/update_tunnel', methods=['POST'])
def update_tunnel():
    """Receive the latest tunnel URL from the GitHub Actions script."""
    global url_updated
    
    data = request.json
    if 'tunnel_url' in data:
        tunnel_url = data['tunnel_url'].rstrip('/')
        if write_tunnel_url(tunnel_url):
            url_updated = True
            return jsonify({
                "message": "Tunnel URL updated",
                "tunnel_url": tunnel_url
            }), 200
        return jsonify({"error": "Failed to save tunnel URL"}), 500
    return jsonify({"error": "Missing 'tunnel_url' in request"}), 400

@app.route('/proxy/', defaults={'endpoint': ''}, methods=['GET', 'POST'])
@app.route('/proxy/<path:endpoint>', methods=['GET', 'POST'])
def proxy_request(endpoint):
    """Forward GET or POST requests to the latest tunnel URL."""
    global url_updated
    
    # Read and validate tunnel URL
    tunnel_url = read_tunnel_url()
    if not tunnel_url:
        return jsonify({"error": "Tunnel URL not set"}), 503

    # Handle URL update flag
    if url_updated:
        url_updated = False
        print(f"Using new tunnel URL: {tunnel_url}")

    # Build target URL
    full_url = tunnel_url.rstrip('/') + '/' + endpoint.lstrip('/')
    if not endpoint:
        full_url = full_url.rstrip('/')

    try:
        # Process request headers
        headers = {
            key: value for key, value in request.headers.items()
            if key.lower() not in ['host', 'content-length']
        }
        
        # Ensure proper content type for JSON
        if request.is_json:
            headers['Content-Type'] = 'application/json'

        # Handle POST request with validation
        if request.method == 'POST':
            try:
                request_data = request.get_json()
                is_valid, error_message = validate_request_data(request_data)
                
                if not is_valid:
                    return jsonify({
                        "error": error_message,
                        "status": "validation_error"
                    }), 400

                print(f"Sending POST request to {full_url}")
                print(f"Request data: {json.dumps(request_data)}")
                
                # Add retry logic
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        response = requests.post(
                            full_url,
                            json=request_data,
                            headers=headers,
                            timeout=30
                        )
                        
                        print(f"Response status: {response.status_code}")
                        print(f"Response text: {response.text[:200]}...")  # Log first 200 chars
                        
                        # Check if response is valid JSON
                        try:
                            response_data = response.json()
                            return jsonify(response_data), response.status_code
                        except json.JSONDecodeError:
                            return Response(
                                response.text,
                                status=response.status_code,
                                content_type=response.headers.get('content-type', 'text/plain')
                            )
                            
                    except requests.RequestException as e:
                        if attempt == max_retries - 1:
                            raise
                        print(f"Retry {attempt + 1}/{max_retries} after error: {str(e)}")
                        time.sleep(1)  # Wait before retry
                        
            except json.JSONDecodeError:
                return jsonify({
                    "error": "Invalid JSON in request body",
                    "status": "json_error"
                }), 400

        # Handle GET request
        else:
            response = requests.get(
                full_url,
                params=request.args,
                headers=headers,
                timeout=30
            )
            return Response(
                response.text,
                status=response.status_code,
                content_type=response.headers.get('content-type', 'text/plain')
            )

    except requests.Timeout:
        return jsonify({
            "error": "Request timed out",
            "status": "timeout_error"
        }), 504
        
    except requests.RequestException as e:
        return jsonify({
            "error": f"Request failed: {str(e)}",
            "status": "connection_error"
        }), 502
        
    except Exception as e:
        return jsonify({
            "error": f"Server error: {str(e)}",
            "status": "server_error"
        }), 500

@app.route('/status', methods=['GET'])
def get_status():
    """Get the current tunnel URL and update status."""
    tunnel_url = read_tunnel_url()
    return jsonify({
        "current_url": tunnel_url,
        "url_updated": url_updated,
        "is_url_valid": bool(tunnel_url and tunnel_url.startswith('http'))
    }), 200

if __name__ == '__main__':
    if not os.path.exists(URL_FILE):
        write_tunnel_url("")
    
    app.run(host='0.0.0.0', port=5000, debug=True)
