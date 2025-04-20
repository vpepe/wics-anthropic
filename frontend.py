#!/usr/bin/env python3
"""
Frontend for Wikipedia Synthesizer

This Flask application provides a web interface for the Wikipedia Synthesizer
that combines articles from different languages.
"""

from flask import Flask, render_template, request, redirect, url_for, jsonify, session, send_file
import backend  # Import your updated backend.py
from anthropic import Anthropic
import os
import uuid
import threading
import time
import datetime
import re
from urllib.parse import quote_plus

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.urandom(24)  # For session management

# In-memory storage for jobs (would use a database in production)
jobs = {}

# Mapping between permanent slugs and job IDs
slug_to_job = {}

# Create Anthropic client
client = Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))

def create_slug(title, language):
    """Create a permanent slug from title and language"""
    # Normalize title: lowercase, replace spaces with hyphens, remove special chars
    title_slug = re.sub(r'[^a-zA-Z0-9\s-]', '', title.lower()).strip()
    title_slug = re.sub(r'[\s-]+', '-', title_slug)
    # Format as language/article_name
    full_slug = f"{language}/{title_slug}"
    return full_slug

@app.route('/')
def index():
    """Render the search page"""
    languages = [
      {"code": "en", "name": "English", "count": "Synthesize an article"},
      {"code": "ja", "name": "日本語", "count": "記事を合成する"},
      {"code": "ru", "name": "Русский", "count": "Синтезировать статью"},
      {"code": "de", "name": "Deutsch", "count": "Artikel synthetisieren"},
      {"code": "es", "name": "Español", "count": "Sintetizar un artículo"},
      {"code": "fr", "name": "Français", "count": "Synthétiser un article"},
      {"code": "zh", "name": "中文", "count": "综合文章"},
      {"code": "it", "name": "Italiano", "count": "Sintetizzare un articolo"},
      {"code": "pt", "name": "Português", "count": "Sintetizar um artigo"},
      {"code": "pl", "name": "Polski", "count": "Zsyntetyzuj artykuł"}
    ]
    
    # Update the session with recent articles
    update_recent_articles_in_session()
    
    # Get recent articles from session
    recent_articles = session.get('recent_articles', [])
    
    return render_template('index.html', languages=languages, recent_articles=recent_articles)

def update_recent_articles_in_session():
    """
    This function should only be called within a request context.
    It updates the session with recent articles from our in-memory storage.
    """
    # Get completed jobs and their article info
    completed_articles = []
    for job in jobs.values():
        if job['status'] == 'completed' and 'article_info' in job:
            # Add permanent slug to article info for linking
            article_info = job['article_info'].copy()
            article_info['slug'] = job.get('slug', create_slug(job['title'], job['language']))
            completed_articles.append(article_info)
    
    # Sort by date (newest first) and limit to 10
    sorted_articles = sorted(completed_articles, key=lambda x: x['date'], reverse=True)[:10]
    
    # Update the session
    session['recent_articles'] = sorted_articles

@app.route('/search', methods=['POST'])
def search():
    """Handle the search form submission"""
    title = request.form.get('title')
    language = request.form.get('language', 'en')
    max_translations = int(request.form.get('max_translations', 5))
    no_cache = request.form.get('no_cache') == 'true'
    
    if not title:
        return redirect(url_for('index'))
    
    # Create a permanent slug
    slug = create_slug(title, language)
    
    # Check if we already have a job for this slug
    if slug in slug_to_job and slug_to_job[slug] in jobs:
        existing_job_id = slug_to_job[slug]
        existing_job = jobs[existing_job_id]
        
        # If job is completed or in progress, redirect to it
        if existing_job['status'] in ['completed', 'processing', 'queued']:
            if existing_job['status'] == 'completed':
                return redirect(url_for('view_article', language=language, article_name=slug.split('/', 1)[1]))
            else:
                return redirect(url_for('article_status', language=language, article_name=slug.split('/', 1)[1]))
    
    # Check cache first unless no-cache is specified
    if not no_cache:
        cached_path = backend.check_cache(title, language, max_translations)
        if cached_path:
            # Create a "completed" job for the cached article
            job_id = str(uuid.uuid4())
            cache_date = datetime.datetime.fromtimestamp(os.path.getmtime(cached_path))
            
            with open(cached_path, 'r', encoding='utf-8') as f:
                cached_content = f.read()
            
            jobs[job_id] = {
                'id': job_id,
                'slug': slug,
                'title': title,
                'language': language,
                'max_translations': max_translations,
                'status': 'completed',
                'progress': 100,
                'result': cached_content,
                'error': None,
                'article_info': {
                    'title': title,
                    'language': language,
                    'date': cache_date.strftime('%Y-%m-%d %H:%M:%S'),
                    'from_cache': True,
                    'cache_path': cached_path
                }
            }
            
            # Map the slug to this job
            slug_to_job[slug] = job_id
            
            # Add to recent articles
            update_recent_articles_in_session()
            
            # Redirect to the article page
            return redirect(url_for('view_article', language=language, article_name=slug.split('/', 1)[1]))
    
    # Create a job ID
    job_id = str(uuid.uuid4())
    
    # Initialize job
    jobs[job_id] = {
        'id': job_id,
        'slug': slug,
        'title': title,
        'language': language,
        'max_translations': max_translations,
        'status': 'queued',
        'progress': 0,
        'result': None,
        'error': None,
        'from_cache': False
    }
    
    # Map the slug to this job
    slug_to_job[slug] = job_id
    
    # Start the synthesis process in a background thread
    thread = threading.Thread(
        target=process_job,
        args=(job_id, title, language, max_translations, no_cache)
    )
    thread.daemon = True
    thread.start()
    
    # Redirect to status page
    return redirect(url_for('article_status', language=language, article_name=slug.split('/', 1)[1]))

