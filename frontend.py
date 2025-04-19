#!/usr/bin/env python3
"""
Frontend for Wikipedia Synthesizer

This Flask application provides a web interface for the Wikipedia Synthesizer
that combines articles from different languages.
"""

from flask import Flask, render_template, request, redirect, url_for, jsonify, session
import backend  # Import your updated backend.py
from anthropic import Anthropic
import os
import uuid
import threading
import time
import datetime

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.urandom(24)  # For session management

# In-memory storage for jobs (would use a database in production)
jobs = {}

# Create Anthropic client
client = Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))

@app.route('/')
def index():
    """Render the search page"""
    languages = [
        {"code": "en", "name": "English", "count": "6,974,000+ articles"},
        {"code": "ja", "name": "日本語", "count": "1,457,000+ 記事"},
        {"code": "ru", "name": "Русский", "count": "2,036,000+ статей"},
        {"code": "de", "name": "Deutsch", "count": "3,001,000+ Artikel"},
        {"code": "es", "name": "Español", "count": "2,021,000+ artículos"},
        {"code": "fr", "name": "Français", "count": "2,674,000+ articles"},
        {"code": "zh", "name": "中文", "count": "1,470,000+ 条目 / 條目"},
        {"code": "it", "name": "Italiano", "count": "1,910,000+ voci"},
        {"code": "pt", "name": "Português", "count": "1,146,000+ artigos"},
        {"code": "pl", "name": "Polski", "count": "1,652,000+ haseł"},
    ]
    
    # Update the session with recent articles
    update_recent_articles_in_session()
    
    # Get recent articles from session
    recent_articles = session.get('recent_articles', [])
    
    return render_template('index.html', languages=languages, recent_articles=recent_articles)

@app.route('/search', methods=['POST'])
def search():
    """Handle the search form submission"""
    title = request.form.get('title')
    language = request.form.get('language', 'en')
    max_translations = int(request.form.get('max_translations', 5))
    
    if not title:
        return redirect(url_for('index'))
    
    # Create a job ID
    job_id = str(uuid.uuid4())
    
    # Initialize job
    jobs[job_id] = {
        'id': job_id,
        'title': title,
        'language': language,
        'max_translations': max_translations,
        'status': 'queued',
        'progress': 0,
        'result': None,
        'error': None
    }
    
    # Start the synthesis process in a background thread
    thread = threading.Thread(
        target=process_job,
        args=(job_id, title, language, max_translations)
    )
    thread.daemon = True
    thread.start()
    
    # Redirect to status page
    return redirect(url_for('status', job_id=job_id))

def process_job(job_id, title, language, max_translations):
    """Background process to run the article synthesis"""
    try:
        # Update job status
        jobs[job_id]['status'] = 'processing'
        
        # Step 1: Get the original article
        jobs[job_id]['progress'] = 10
        original_text, langlinks = backend.get_wikipedia_article_with_tool(title, language)
        
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
        
        # Use backend's parallel translation (or adapt to process one at a time)
        with backend.ThreadPool(min(10, len(translation_args))) as pool:
            # Map worker function to arguments
            results = pool.map(backend.translate_article_worker, translation_args)
            
            # Process results and update progress incrementally
            for i, (lang, translated) in enumerate(results):
                progress_increment = 30 / len(translation_args)
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
        
        # Update job with result
        jobs[job_id]['status'] = 'completed'
        jobs[job_id]['progress'] = 100
        jobs[job_id]['result'] = synthesized_article
        
        # Store article metadata in the job rather than session
        jobs[job_id]['article_info'] = {
            'title': title,
            'language': language,
            'date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
    except Exception as e:
        # Handle errors
        jobs[job_id]['status'] = 'error'
        jobs[job_id]['error'] = str(e)
        print(f"Error in job {job_id}: {e}")

# Global in-memory storage for recent articles
recent_articles_storage = []

def update_recent_articles_in_session():
    """
    This function should only be called within a request context.
    It updates the session with recent articles from our in-memory storage.
    """
    # Get completed jobs and their article info
    completed_articles = []
    for job in jobs.values():
        if job['status'] == 'completed' and 'article_info' in job:
            completed_articles.append(job['article_info'])
    
    # Sort by date (newest first) and limit to 10
    sorted_articles = sorted(completed_articles, key=lambda x: x['date'], reverse=True)[:10]
    
    # Update the session
    session['recent_articles'] = sorted_articles

@app.route('/status/<job_id>')
def status(job_id):
    """Show the status page for a job"""
    if job_id not in jobs:
        return redirect(url_for('index'))
    
    job = jobs[job_id]
    
    if job['status'] == 'completed':
        # Redirect to article page if job is complete
        return redirect(url_for('article', job_id=job_id))
    
    return render_template('status.html', job=job)

@app.route('/api/status/<job_id>')
def api_status(job_id):
    """API endpoint for getting job status via AJAX"""
    if job_id not in jobs:
        return jsonify({'error': 'Job not found'}), 404
    
    return jsonify(jobs[job_id])

@app.route('/article/<job_id>')
def article(job_id):
    """Show the synthesized article"""
    if job_id not in jobs or jobs[job_id]['status'] != 'completed':
        return redirect(url_for('index'))
    
    job = jobs[job_id]
    languages = [
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
    
    # Update recent articles in session when viewing an article
    update_recent_articles_in_session()
    
    return render_template('article.html', 
                          article=job['result'], 
                          title=job['title'],
                          language=job['language'],
                          max_translations=job['max_translations'],
                          now=datetime.datetime.now(),
                          languages=languages)

if __name__ == '__main__':
    app.run(debug=True)