from flask import Flask, request, jsonify, send_file, render_template_string
import yt_dlp
import os
import re
import uuid
import threading
import time
from pathlib import Path
from datetime import datetime, timedelta

app = Flask(__name__)

# Create downloads directory if it doesn't exist
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# Dictionary to track file expiration times
file_expiry = {}

def schedule_deletion(filename, delay_minutes=10):
    """Schedule a file for deletion after specified minutes"""
    def delete_file():
        time.sleep(delay_minutes * 60)
        file_path = DOWNLOAD_DIR / filename
        if file_path.exists():
            try:
                file_path.unlink()
                print(f"Deleted: {filename}")
                # Remove from expiry tracking
                if filename in file_expiry:
                    del file_expiry[filename]
            except Exception as e:
                print(f"Error deleting {filename}: {e}")
    
    expiry_time = datetime.now() + timedelta(minutes=delay_minutes)
    file_expiry[filename] = expiry_time
    thread = threading.Thread(target=delete_file, daemon=True)
    thread.start()
    return expiry_time

def cleanup_expired_files():
    """Remove expired files (for manual cleanup if needed)"""
    now = datetime.now()
    for filename, expiry_time in list(file_expiry.items()):
        if now >= expiry_time:
            file_path = DOWNLOAD_DIR / filename
            if file_path.exists():
                file_path.unlink()
                print(f"Cleaned up expired file: {filename}")
            del file_expiry[filename]

# HTML template for the web interface
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>YouTube Video Downloader</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 50px auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .container {
            background-color: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        h1 {
            color: #333;
        }
        input, select, button {
            margin: 10px 0;
            padding: 10px;
            width: 100%;
            font-size: 16px;
        }
        button {
            background-color: #ff0000;
            color: white;
            border: none;
            cursor: pointer;
        }
        button:hover {
            background-color: #cc0000;
        }
        .quality-option {
            margin: 10px 0;
        }
        .result {
            margin-top: 20px;
            padding: 10px;
            background-color: #e8f5e9;
            border-radius: 5px;
            display: none;
        }
        .error {
            background-color: #ffebee;
            color: #c62828;
        }
        .loading {
            display: none;
            margin-top: 20px;
            text-align: center;
        }
        .info {
            background-color: #e3f2fd;
            color: #1976d2;
            font-size: 12px;
            text-align: center;
            margin-top: 10px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>YouTube Video Downloader</h1>
        <p style="color: #666;">Files are automatically deleted after 10 minutes</p>
        <form id="downloadForm">
            <input type="text" id="url" placeholder="Enter YouTube URL" required>
            <select id="quality">
                <option value="best">Best Quality (Video + Audio)</option>
                <option value="bestvideo+bestaudio">Best Video + Best Audio</option>
                <option value="worst">Worst Quality</option>
                <option value="mp4">MP4 (720p or lower)</option>
                <option value="audio">Audio Only (MP3)</option>
                <option value="2160p">4K (2160p)</option>
                <option value="1440p">1440p</option>
                <option value="1080p">1080p</option>
                <option value="720p">720p</option>
                <option value="480p">480p</option>
                <option value="360p">360p</option>
            </select>
            <button type="submit">Download</button>
        </form>
        <div id="loading" class="loading">
            <p>Downloading... Please wait...</p>
        </div>
        <div id="result" class="result"></div>
        <div class="info">
            ⏱️ Files are automatically deleted 10 minutes after download
        </div>
    </div>

    <script>
        document.getElementById('downloadForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const url = document.getElementById('url').value;
            const quality = document.getElementById('quality').value;
            const resultDiv = document.getElementById('result');
            const loadingDiv = document.getElementById('loading');
            
            loadingDiv.style.display = 'block';
            resultDiv.style.display = 'none';
            resultDiv.className = 'result';
            
            try {
                const response = await fetch('/download', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ url: url, quality: quality })
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    resultDiv.innerHTML = `<strong>Success!</strong> File ready: <a href="/download-file/${data.filename}">Click here to download</a><br>
                    <small style="color: #666;">⚠️ File will be deleted in ${data.expires_in_minutes} minutes</small>`;
                    resultDiv.classList.add('result');
                } else {
                    resultDiv.innerHTML = `<strong>Error:</strong> ${data.error}`;
                    resultDiv.classList.add('error');
                }
                resultDiv.style.display = 'block';
            } catch (error) {
                resultDiv.innerHTML = `<strong>Error:</strong> ${error.message}`;
                resultDiv.classList.add('error');
                resultDiv.style.display = 'block';
            } finally {
                loadingDiv.style.display = 'none';
            }
        });
    </script>