def process_job(job_id, title, language, max_translations, no_cache=False):
    """Background process to run the article synthesis"""
    try:
        # Update job status
        jobs[job_id]['status'] = 'processing'
        
        # Check cache first unless no-cache is specified
        if not no_cache:
            cached_path = backend.check_cache(title, language, max_translations)
            if cached_path:
                # Load from cache
                with open(cached_path, 'r', encoding='utf-8') as f:
                    cached_content = f.read()
                
                # Update job with cached result
                jobs[job_id]['status'] = 'completed'
                jobs[job_id]['progress'] = 100
                jobs[job_id]['result'] = cached_content
                jobs[job_id]['article_info'] = {
                    'title': title,
                    'language': language,
                    'date': datetime.datetime.fromtimestamp(os.path.getmtime(cached_path)).strftime('%Y-%m-%d %H:%M:%S'),
                    'from_cache': True,
                    'cache_path': cached_path
                }
                
                # We can't determine the selected languages for cached content
                # This will use the fallback in the template
                jobs[job_id]['selected_languages'] = []
                
                # Update recent articles in session cannot be called from background thread
                # It will be called when the user views the article
                return
        
        # Step 1: Get the original article
        jobs[job_id]['progress'] = 10
        original_text, langlinks = backend.get_wikipedia_article_with_tool(title, language, True)
        
        if not original_text or not langlinks:
            raise Exception(f"Could not find article '{title}' in {language}")
        
        # Step 2: Select relevant languages
        jobs[job_id]['progress'] = 20
        relevant_languages = backend.select_relevant_languages(
            client, 
            title, 
            language, 
            langlinks, 
            max_translations=max_translations
        )
        
        # Store the selected languages in the job
        jobs[job_id]['selected_languages'] = relevant_languages
        
        # Create a list of tuples for selected languages
        translations = []
        for lang_link in langlinks:
            if lang_link["language"] in relevant_languages:
                translations.append((lang_link["language"], lang_link["title"]))
        
        # Add the source language
        translations.append((language, title))
        
        # Step 3: Get translation content
        jobs[job_id]['progress'] = 30
        translation_content = backend.get_translation_content_with_tool(client, translations)
        
        # Step 4: Translate articles
        jobs[job_id]['progress'] = 40
        translated_articles = {}
        
        # Add the original language version first
        translated_articles[language] = original_text
        
        # Prepare arguments for parallel processing
        translation_args = []
        for lang, content in translation_content.items():
            if lang != language:  # Skip source language
                translation_args.append((client, content, lang, language, lang))
        
        # Use backend's parallel translation
        with backend.ThreadPool(min(10, len(translation_args))) as pool:
            # Map worker function to arguments
            results = pool.map(backend.translate_article_worker, translation_args)
            
            # Process results and update progress incrementally
            for i, (lang, translated) in enumerate(results):
                progress_increment = 30 / max(1, len(translation_args))
                jobs[job_id]['progress'] = min(70, 40 + int((i+1) * progress_increment))
                
                if translated is not None:
                    translated_articles[lang] = translated
        
        # Step 5: Synthesize
        jobs[job_id]['progress'] = 80
        synthesized_article = backend.synthesize_with_claude(
            client, translated_articles, language, title
        )
        
        if synthesized_article.startswith("Synthesis failed:"):
            raise Exception(synthesized_article)
        
        # Save to cache
        cache_path = backend.save_to_cache(title, language, max_translations, synthesized_article)
        
        # Update job with result
        jobs[job_id]['status'] = 'completed'
        jobs[job_id]['progress'] = 100
        jobs[job_id]['result'] = synthesized_article
        
        # Store article metadata in the job
        jobs[job_id]['article_info'] = {
            'title': title,
            'language': language,
            'date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'from_cache': False,
            'cache_path': cache_path
        }
        
        # Update recent articles in session cannot be called from background thread
        # It will be called when the user views the article
        
    except Exception as e:
        # Handle errors
        jobs[job_id]['status'] = 'error'
        jobs[job_id]['error'] = str(e)
        print(f"Error in job {job_id}: {e}")

