from flask import Flask, request, jsonify
import requests
import threading

app = Flask(__name__)

# Use an in-memory variable for storing the tunnel URL (since Vercel is stateless)
tunnel_url = None
lock = threading.Lock()

def get_tunnel_url():
    """Safely get the stored tunnel URL"""
    with lock:
        return tunnel_url

def set_tunnel_url(url):
    """Safely update the stored tunnel URL"""
    global tunnel_url
    with lock:
        tunnel_url = url
    print(f"✅ Updated Tunnel URL: {tunnel_url}")

@app.route('/update_tunnel', methods=['POST'])
def update_tunnel():
    """Receive and update the latest tunnel URL"""
    data = request.json
    if 'tunnel_url' in data:
        set_tunnel_url(data['tunnel_url'].rstrip('/'))
        return jsonify({"message": "Tunnel URL updated", "tunnel_url": tunnel_url}), 200
    return jsonify({"error": "Missing 'tunnel_url'"}), 400

@app.route('/proxy/', defaults={'endpoint': ''}, methods=['GET', 'POST'])
@app.route('/proxy/<path:endpoint>', methods=['GET', 'POST'])
def proxy_request(endpoint):
    """Proxy requests to the latest tunnel URL"""
    current_tunnel = get_tunnel_url()
    if not current_tunnel:
        return jsonify({"error": "Tunnel URL not set"}), 503

    full_url = f"{current_tunnel}/{endpoint}"
    print(f"🔀 Proxying request to: {full_url}")

    try:
        headers = {key: value for key, value in request.headers.items() if key.lower() != 'host'}
        headers.setdefault("Content-Type", "application/json")

        if request.method == 'GET':
            response = requests.get(full_url, headers=headers, params=request.args, stream=True, verify=False)
        else:  # POST request
            response = requests.post(full_url, headers=headers, data=request.get_data(), stream=True, verify=False)

        return (response.raw.read(), response.status_code, dict(response.headers))

    except requests.RequestException as e:
        return jsonify({"error": f"Proxy request failed: {str(e)}"}), 502

@app.route('/status', methods=['GET'])
def get_status():
    """Return the current tunnel URL"""
    return jsonify({"current_url": get_tunnel_url(), "is_url_valid": bool(get_tunnel_url())}), 200

# For Vercel compatibility
def handler(event, context):
    return app(event, context)

if __name__ == '__main__':
    print("🚀 Running Vercel-compatible server...")
    app.run(host='0.0.0.0', port=5000)