</body>
</html>
'''

def get_format_code(quality):
    """Get yt-dlp format code based on quality selection"""
    format_map = {
        'best': 'best',
        'bestvideo+bestaudio': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'worst': 'worst',
        'mp4': 'best[ext=mp4]',
        'audio': 'bestaudio/best',
        '2160p': 'bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/best[height<=2160]',
        '1440p': 'bestvideo[height<=1440][ext=mp4]+bestaudio[ext=m4a]/best[height<=1440]',
        '1080p': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]',
        '720p': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]',
        '480p': 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]',
        '360p': 'bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360]'
    }
    return format_map.get(quality, 'best')

def sanitize_filename(filename):
    """Remove invalid characters from filename"""
    return re.sub(r'[<>:"/\\|?*]', '', filename)

@app.route('/')
def index():
    """Serve the main page"""
    return render_template_string(HTML_TEMPLATE)

@app.route('/download', methods=['POST'])
def download_video():
    """Download video with selected quality"""
    data = request.json
    url = data.get('url')
    quality = data.get('quality', 'best')
    expiry_minutes = data.get('expiry_minutes', 10)  # Allow custom expiry time
    
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    
    try:
        # Generate unique filename to avoid conflicts
        unique_id = str(uuid.uuid4())[:8]
        
        # Get format code
        format_code = get_format_code(quality)
        
        # Configure yt-dlp options
        ydl_opts = {
            'format': format_code,
            'outtmpl': str(DOWNLOAD_DIR / f'%(title)s_{unique_id}.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
        }
        
        # Add audio conversion for audio-only downloads
        if quality == 'audio':
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
            ydl_opts['outtmpl'] = str(DOWNLOAD_DIR / f'%(title)s_{unique_id}.%(ext)s')
        
        # Download the video
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            # Handle audio file extension change
            if quality == 'audio':
                filename = filename.rsplit('.', 1)[0] + '.mp3'
            
            # Get just the filename without path
            file_path = Path(filename)
            original_filename = sanitize_filename(f"{info['title']}_{unique_id}{file_path.suffix}")
            final_path = DOWNLOAD_DIR / original_filename
            
            # Rename if necessary
            if file_path.name != original_filename:
                file_path.rename(final_path)
            else:
                original_filename = file_path.name
        
        # Schedule deletion after specified minutes
        expiry_time = schedule_deletion(original_filename, expiry_minutes)
        
        return jsonify({
            'success': True,
            'filename': original_filename,
            'title': info['title'],
            'message': 'Download completed successfully',
            'expires_at': expiry_time.isoformat(),
            'expires_in_minutes': expiry_minutes
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download-file/<filename>')
def download_file(filename):
    """Serve the downloaded file"""
    file_path = DOWNLOAD_DIR / filename
    
    if not file_path.exists():
        return jsonify({'error': 'File not found or has been deleted (files are kept for 10 minutes only)'}), 404
    
    # Send file and it will be deleted automatically by the scheduled task
    return send_file(file_path, as_attachment=True)

@app.route('/info', methods=['POST'])
def get_video_info():
    """Get video information without downloading"""
    data = request.json
    url = data.get('url')
    
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Extract available formats
            formats = []
            for f in info.get('formats', []):
                if f.get('vcodec') != 'none' and f.get('height'):
                    formats.append({
                        'quality': f"{f.get('height', '?')}p",
                        'format_id': f['format_id'],
                        'ext': f.get('ext', 'unknown'),
                        'filesize': f.get('filesize', 0)
                    })
            
            return jsonify({
                'title': info.get('title'),
                'duration': info.get('duration'),
                'uploader': info.get('uploader'),
                'formats': formats[:10]  # Limit to first 10 formats
            })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/cleanup', methods=['POST'])
def cleanup():
    """Remove all downloaded files immediately"""
    try:
        deleted_count = 0
        for file in DOWNLOAD_DIR.iterdir():
            if file.is_file():
                file.unlink()
                deleted_count += 1
        file_expiry.clear()
        return jsonify({'message': f'Cleaned up {deleted_count} files'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/status', methods=['GET'])
def get_status():
    """Get status of current files"""
    files = []
    for filename, expiry_time in file_expiry.items():
        files.append({
            'filename': filename,
            'expires_at': expiry_time.isoformat(),
            'time_remaining_minutes': max(0, (expiry_time - datetime.now()).total_seconds() / 60)
        })
    
    return jsonify({
        'active_files_count': len(files),
        'files': files,
        'download_directory': str(DOWNLOAD_DIR)
    })

@app.route('/download-with-expiry', methods=['POST'])
def download_with_custom_expiry():
    """Download video with custom expiry time"""
    data = request.json
    url = data.get('url')
    quality = data.get('quality', 'best')
    expiry_minutes = data.get('expiry_minutes', 10)
    
    # Limit expiry between 1 and 60 minutes
    expiry_minutes = max(1, min(60, expiry_minutes))
    
    return download_video()  # Reuse the existing function

if __name__ == '__main__':
    print("=" * 50)
    print("YouTube Downloader Server with Auto-Deletion")
    print("=" * 50)
    print(f"Download directory: {DOWNLOAD_DIR.absolute()}")
    print("Files are automatically deleted after 10 minutes")
    print("Visit http://localhost:5000 to access the web interface")
    print("=" * 50)
    app.run(debug=True, host='0.0.0.0', port=5000)
