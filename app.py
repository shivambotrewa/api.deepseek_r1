from flask import Flask, request, Response, jsonify, stream_with_context
import requests
from urllib.parse import urljoin
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
    
    # Validate URL format
    try:
        TARGET_URL = data['tunnel_url'].rstrip('/')  # Remove trailing slashes
        requests.head(TARGET_URL)  # Test connection
        logger.info(f"Target URL updated to: {TARGET_URL}")
        return jsonify({"message": f"Target URL updated to {TARGET_URL}"}), 200
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to validate URL: {str(e)}")
        return jsonify({"error": f"Invalid URL: {str(e)}"}), 400

@app.route('/status', methods=['GET'])
def get_status():
    """Return the currently saved target URL and its validity."""
    is_valid = False
    try:
        if TARGET_URL:
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
    """Forward requests to the target URL and stream the response."""
    if not TARGET_URL:
        return jsonify({"error": "Target URL is not set"}), 500

    try:
        # Build the full URL using urljoin to handle paths correctly
        full_url = urljoin(TARGET_URL + '/', path)
        logger.debug(f"Proxying request to: {full_url}")

        # Forward the request headers except those that should be excluded
        excluded_headers = ['host', 'content-length', 'connection', 'content-encoding']
        headers = {
            key: value for key, value in request.headers.items()
            if key.lower() not in excluded_headers
        }

        # Add X-Forwarded headers
        headers['X-Forwarded-For'] = request.remote_addr
        headers['X-Forwarded-Proto'] = request.scheme
        headers['X-Forwarded-Host'] = request.headers.get('host', '')

        # Forward the request using streaming
        upstream_response = requests.request(
            method=request.method,
            url=full_url,
            headers=headers,
            data=request.get_data(),
            cookies=request.cookies,
            stream=True,
            timeout=30  # Add timeout to prevent hanging
        )

        # Filter response headers
        response_headers = {
            key: value for key, value in upstream_response.headers.items()
            if key.lower() not in ['transfer-encoding', 'content-encoding', 'content-length']
        }

        # Stream response from upstream to client
        def generate():
            try:
                for chunk in upstream_response.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
            except Exception as e:
                logger.error(f"Streaming error: {str(e)}")
                yield str(e).encode()

        return Response(
            stream_with_context(generate()),
            status=upstream_response.status_code,
            headers=response_headers,
            content_type=upstream_response.headers.get('content-type')
        )

    except requests.RequestException as e:
        logger.error(f"Proxy error: {str(e)}")
        return jsonify({"error": str(e)}), 502

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
