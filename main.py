from flask import Flask, render_template, send_from_directory, request, redirect, url_for, abort, jsonify, make_response
import os
import re
import json
from flask_caching import Cache
from werkzeug.middleware.proxy_fix import ProxyFix
from datetime import datetime

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
cache = Cache(app, config={'CACHE_TYPE': 'simple'})

ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}
ITEMS_PER_PAGE = 24

@cache.memoize(timeout=300)
def get_manga_list(folder):
    manga_list = []
    for item in os.listdir(folder):
        item_path = os.path.join(folder, item)
        if os.path.isdir(item_path):
            preview_image = next((f for f in os.listdir(item_path) if f.lower().startswith('preview') and os.path.splitext(f)[1].lower() in ALLOWED_EXTENSIONS), None)
            info_file = os.path.join(item_path, 'info.json')
            info = {}
            if os.path.exists(info_file):
                with open(info_file, 'r', encoding='utf-8') as f:
                    info = json.load(f)
            if preview_image:
                manga_list.append({
                    'title': item,
                    'preview': f'/image/{folder}/{item}/{preview_image}',  # Modified this line
                    'author': info.get('author', 'Unknown'),
                    'genres': info.get('genres', []),
                    'status': info.get('status', 'Unknown'),
                    'description': info.get('description', 'No description available.'),
                    'rating': info.get('rating', 0),
                    'last_updated': info.get('last_updated', 'Unknown')
                })
    return sorted(manga_list, key=lambda x: x['title'])

@cache.memoize(timeout=300)
def get_chapters(manga_title, folder):
    chapters = []
    manga_path = os.path.join(folder, manga_title)
    subdirs = [d for d in os.listdir(manga_path) if os.path.isdir(os.path.join(manga_path, d))]
    
    if not subdirs:
        chapters.append({'number': 0, 'title': 'Oneshot', 'folder': ''})
    else:
        for item in subdirs:
            if item.isdigit():
                chapters.append({'number': int(item), 'title': f'Chapter {item}', 'folder': item})
            else:
                match = re.search(r'_(\d+)$', item)
                if match:
                    number = int(match.group(1))
                    chapters.append({'number': number, 'title': item, 'folder': item})
                else:
                    chapters.append({'number': float('inf'), 'title': item, 'folder': item})
    
    chapters.sort(key=lambda x: x['number'])
    return chapters

@cache.memoize(timeout=300)
def get_images(manga_title, chapter_folder, folder):
    if chapter_folder:
        chapter_path = os.path.join(folder, manga_title, chapter_folder)
    else:
        chapter_path = os.path.join(folder, manga_title)
    
    images = []
    for file in os.listdir(chapter_path):
        if os.path.splitext(file)[1].lower() in ALLOWED_EXTENSIONS:
            images.append(file)
    
    def sort_key(filename):
        match = re.search(r'_(\d+)(?=\.[^.]+$)', filename)
        if match:
            return int(match.group(1))
        
        match = re.search(r'(\d+)', filename)
        if match:
            return int(match.group(1))
        
        return float('inf')
    
    images.sort(key=sort_key)
    return images

@app.route('/')
def index():
    mode = request.args.get('mode', 'manga')
    if mode not in ['manga', 'hentai']:
        mode = 'manga'
    
    page = request.args.get('page', 1, type=int)
    search_query = request.args.get('search', '')
    sort_by = request.args.get('sort', 'title')
    filter_genre = request.args.get('genre', '')
    
    manga_list = get_manga_list(mode)
    
    if search_query:
        manga_list = [manga for manga in manga_list if search_query.lower() in manga['title'].lower()]
    
    if filter_genre:
        manga_list = [manga for manga in manga_list if filter_genre in manga['genres']]
    
    if sort_by == 'rating':
        manga_list.sort(key=lambda x: x['rating'], reverse=True)
    elif sort_by == 'last_updated':
        manga_list.sort(key=lambda x: datetime.strptime(x['last_updated'], '%Y-%m-%d') if x['last_updated'] != 'Unknown' else datetime.min, reverse=True)
    
    total_pages = (len(manga_list) - 1) // ITEMS_PER_PAGE + 1
    start = (page - 1) * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    
    all_genres = set()
    for manga in manga_list:
        all_genres.update(manga['genres'])
    
    # Add latest chapters to each manga
    for manga in manga_list:
        manga['latest_chapters'] = get_chapters(manga['title'], mode)[-3:][::-1]
    
    return render_template('index.html', 
                           manga_list=manga_list[start:end], 
                           page=page, 
                           total_pages=total_pages, 
                           mode=mode,
                           search_query=search_query,
                           sort_by=sort_by,
                           filter_genre=filter_genre,
                           all_genres=sorted(all_genres),
                           get_chapters=get_chapters)

@app.route('/toggle-theme')
def toggle_theme():
    current_theme = request.cookies.get('theme', 'light')
    new_theme = 'dark' if current_theme == 'light' else 'light'
    response = make_response(redirect(request.referrer or url_for('index')))
    response.set_cookie('theme', new_theme, max_age=86400)  # 1 day
    return response

@app.route('/<folder>/<title>')
def manga_detail(folder, title):
    chapters = get_chapters(title, folder)
    info_file = os.path.join(folder, title, 'info.json')
    info = {}
    if os.path.exists(info_file):
        with open(info_file, 'r', encoding='utf-8') as f:
            info = json.load(f)
    
    page = request.args.get('page', 1, type=int)
    total_pages = (len(chapters) - 1) // ITEMS_PER_PAGE + 1
    
    # Get the preview image
    preview_image = next((f for f in os.listdir(os.path.join(folder, title)) if f.lower().startswith('preview') and os.path.splitext(f)[1].lower() in ALLOWED_EXTENSIONS), None)
    
    return render_template('manga_detail.html', title=title, chapters=chapters, folder=folder, info=info, page=page, total_pages=total_pages, preview_image=preview_image)

@app.route('/<folder>/<title>/<chapter>')
def read_chapter(folder, title, chapter):
    manga_path = os.path.join(folder, title)
    chapters = get_chapters(title, folder)
    
    current_chapter = next((c for c in chapters if str(c['number']) == chapter or c['title'] == chapter or c['folder'] == chapter), None)
    
    if current_chapter is None:
        return "Chapter not found", 404
    
    if current_chapter['number'] == 0:
        chapter_path = manga_path
    else:
        chapter_path = os.path.join(manga_path, current_chapter['folder'])
    
    html_file = next((f for f in os.listdir(chapter_path) if f.lower().endswith('.html')), None)
    
    if html_file:
        with open(os.path.join(chapter_path, html_file), 'r', encoding='utf-8') as f:
            content = f.read()
        return content
    else:
        images = get_images(title, current_chapter['folder'], folder)
        return render_template('read_chapter.html', title=title, chapter=current_chapter, images=images, folder=folder, chapters=chapters)

@app.route('/image/<path:filepath>')
def serve_image(filepath):
    try:
        directory = os.path.dirname(filepath)
        filename = os.path.basename(filepath)
        return send_from_directory(directory, filename)
    except FileNotFoundError:
        abort(404)

@app.route('/api/search')
def search():
    query = request.args.get('q', '').lower()
    mode = request.args.get('mode', 'manga')
    
    if mode not in ['manga', 'hentai']:
        mode = 'manga'
    
    manga_list = get_manga_list(mode)
    results = [manga for manga in manga_list if query in manga['title'].lower()]
    return jsonify(results)

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.context_processor
def utility_processor():
    def truncate(text, length=200):
        return text[:length] + '...' if len(text) > length else text
    
    return dict(truncate=truncate, max=max, min=min)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80, debug=True)