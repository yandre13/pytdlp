from flask import Flask, request, jsonify
from flask_cors import CORS
import yt_dlp
import logging
import re
import os
from urllib.parse import unquote
import time

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Permitir CORS para todas las rutas

# Configuración de yt-dlp
YDL_OPTS = {
    'format': 'best[height<=720]/best',  # Máximo 720p para mejor rendimiento
    'noplaylist': True,
    'extract_flat': False,
    'quiet': True,
    'no_warnings': True,
    'extractaudio': False,
    'audioformat': 'mp4',
    'outtmpl': '%(title)s.%(ext)s',
    'user_agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1'
}

def is_valid_youtube_url(url):
    """Valida si la URL es de YouTube"""
    youtube_patterns = [
        r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=[\w-]+',
        r'(?:https?://)?(?:www\.)?youtu\.be/[\w-]+',
        r'(?:https?://)?(?:www\.)?youtube\.com/embed/[\w-]+',
        r'(?:https?://)?(?:www\.)?youtube\.com/v/[\w-]+',
        r'(?:https?://)?(?:www\.)?youtube\.com/shorts/[\w-]+'
    ]
    
    return any(re.match(pattern, url, re.IGNORECASE) for pattern in youtube_patterns)

def clean_url(url):
    """Limpia y normaliza la URL"""
    # Decodificar URL
    url = unquote(url)
    
    # Agregar https si no tiene protocolo
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    return url

@app.route('/health', methods=['GET'])
def health_check():
    """Endpoint de salud para verificar que la API funciona"""
    return jsonify({
        'status': 'healthy',
        'message': 'YouTube Extraction API is running',
        'timestamp': time.time()
    })

@app.route('/extract/<path:url>', methods=['GET'])
def extract_video_info(url):
    """
    Extrae información del video de YouTube
    Parámetros:
    - url: URL del video de YouTube (codificada)
    """
    try:
        # Limpiar y validar URL
        clean_video_url = clean_url(url)
        logger.info(f"Procesando URL: {clean_video_url}")
        
        if not is_valid_youtube_url(clean_video_url):
            return jsonify({
                'error': 'invalid_url',
                'message': 'La URL proporcionada no es una URL válida de YouTube'
            }), 400
        
        # Extraer información del video
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            info = ydl.extract_info(clean_video_url, download=False)
            
            if not info:
                return jsonify({
                    'error': 'extraction_failed',
                    'message': 'No se pudo extraer información del video'
                }), 400
            
            # Buscar el mejor formato de video
            video_url = None
            formats = info.get('formats', [])
            
            # Priorizar formatos mp4 con buena calidad
            for fmt in formats:
                if (fmt.get('ext') == 'mp4' and 
                    fmt.get('vcodec') != 'none' and 
                    fmt.get('acodec') != 'none' and
                    fmt.get('height', 0) <= 720):
                    video_url = fmt.get('url')
                    break
            
            # Si no encontramos mp4 combinado, buscar el mejor disponible
            if not video_url and formats:
                best_format = max(formats, 
                                key=lambda x: (
                                    x.get('height', 0) if x.get('height') and x.get('height') <= 720 else 0,
                                    1 if x.get('ext') == 'mp4' else 0
                                ))
                video_url = best_format.get('url')
            
            if not video_url:
                return jsonify({
                    'error': 'no_video_url',
                    'message': 'No se pudo obtener URL de video reproducible'
                }), 400
            
            # Preparar respuesta
            response_data = {
                'video_url': video_url,
                'title': info.get('title', 'Video sin título'),
                'duration': info.get('duration'),
                'thumbnail': info.get('thumbnail'),
                'uploader': info.get('uploader'),
                'view_count': info.get('view_count'),
                'upload_date': info.get('upload_date'),
                'description': info.get('description', '')[:500] if info.get('description') else None,  # Limitamos descripción
                'original_url': clean_video_url
            }
            
            logger.info(f"Extracción exitosa: {response_data['title']}")
            return jsonify(response_data)
            
    except yt_dlp.DownloadError as e:
        error_msg = str(e)
        logger.error(f"Error de yt-dlp: {error_msg}")
        
        # Errores comunes de YouTube
        if 'Video unavailable' in error_msg:
            return jsonify({
                'error': 'video_unavailable',
                'message': 'El video no está disponible (puede ser privado, eliminado o restringido por región)'
            }), 404
        elif 'Sign in to confirm your age' in error_msg:
            return jsonify({
                'error': 'age_restricted',
                'message': 'El video tiene restricción de edad'
            }), 403
        elif 'Private video' in error_msg:
            return jsonify({
                'error': 'private_video',
                'message': 'El video es privado'
            }), 403
        else:
            return jsonify({
                'error': 'extraction_error',
                'message': f'Error al extraer el video: {error_msg}'
            }), 500
            
    except Exception as e:
        logger.error(f"Error inesperado: {str(e)}")
        return jsonify({
            'error': 'internal_error',
            'message': 'Error interno del servidor'
        }), 500

@app.route('/extract', methods=['POST'])
def extract_video_info_post():
    """
    Extrae información del video de YouTube mediante POST
    Body JSON: {"url": "https://youtube.com/..."}
    """
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({
                'error': 'missing_url',
                'message': 'Falta el parámetro URL en el body JSON'
            }), 400
        
        url = data['url']
        return extract_video_info(url)
        
    except Exception as e:
        logger.error(f"Error en POST extract: {str(e)}")
        return jsonify({
            'error': 'internal_error',
            'message': 'Error interno del servidor'
        }), 500

@app.route('/formats/<path:url>', methods=['GET'])
def get_available_formats(url):
    """
    Obtiene todos los formatos disponibles para un video (útil para debugging)
    """
    try:
        clean_video_url = clean_url(url)
        
        if not is_valid_youtube_url(clean_video_url):
            return jsonify({
                'error': 'invalid_url',
                'message': 'La URL proporcionada no es una URL válida de YouTube'
            }), 400
        
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            info = ydl.extract_info(clean_video_url, download=False)
            
            formats = []
            for fmt in info.get('formats', []):
                formats.append({
                    'format_id': fmt.get('format_id'),
                    'ext': fmt.get('ext'),
                    'resolution': fmt.get('resolution'),
                    'fps': fmt.get('fps'),
                    'vcodec': fmt.get('vcodec'),
                    'acodec': fmt.get('acodec'),
                    'filesize': fmt.get('filesize'),
                    'url': fmt.get('url')
                })
            
            return jsonify({
                'title': info.get('title'),
                'formats': formats
            })
            
    except Exception as e:
        logger.error(f"Error obteniendo formatos: {str(e)}")
        return jsonify({
            'error': 'formats_error',
            'message': f'Error obteniendo formatos: {str(e)}'
        }), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'error': 'not_found',
        'message': 'Endpoint no encontrado'
    }), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        'error': 'internal_error',
        'message': 'Error interno del servidor'
    }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    logger.info(f"Iniciando servidor en puerto {port}")
    app.run(host='0.0.0.0', port=port, debug=debug)