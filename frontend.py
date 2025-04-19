from flask import Flask, render_template, request, redirect, url_for, jsonify, session
import backend  # Import your existing backend.py
import os
import uuid
import threading
import time

app = Flask(__name__)
app.secret_key = os.urandom(24)  # For session management

# In-memory storage for jobs (would use a database in production)
jobs = {}

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
        
        # Call your backend functions here
        # This is a simplified version - you'll need to update this
        # based on your actual backend.py functions
        
        # Step 1: Get the original article
        jobs[job_id]['progress'] = 10
        original_text, langlinks = backend.get_wikipedia_article(title, language)
        
        if not original_text or not langlinks:
            raise Exception(f"Could not find article '{title}' in {language}")
        
        # Step 2: Get translations
        jobs[job_id]['progress'] = 30
        translations = backend.get_all_translations(langlinks) + [(language, title)]
        translation_content = backend.get_translation_content(translations)
        
        # Step 3: Translate articles
        jobs[job_id]['progress'] = 50
        translated_articles = {language: original_text}
        
        for lang, content in translation_content.items():
            if lang != language and content:
                translated = backend.translate_with_claude(content, lang, language)
                if not translated.startswith("Translation failed:"):
                    translated_articles[lang] = translated
                # Update progress incrementally
                progress_increment = 30 / len(translation_content)
                jobs[job_id]['progress'] = min(80, jobs[job_id]['progress'] + progress_increment)
        
        # Step 4: Synthesize
        jobs[job_id]['progress'] = 90
        synthesized_article = backend.synthesize_with_claude(
            translated_articles, language, title
        )
        
        # Update job with result
        jobs[job_id]['status'] = 'completed'
        jobs[job_id]['progress'] = 100
        jobs[job_id]['result'] = synthesized_article
        
        # Update recent articles in session
        update_recent_articles(title, language)
        
    except Exception as e:
        # Handle errors
        jobs[job_id]['status'] = 'error'
        jobs[job_id]['error'] = str(e)
        print(f"Error in job {job_id}: {e}")

def update_recent_articles(title, language):
    """Update the recent articles list in the session"""
    recent_articles = session.get('recent_articles', [])
    
    # Add the new article at the beginning
    new_article = {
        'title': title,
        'language': language,
        'date': time.strftime('%Y-%m-%d %H:%M:%S')
    }
    
    # Remove duplicates
    recent_articles = [a for a in recent_articles if a['title'] != title or a['language'] != language]
    
    # Add new article and limit to 10
    recent_articles.insert(0, new_article)
    recent_articles = recent_articles[:10]
    
    # Update session
    session['recent_articles'] = recent_articles

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
    
    return render_template('article.html', 
                          article=job['result'], 
                          title=job['title'],
                          language=job['language'],
                          max_translations=job['max_translations'])

if __name__ == '__main__':
    app.run(debug=True)
