from flask import Flask, request, Response, stream_with_context, jsonify
import requests
import os
from threading import Lock
import json

app = Flask(__name__)

# File to store the latest tunnel URL
URL_FILE = "/tmp/tunnel_url.txt"
file_lock = Lock()
current_url = None  # In-memory cache of the URL

def read_tunnel_url():
    """Read the latest tunnel URL from file and cache it."""
    global current_url
    try:
        with file_lock:
            if current_url:  # Return cached URL if available
                return current_url
            if os.path.exists(URL_FILE):
                with open(URL_FILE, 'r') as f:
                    current_url = f.read().strip()
                return current_url
            return None
    except Exception as e:
        print(f"Error reading URL file: {e}")
        return current_url  # Return cached URL even if file read fails

def write_tunnel_url(url):
    """Write the tunnel URL to file and update cache."""
    global current_url
    try:
        os.makedirs(os.path.dirname(URL_FILE), exist_ok=True)
        with file_lock:
            with open(URL_FILE, 'w') as f:
                f.write(url)
            current_url = url  # Update the cache
        return True
    except Exception as e:
        print(f"Error writing URL file: {e}")
        return False

@app.route('/update_tunnel', methods=['POST'])
def update_tunnel():
    """Update the tunnel URL dynamically."""
    try:
        data = request.get_json()
        if not data or 'tunnel_url' not in data:
            return jsonify({"error": "Missing 'tunnel_url' in request"}), 400

        tunnel_url = data['tunnel_url'].rstrip('/')
        if not tunnel_url.startswith(('http://', 'https://')):
            return jsonify({"error": "Invalid URL format"}), 400

        if write_tunnel_url(tunnel_url):
            return jsonify({"message": "Tunnel URL updated successfully", "tunnel_url": tunnel_url}), 200
        else:
            return jsonify({"error": "Failed to save tunnel URL"}), 500
    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500

def extract_and_assemble_response(response):
    """Extract 'response' fields, arrange them, and return the readable text."""
    full_response = []
    
    for line in response.iter_lines():
        if line:
            try:
                data = json.loads(line)
                if "response" in data:
                    full_response.append(data["response"])
                if data.get("done", False):  # Stop collecting when done
                    break
            except json.JSONDecodeError:
                continue

    return "".join(full_response).strip()

@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
@app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
def proxy(path):
    """Forward any request to the dynamically stored tunnel URL and process the response."""
    tunnel_url = read_tunnel_url()
    if not tunnel_url:
        return jsonify({"error": "Tunnel URL not set"}), 503

    # Construct the full URL
    url = f"{tunnel_url}/{path}"

    # Forward headers (excluding 'Host')
    headers = {key: value for key, value in request.headers.items() if key.lower() != "host"}

    # Forward cookies
    if request.cookies:
        headers["Cookie"] = "; ".join([f"{key}={value}" for key, value in request.cookies.items()])

    # Forward request body if needed
    data = request.get_data() if request.method in ["POST", "PUT", "PATCH"] else None

    try:
        # Send request to target URL
        resp = requests.request(
            method=request.method,
            url=url,
            headers=headers,
            data=data,
            params=request.args,
            cookies=request.cookies,
            stream=True,  # Enable streaming
            allow_redirects=False
        )

        # Extract and return formatted response
        final_response = extract_and_assemble_response(resp)
        return jsonify({"response": final_response})

    except requests.Timeout:
        return jsonify({"error": "Request timed out"}), 504
    except requests.RequestException as e:
        return jsonify({"error": f"Request failed: {str(e)}"}), 502
    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500

@app.route('/status', methods=['GET'])
def get_status():
    """Get the current tunnel URL status."""
    tunnel_url = read_tunnel_url()
    return jsonify({
        "current_url": tunnel_url,
        "is_url_valid": bool(tunnel_url and tunnel_url.startswith('http')),
        "cached": bool(current_url)
    }), 200

if __name__ == '__main__':
    # Initialize by reading the existing URL file if it exists
    read_tunnel_url()
    os.makedirs(os.path.dirname(URL_FILE), exist_ok=True)
    app.run(host='0.0.0.0', port=5000, debug=True)