# New route for status using language/article_name format
@app.route('/status/<language>/<article_name>')
def article_status(language, article_name):
    """Show the status page for a job using its permanent URL"""
    # Reconstruct the slug
    slug = f"{language}/{article_name}"
    
    if slug not in slug_to_job:
        # Article doesn't exist - redirect to the not_found page
        return redirect(url_for('not_found', language=language, article_name=article_name))
    
    job_id = slug_to_job[slug]
    job = jobs[job_id]
    
    if job['status'] == 'completed':
        # Redirect to article page if job is complete
        return redirect(url_for('view_article', language=language, article_name=article_name))
    
    return render_template('status.html', job=job, language=language, article_name=article_name)

# Legacy route for job_id-based status (for backward compatibility)
@app.route('/job_status/<job_id>')
def status(job_id):
    """Show the status page for a job using legacy job_id"""
    if job_id not in jobs:
        return redirect(url_for('index'))
    
    job = jobs[job_id]
    slug = job.get('slug', create_slug(job['title'], job['language']))
    language, article_name = slug.split('/', 1)
    
    # Redirect to the language/article_name URL for canonical linking
    return redirect(url_for('article_status', language=language, article_name=article_name))

@app.route('/api/status/<language>/<article_name>')
def api_status_by_path(language, article_name):
    """API endpoint for getting job status via AJAX using language/article_name"""
    slug = f"{language}/{article_name}"
    
    if slug not in slug_to_job:
        return jsonify({'error': 'Article not found'}), 404
    
    job_id = slug_to_job[slug]
    return jsonify(jobs[job_id])

@app.route('/api/status/<job_id>')
def api_status(job_id):
    """API endpoint for getting job status via AJAX using job_id (legacy)"""
    if job_id not in jobs:
        return jsonify({'error': 'Job not found'}), 404
    
    return jsonify(jobs[job_id])

# New route for viewing article using language/article_name format
@app.route('/article/<language>/<article_name>')
def view_article(language, article_name):
    """Show the synthesized article using its permanent URL"""
    # Reconstruct the slug
    slug = f"{language}/{article_name}"
    
    # First check if the article is in our in-memory mapping
    if slug in slug_to_job:
        job_id = slug_to_job[slug]
        if job_id in jobs and jobs[job_id]['status'] == 'completed':
            job = jobs[job_id]
            
            # Define all available languages with names
            all_languages = [
                {"code": "en", "name": "English"},
                {"code": "ja", "name": "日本語"},
                {"code": "ru", "name": "Русский"},
                {"code": "de", "name": "Deutsch"},
                {"code": "es", "name": "Español"},
                {"code": "fr", "name": "Français"},
                {"code": "zh", "name": "中文"},
                {"code": "it", "name": "Italiano"},
                {"code": "pt", "name": "Português"},
                {"code": "pl", "name": "Polski"},
            ]
            
            # Get the selected languages from the job if available
            selected_languages = job.get('selected_languages', [])
            
            # Update recent articles in session when viewing an article
            update_recent_articles_in_session()
            
            # Get cache information
            from_cache = job.get('article_info', {}).get('from_cache', False)
            cache_path = job.get('article_info', {}).get('cache_path', None)
            
            return render_template('article.html', 
                                  article=job['result'], 
                                  title=job['title'],
                                  language=job['language'],
                                  max_translations=job['max_translations'],
                                  now=datetime.datetime.now(),
                                  languages=all_languages,
                                  all_languages=all_languages,
                                  selected_languages=selected_languages,
                                  from_cache=from_cache,
                                  cache_path=cache_path,
                                  article_name=article_name,
                                  job_id=job_id)
        elif job_id in jobs:
            # Job exists but isn't completed
            return redirect(url_for('article_status', language=language, article_name=article_name))
    
    # If we get here, the article isn't in our in-memory mapping
    # Check if it exists in the cache directly
    article_title = article_name.replace('-', ' ').title()
    cache_key = backend.get_cache_key(article_title, language, 5)  # Use default 5 translations
    cache_path = backend.get_cache_path(cache_key)
    
    if os.path.exists(cache_path):
        # Found in cache! Create a job for it
        job_id = str(uuid.uuid4())
        with open(cache_path, 'r', encoding='utf-8') as f:
            cached_content = f.read()
        
        # Create a job entry for this cached article
        jobs[job_id] = {
            'id': job_id,
            'slug': slug,
            'title': article_title,
            'language': language,
            'max_translations': 5,  # Default
            'status': 'completed',
            'progress': 100,
            'result': cached_content,
            'error': None,
            'article_info': {
                'title': article_title,
                'language': language,
                'date': datetime.datetime.fromtimestamp(os.path.getmtime(cache_path)).strftime('%Y-%m-%d %H:%M:%S'),
                'from_cache': True,
                'cache_path': cache_path
            }
        }
        
        # Update the mapping
        slug_to_job[slug] = job_id
        
        # Redirect to ourselves to use the normal view path now that the job exists
        return redirect(url_for('view_article', language=language, article_name=article_name))
    
    # If we get here, the article really doesn't exist
    return redirect(url_for('not_found', language=language, article_name=article_name))

