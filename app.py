from flask import Flask, request, Response, jsonify, stream_with_context
import requests
import json
import logging
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Store the target URL
TARGET_URL = "https://example.com"  # Default URL

@app.route('/update_tunnel', methods=['POST'])
def set_url():
    """Update the target URL dynamically."""
    global TARGET_URL
    data = request.get_json()

    if not data or 'tunnel_url' not in data:
        return jsonify({"error": "Missing 'tunnel_url' in request body"}), 400

    TARGET_URL = data['tunnel_url'].rstrip('/')  # Normalize URL
    try:
        requests.head(TARGET_URL, timeout=5)  # Validate URL
        logger.info(f"Target URL updated to: {TARGET_URL}")
        return jsonify({"message": f"Target URL updated to {TARGET_URL}"}), 200
    except requests.exceptions.RequestException as e:
        logger.error(f"Invalid target URL: {e}")
        return jsonify({"error": f"Invalid URL: {e}"}), 400

@app.route('/status', methods=['GET'])
def get_status():
    """Return the currently saved target URL and its validity."""
    is_valid = False
    try:
        requests.head(TARGET_URL, timeout=5)
        is_valid = True
    except requests.exceptions.RequestException:
        pass

    return jsonify({
        "current_url": TARGET_URL,
        "is_url_valid": is_valid
    }), 200

@app.route('/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'])
def proxy(path):
    """Forward requests to the target URL and return JSON-formatted streamed responses."""
    if not TARGET_URL:
        return jsonify({"error": "Target URL is not set"}), 500

    try:
        full_url = f"{TARGET_URL}/{path}"
        logger.info(f"Proxying request to: {full_url}")

        headers = {k: v for k, v in request.headers.items() if k.lower() not in ['host', 'content-length', 'connection']}
        headers.update({
            'X-Forwarded-For': request.remote_addr,
            'X-Forwarded-Proto': request.scheme,
            'X-Forwarded-Host': request.headers.get('host', '')
        })

        upstream_response = requests.request(
            method=request.method,
            url=full_url,
            headers=headers,
            data=request.get_data(),
            cookies=request.cookies,
            stream=True,
            timeout=30
        )

        def generate():
            buffer = b""
            for chunk in upstream_response.iter_content(chunk_size=8192):
                if chunk:
                    buffer += chunk
                    try:
                        # Attempt to decode and format as JSON
                        decoded_chunk = buffer.decode('utf-8')
                        json_data = json.loads(decoded_chunk)
                        yield json.dumps(json_data, indent=4).encode()  # Pretty print JSON
                        buffer = b""  # Reset buffer after successful JSON parsing
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        pass  # Keep accumulating chunks until we have valid JSON

        return Response(
            stream_with_context(generate()),
            status=upstream_response.status_code,
            headers={k: v for k, v in upstream_response.headers.items() if k.lower() not in ['transfer-encoding', 'content-encoding', 'content-length']},
            content_type='application/json'
        )

    except requests.RequestException as e:
        logger.error(f"Proxy error: {e}")
        return jsonify({"error": str(e)}), 502

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
