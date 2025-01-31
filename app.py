from flask import Flask, request, jsonify, Response
import requests
import os
from threading import Lock
import json
import time

app = Flask(__name__)

# Use /tmp directory for Vercel environment
URL_FILE = "/tmp/tunnel_url.txt"
file_lock = Lock()
url_updated = False

def read_tunnel_url():
    """Read the tunnel URL from file."""
    try:
        with file_lock:
            if os.path.exists(URL_FILE):
                with open(URL_FILE, 'r') as f:
                    return f.read().strip()
            return None
    except Exception as e:
        print(f"Error reading URL file: {e}")
        return None

def write_tunnel_url(url):
    """Write the tunnel URL to file."""
    try:
        os.makedirs(os.path.dirname(URL_FILE), exist_ok=True)
        
        with file_lock:
            with open(URL_FILE, 'w') as f:
                f.write(url)
            if os.path.exists(URL_FILE):
                with open(URL_FILE, 'r') as f:
                    if f.read().strip() == url:
                        return True
        return False
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
    
    try:
        data = request.get_json()
        if not data or 'tunnel_url' not in data:
            return jsonify({"error": "Missing 'tunnel_url' in request"}), 400

        tunnel_url = data['tunnel_url'].rstrip('/')
        
        if not tunnel_url.startswith(('http://', 'https://')):
            return jsonify({"error": "Invalid URL format"}), 400

        if write_tunnel_url(tunnel_url):
            url_updated = True
            saved_url = read_tunnel_url()
            if saved_url == tunnel_url:
                return jsonify({
                    "message": "Tunnel URL updated successfully",
                    "tunnel_url": tunnel_url,
                    "file_path": URL_FILE
                }), 200
            else:
                return jsonify({
                    "error": "URL verification failed",
                    "saved_url": saved_url,
                    "intended_url": tunnel_url
                }), 500
        else:
            file_exists = os.path.exists(URL_FILE)
            file_perms = ""
            dir_perms = ""
            try:
                if file_exists:
                    file_perms = oct(os.stat(URL_FILE).st_mode)[-3:]
                dir_perms = oct(os.stat(os.path.dirname(URL_FILE)).st_mode)[-3:]
            except Exception as e:
                print(f"Error checking permissions: {e}")

            return jsonify({
                "error": "Failed to save tunnel URL",
                "details": {
                    "file_exists": file_exists,
                    "file_path": URL_FILE,
                    "file_permissions": file_perms,
                    "directory_permissions": dir_perms
                }
            }), 500

    except Exception as e:
        return jsonify({
            "error": "Server error while updating tunnel URL",
            "details": str(e)
        }), 500

@app.route('/proxy/', defaults={'endpoint': ''}, methods=['GET', 'POST'])
@app.route('/proxy/<path:endpoint>', methods=['GET', 'POST'])
def proxy_request(endpoint):
    """Forward GET or POST requests to the latest tunnel URL."""
    global url_updated
    
    tunnel_url = read_tunnel_url()
    if not tunnel_url:
        return jsonify({"error": "Tunnel URL not set"}), 503

    if url_updated:
        url_updated = False
        print(f"Using new tunnel URL: {tunnel_url}")

    full_url = tunnel_url.rstrip('/') + '/' + endpoint.lstrip('/')
    if not endpoint:
        full_url = full_url.rstrip('/')

    try:
        headers = {
            key: value for key, value in request.headers.items()
            if key.lower() not in ['host', 'content-length']
        }
        
        if request.is_json:
            headers['Content-Type'] = 'application/json'

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
                        print(f"Response text: {response.text[:200]}...")
                        
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
                        time.sleep(1)
                        
            except json.JSONDecodeError:
                return jsonify({
                    "error": "Invalid JSON in request body",
                    "status": "json_error"
                }), 400

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
    os.makedirs(os.path.dirname(URL_FILE), exist_ok=True)
    
    if not os.path.exists(URL_FILE):
        try:
            with open(URL_FILE, 'w') as f:
                f.write("")
        except Exception as e:
            print(f"Error creating URL file: {e}")
    
    app.run(host='0.0.0.0', port=5000, debug=True)
