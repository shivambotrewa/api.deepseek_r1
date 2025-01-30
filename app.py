from flask import Flask, request, jsonify
import requests
import os
from threading import Lock

app = Flask(__name__)

# File to store the tunnel URL
URL_FILE = "tunnel_url.txt"
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
        print(f"✅ Tunnel URL Updated: {url}")
        return True
    except Exception as e:
        print(f"Error writing URL file: {e}")
        return False

@app.route('/update_tunnel', methods=['POST'])
def update_tunnel():
    """Receive the latest tunnel URL from the GitHub Actions script."""
    global url_updated
    
    data = request.json
    if 'tunnel_url' in data:
        tunnel_url = data['tunnel_url'].rstrip('/')  # Remove trailing slash if present
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
    
    tunnel_url = read_tunnel_url()
    if not tunnel_url:
        return jsonify({"error": "Tunnel URL not set"}), 503

    if url_updated:
        url_updated = False
        print(f"🔄 Using updated tunnel URL: {tunnel_url}")

    # Build the target URL
    full_url = f"{tunnel_url.rstrip('/')}/{endpoint.lstrip('/')}"
    print(f"🔀 Proxying {request.method} request to: {full_url}")  

    try:
        headers = {key: value for key, value in request.headers.items() if key.lower() != 'host'}
        
        if 'Content-Type' not in headers:
            headers['Content-Type'] = 'application/json'

        if request.method == 'GET':
            response = requests.get(full_url, params=request.args, headers=headers, stream=True, verify=False)
        else:  # POST request
            print(f"📤 Forwarding POST data: {request.get_data().decode('utf-8')}")
            response = requests.post(full_url, data=request.get_data(), headers=headers, stream=True, verify=False)

        print(f"✅ Response status: {response.status_code}")

        return (
            response.raw.read(),
            response.status_code,
            dict(response.headers)
        )

    except requests.RequestException as e:
        error_msg = f"❌ Proxy request failed: {str(e)}"
        print(error_msg)
        return jsonify({
            "error": error_msg,
            "target_url": full_url,
            "method": request.method,
            "request_data": request.get_data().decode('utf-8')
        }), 502

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
    # Ensure the URL file exists
    if not os.path.exists(URL_FILE):
        write_tunnel_url("")
    
    app.run(host='0.0.0.0', port=5000, debug=True)