# Legacy route for job_id-based article viewing (for backward compatibility)
@app.route('/article_by_id/<job_id>')
def article(job_id):
    """Show the synthesized article using the legacy job_id"""
    if job_id not in jobs or jobs[job_id]['status'] != 'completed':
        return redirect(url_for('index'))
    
    job = jobs[job_id]
    slug = job.get('slug', create_slug(job['title'], job['language']))
    language, article_name = slug.split('/', 1)
    
    # Redirect to the language/article_name URL for canonical linking
    return redirect(url_for('view_article', language=language, article_name=article_name))

@app.route('/download/<language>/<article_name>')
def download_article_by_path(language, article_name):
    """Download the synthesized article as HTML using language/article_name"""
    # Reconstruct the slug
    slug = f"{language}/{article_name}"
    
    if slug not in slug_to_job:
        return redirect(url_for('index'))
    
    job_id = slug_to_job[slug]
    if job_id not in jobs or jobs[job_id]['status'] != 'completed':
        return redirect(url_for('index'))
    
    job = jobs[job_id]
    
    # If we have a cached file, serve it directly
    if 'article_info' in job and 'cache_path' in job['article_info']:
        cache_path = job['article_info']['cache_path']
        if os.path.exists(cache_path):
            return send_file(
                cache_path,
                mimetype='text/html',
                as_attachment=True,
                download_name=f"{job['title']}.html"
            )
    
    # Otherwise create a temporary file
    import tempfile
    
    fd, path = tempfile.mkstemp(suffix='.html')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as tmp:
            tmp.write(job['result'])
        
        return send_file(
            path,
            mimetype='text/html',
            as_attachment=True,
            download_name=f"{job['title']}.html"
        )
    finally:
        # Clean up temporary file (happens after response is sent)
        try:
            os.remove(path)
        except:
            pass

# Legacy route for job_id-based download (for backward compatibility)
@app.route('/download_by_id/<job_id>')
def download_article(job_id):
    """Download the synthesized article as HTML using job_id (legacy)"""
    if job_id not in jobs or jobs[job_id]['status'] != 'completed':
        return redirect(url_for('index'))
    
    job = jobs[job_id]
    slug = job.get('slug', create_slug(job['title'], job['language']))
    language, article_name = slug.split('/', 1)
    
    # Redirect to the language/article_name URL for canonical linking
    return redirect(url_for('download_article_by_path', language=language, article_name=article_name))

