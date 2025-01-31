from flask import Flask, request, Response
import requests
import os
from threading import Lock

app = Flask(__name__)

# File to store the latest tunnel URL
URL_FILE = "/tmp/tunnel_url.txt"
file_lock = Lock()

def read_tunnel_url():
    """Read the latest tunnel URL from file."""
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
            return {"error": "Missing 'tunnel_url' in request"}, 400

        tunnel_url = data['tunnel_url'].rstrip('/')
        if not tunnel_url.startswith(('http://', 'https://')):
            return {"error": "Invalid URL format"}, 400

        if write_tunnel_url(tunnel_url):
            return {"message": "Tunnel URL updated successfully", "tunnel_url": tunnel_url}, 200
        else:
            return {"error": "Failed to save tunnel URL"}, 500
    except Exception as e:
        return {"error": f"Server error: {str(e)}"}, 500

@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
@app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
def proxy(path):
    """Forward any request to the dynamically stored tunnel URL."""
    tunnel_url = read_tunnel_url()
    if not tunnel_url:
        return {"error": "Tunnel URL not set"}, 503

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
            allow_redirects=False  # Prevent unwanted redirects
        )

        # Build the response
        response = Response(resp.content, status=resp.status_code)

        # Forward headers, excluding certain ones
        for key, value in resp.headers.items():
            if key.lower() not in ["content-encoding", "transfer-encoding"]:
                response.headers[key] = value

        return response

    except requests.Timeout:
        return {"error": "Request timed out"}, 504
    except requests.RequestException as e:
        return {"error": f"Request failed: {str(e)}"}, 502
    except Exception as e:
        return {"error": f"Server error: {str(e)}"}, 500

@app.route('/status', methods=['GET'])
def get_status():
    """Get the current tunnel URL status."""
    tunnel_url = read_tunnel_url()
    return {"current_url": tunnel_url, "is_url_valid": bool(tunnel_url and tunnel_url.startswith('http'))}, 200

if __name__ == '__main__':
    os.makedirs(os.path.dirname(URL_FILE), exist_ok=True)
    app.run(host='0.0.0.0', port=5000, debug=True)