@app.route('/regenerate/<language>/<article_name>')
def regenerate_article_by_path(language, article_name):
    """Regenerate an article (bypassing the cache) using language/article_name"""
    # Reconstruct the slug
    slug = f"{language}/{article_name}"
    
    if slug not in slug_to_job:
        return redirect(url_for('index'))
    
    job_id = slug_to_job[slug]
    job = jobs[job_id]
    
    # Create a new job with no-cache option
    new_job_id = str(uuid.uuid4())
    
    # Initialize job with the same slug
    jobs[new_job_id] = {
        'id': new_job_id,
        'slug': slug,  # Use the same slug
        'title': job['title'],
        'language': job['language'],
        'max_translations': job['max_translations'],
        'status': 'queued',
        'progress': 0,
        'result': None,
        'error': None,
        'from_cache': False
    }
    
    # Update the slug mapping to point to the new job
    slug_to_job[slug] = new_job_id
    
    # Start the synthesis process in a background thread
    thread = threading.Thread(
        target=process_job,
        args=(new_job_id, job['title'], job['language'], job['max_translations'], True)
    )
    thread.daemon = True
    thread.start()
    
    # Redirect to status page
    return redirect(url_for('article_status', language=language, article_name=article_name))

# Legacy route for job_id-based regeneration (for backward compatibility)
@app.route('/regenerate_by_id/<job_id>')
def regenerate_article(job_id):
    """Regenerate an article (bypassing the cache) using job_id (legacy)"""
    if job_id not in jobs:
        return redirect(url_for('index'))
    
    job = jobs[job_id]
    slug = job.get('slug', create_slug(job['title'], job['language']))
    language, article_name = slug.split('/', 1)
    
    # Redirect to the language/article_name URL for canonical linking
    return redirect(url_for('regenerate_article_by_path', language=language, article_name=article_name))

@app.route('/cache/<path:filename>')
def cached_content(filename):
    """Serve a cached file directly"""
    return send_file(os.path.join(backend.CACHE_DIR, filename))

@app.route('/cache')
def list_cache():
    """List all cached articles"""
    cached_files = []
    
    # Get all HTML files in the cache directory
    if os.path.exists(backend.CACHE_DIR):
        for filename in os.listdir(backend.CACHE_DIR):
            if filename.endswith('.html'):
                path = os.path.join(backend.CACHE_DIR, filename)
                try:
                    # Get file modification time
                    mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path))
                    
                    # Get file size
                    size = os.path.getsize(path)
                    
                    # Read the first line to try to extract a title
                    with open(path, 'r', encoding='utf-8') as f:
                        first_line = f.readline().strip()
                        title = first_line if first_line.startswith('<h1>') else filename
                    
                    # Try to extract language and title from cache key
                    parts = filename.split('/')
                    if len(parts) > 1:
                        language = parts[0]
                        article_title = parts[1].replace('.html', '').replace('_', ' ')
                        article_name = parts[1].replace('.html', '')
                    else:
                        language = None
                        article_title = None
                        article_name = None
                    
                    cached_files.append({
                        'filename': filename,
                        'path': path,
                        'mtime': mtime,
                        'size': size,
                        'title': title,
                        'language': language,
                        'article_title': article_title,
                        'article_name': article_name
                    })
                except Exception as e:
                    print(f"Error reading cache file {filename}: {e}")
    
    # Sort by modification time (newest first)
    cached_files = sorted(cached_files, key=lambda x: x['mtime'], reverse=True)
    
    return render_template('cache.html', 
                           cached_files=cached_files,
                           cache_dir=backend.CACHE_DIR)

@app.route('/clear_cache')
def clear_cache():
    """Clear all cached articles"""
    if os.path.exists(backend.CACHE_DIR):
        for filename in os.listdir(backend.CACHE_DIR):
            if filename.endswith('.html'):
                try:
                    os.remove(os.path.join(backend.CACHE_DIR, filename))
                except Exception as e:
                    print(f"Error removing cache file {filename}: {e}")
    
    return redirect(url_for('list_cache'))

# New route for handling non-existent articles
@app.route('/not_found/<language>/<article_name>')
def not_found(language, article_name):
    """Show a page prompting the user to create a new article"""
    # Determine article title from article_name (replace hyphens with spaces)
    article_title = article_name.replace('-', ' ').title()
    
    # Get the language name from the language code
    language_name = "Unknown"
    for lang in [
        {"code": "en", "name": "English"},
        {"code": "ja", "name": "日本語"},
        {"code": "ru", "name": "Русский"},
        {"code": "de", "name": "Deutsch"},
        {"code": "es", "name": "Español"},
        {"code": "fr", "name": "Français"},
        {"code": "zh", "name": "中文"},
        {"code": "it", "name": "Italiano"},
        {"code": "pt", "name": "Português"},
        {"code": "pl", "name": "Polski"},
    ]:
        if lang["code"] == language:
            language_name = lang["name"]
            break
    
    return render_template('not_found.html', 
                          language=language,
                          language_name=language_name,
                          article_name=article_name,
                          article_title=article_title)



if __name__ == '__main__':
    app.run(debug=True)