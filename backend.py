#!/usr/bin/env python3
"""
Wikipedia Synthesizer with Claude Tools

This script takes a Wikipedia article in one language, finds translations,
uses Claude to select the most relevant languages for the topic,
translates them all to the target language using Claude AI, and synthesizes
them into a comprehensive article.
"""

from dotenv import load_dotenv
load_dotenv()

import argparse
import json
import os
import time
import tiktoken
from typing import Dict, List, Optional, Tuple, Any, Union
import wikipediaapi
from multiprocessing.dummy import Pool as ThreadPool
from anthropic import Anthropic
import hashlib
import pathlib


LANGUAGE_SELECTION_PROMPT = (lambda title, max_translations, source_lang, lang_options_text :f"""I need your help selecting the most relevant languages for Wikipedia articles about "{title}".

Given the topic "{title}", which {max_translations} languages would likely have the most unique, comprehensive, 
or culturally significant information about this topic? I need you to select languages that would provide diverse 
perspectives and complementary information, not just the languages with the longest articles.

Here are the available language options (language code: article title in that language):
{lang_options_text}

Choose exactly {max_translations} languages (NOT including the source language {source_lang}), providing your rationale 
for each. Be sure to include the source language. Format your response as a JSON object with an array of language codes, like this:
{{
  "selected_languages": ["xx", "yy", "zz", "aa", "bb"],
  "rationale": "brief explanation of your choices"
}}""")

TRANSLATION_PROMPT = (lambda source_lang, target_lang, text: f"""Translate the following text from {source_lang} to {target_lang}. 
Maintain the original section structure and formatting as much as possible.

TEXT TO TRANSLATE:
{text}

TRANSLATION:""")

SYNTHESIS_CONTEXT = (lambda original_title, articles, target_lang: f"""I have collected versions of the Wikipedia article '{original_title}' from {len(articles)} different language editions, and translated them all to {target_lang}.

I will now provide each version. Your task is to synthesize these into a single comprehensive article. You should not worry about length constraints, talk for as long as you need to, since everything here is important. Remember that Wikipedia is an encyclopedia, meaning all the information here is useful for research and should be kept, at least at the conceptual level.""")

SYNTHESIS_PROMPT = (lambda combined_input, target_lang: f"""{combined_input}

Please combine these different Wikipedia versions into a single, comprehensive article in {target_lang}. 
Combine information from all sources, resolve any contradictions, and create a well-structured article that 
contains the most accurate and complete information from all language editions.

The article should:
1. Follow Wikipedia's neutral point of view
2. Maintain a proper encyclopedic tone
3. Include all important facts from the various language versions
4. Be well-structured with appropriate sections and subsections
5. Resolve any contradictory information by noting different perspectives or choosing the most reliable information
6. Note which language's version is being referenced for each piece of information, if relevant
7. Include hyperlinks to related topics in the format `/article/language_code/article_name` (for example `/article/en/quantum_physics` or `/article/it/renaissance`). Generate links even if you're not sure whether they exist - the system will automatically create pages for non-existent articles. Be generous with generating links, we want the feeling of an interconnected knowledge base. 

When adding hyperlinks:
- Always generate them with the correct capitalization, e.g. "/article/en/Center_for_AI_Safety" not "/article/en/center_for_Ai_safety"
- Link the first mention of important concepts, people, places, or events
- Use the target language code ({target_lang}) for all links
- Only link to other languages when referring to concepts that are particularly relevant to that language or culture
- Format links simply using Markdown syntax: [link text](/article/language_code/article_name)
- For article names with multiple words, replace spaces with underscores
- For article names with parentheses, make sure they don't interfere with markdown formatting, i.e. [link text](article/language_code/article_name_(item_in_parentheses)), note the two closing parentheses.

SYNTHESIZED ARTICLE:""")

# Claude API information
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
CLAUDE_MODEL = "claude-3-7-sonnet-latest"

# Define cache directory
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# Define the search_wikipedia tool
SEARCH_WIKIPEDIA_TOOL = {
    "name": "search_wikipedia",
    "description": "Search for a Wikipedia article by title and language",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "The title of the Wikipedia article"
            },
            "language": {
                "type": "string",
                "description": "The language code (e.g., 'en', 'es', 'fr')"
            },
            "page": {
                "type": "integer",
                "description": "Page number for paginated results (starting from 0)",
                "default": 0
            }
        },
        "required": ["title", "language"]
    }
}

# Define tools list for Claude
CLAUDE_TOOLS = [SEARCH_WIKIPEDIA_TOOL]

def count_tokens(text: str) -> int:
    """
    Count the number of tokens in a string.
    
    Args:
        text: The text to count tokens for
        
    Returns:
        Number of tokens
    """
    enc = tiktoken.get_encoding("cl100k_base")  # Claude's encoding
    return len(enc.encode(text))

def paginate_text(text: str, tokens_per_page: int = 10000) -> List[str]:
    """
    Paginate text based on token count.
    
    Args:
        text: The text to paginate
        tokens_per_page: Maximum tokens per page
        
    Returns:
        List of text pages
    """
    enc = tiktoken.get_encoding("cl100k_base")  # Claude's encoding
    tokens = enc.encode(text)
    
    pages = []
    start_idx = 0
    
    while start_idx < len(tokens):
        end_idx = min(start_idx + tokens_per_page, len(tokens))
        page_tokens = tokens[start_idx:end_idx]
        page_text = enc.decode(page_tokens)
        pages.append(page_text)
        start_idx = end_idx
    
    return pages

def search_wikipedia(title: str, language: str, page: int = 0) -> Dict[str, Any]:
    """
    Function to implement the search_wikipedia tool functionality.
    
    Args:
        title: The title of the Wikipedia article
        language: Language code
        page: Page number (0-indexed)
        
    Returns:
        Dictionary with article data
    """
    wiki_wiki = wikipediaapi.Wikipedia(
        language=language,
        extract_format=wikipediaapi.ExtractFormat.WIKI,
        user_agent='WikipediaSynthesizer/1.0'
    )
    
    wiki_page = wiki_wiki.page(title)
    
    if not wiki_page.exists():
        return {
            "found": False,
            "error": f"Article '{title}' not found in {language} Wikipedia"
        }
    
    # Get the full text and paginate it
    full_text = wiki_page.text
    pages = paginate_text(full_text)
    
    # Get all language links
    langlinks = []
    for lang, link in wiki_page.langlinks.items():
        langlinks.append({
            "language": lang,
            "title": link.title
        })
    
    # Make sure requested page exists
    if page >= len(pages):
        return {
            "found": True,
            "error": f"Page {page} not available. Article has {len(pages)} pages.",
            "total_pages": len(pages)
        }
    
    return {
        "found": True,
        "title": wiki_page.title,
        "language": language,
        "page": page,
        "total_pages": len(pages),
        "content": pages[page],
        "langlinks": langlinks,
        "url": wiki_page.fullurl
    }

"""
Modifications to backend.py to integrate fuzzy search.
This shows the changes needed - you'll need to include these in your backend.py file.
"""

# Import the new fuzzy search functionality 
from wikipedia_fuzzy_search import perform_fuzzy_search, evaluate_search_results, get_wikipedia_article_with_fuzzy_search

# Replace the existing get_wikipedia_article_with_tool function with the fuzzy search version
def get_wikipedia_article_with_tool(client, title: str, language: str, first_article: bool = False) -> Tuple[Optional[str], Optional[List[Dict]]]:
    """
    Retrieves a Wikipedia article using fuzzy search when needed.
    
    Args:
        client: Anthropic client
        title: The title of the Wikipedia article
        language: The language code
        first_article: Flag to indicate if this is the first article retrieval
    Returns:
        Tuple containing article text and language links if successful, else (None, None)
    """
    return get_wikipedia_article_with_fuzzy_search(client, title, language, first_article)

def select_relevant_languages(client: Anthropic, title: str, source_lang: str, 
                             all_lang_links: List[Dict], max_translations: int = 5) -> List[str]:
    """
    Uses Claude to select the most relevant languages for a given topic.
    
    Args:
        client: Anthropic client
        title: The article title
        source_lang: Source language code
        all_lang_links: List of language links
        max_translations: Maximum number of languages to select
        
    Returns:
        List of selected language codes
    """
    # Extract language codes and titles for prompt
    lang_options = [f"{link['language']}: {link['title']}" for link in all_lang_links]
    lang_options_text = "\n".join(lang_options)
    
    prompt = LANGUAGE_SELECTION_PROMPT(title, max_translations, source_lang, lang_options_text)
    
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1000,
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.2
        )
        
        # Extract JSON response
        response_text = response.content[0].text
        
        # Find JSON object in response
        import re
        json_match = re.search(r'({[\s\S]*})', response_text)
        
        if json_match:
            try:
                json_data = json.loads(json_match.group(1))
                selected_languages = json_data.get("selected_languages", [])
                
                # Make sure we got exactly the right number
                if len(selected_languages) > max_translations:
                    selected_languages = selected_languages[:max_translations]+source_lang
                
                print(f"Selected languages: {selected_languages}")
                print(f"Rationale: {json_data.get('rationale', 'No rationale provided')}")
                
                return selected_languages
                
            except json.JSONDecodeError:
                print(f"Failed to parse JSON response: {response_text}")
        else:
            print(f"Failed to extract JSON from response: {response_text}")
            
    except Exception as e:
        print(f"Error in Claude API call: {e}")
    
    # Fallback to selecting languages based on alphabetical order if Claude fails
    print("Falling back to alphabetical order selection")
    langs = [link["language"] for link in all_lang_links if link["language"] != source_lang]
    return langs[:max_translations]

def get_translation_content_with_tool(client: Anthropic, translations: List[Tuple[str, str]]) -> Dict[str, Optional[str]]:
    """
    Retrieves the content of each translated article using the search_wikipedia tool.
    
    Args:
        client: Anthropic client
        translations: List of tuples containing (language_code, article_title)
        
    Returns:
        Dictionary mapping language codes to article content
    """
    translation_content = {}
    
    for lang, title in translations:
        print(f"  Retrieving {lang} article: {title}")
        
        full_text = ""
        current_page = 0
        
        while True:
            try:
                result = search_wikipedia(title, lang, current_page)
                
                if not result["found"]:
                    print(f"  Article not found: {result.get('error', 'Unknown error')}")
                    translation_content[lang] = None
                    break
                
                full_text += result["content"]
                
                # Check if we've reached the last page
                if current_page >= result["total_pages"] - 1:
                    translation_content[lang] = full_text
                    break
                    
                current_page += 1
                print(f"    Retrieved page {current_page} of {result['total_pages']}")
                
            except Exception as e:
                print(f"  Error retrieving Wikipedia article: {e}")
                if full_text:
                    # Return what we have so far
                    translation_content[lang] = full_text
                else:
                    translation_content[lang] = None
                break
            
    return translation_content

def translate_with_claude(client: Anthropic, text: str, source_lang: str, target_lang: str) -> str:
    """
    Translates text using the Claude API with streaming.
    
    Args:
        client: Anthropic client
        text: The text to translate
        source_lang: Source language code
        target_lang: Target language code
        
    Returns:
        Translated text
    """
    # Skip translation if source and target are the same
    if source_lang == target_lang:
        return text
    
    # Limit text length to handle API constraints
    text = text[:128000] if len(text) > 128000 else text
    
    prompt = TRANSLATION_PROMPT(source_lang, target_lang, text)
    
    try:
        # Use the Anthropic SDK with streaming
        print(f"  Starting translation stream from {source_lang} to {target_lang}...")
        with client.messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=64000,
            messages=[
                {"role": "user", "content": prompt}
            ]
        ) as stream:
            # Collect the streamed response
            translation = ""
            for text in stream.text_stream:
                translation += text
            
            if translation:
                return translation
            else:
                print(f"Warning: Empty translation result")
                return f"Translation failed: Empty result"
            
    except Exception as e:
        print(f"Error in Claude API call: {e}")
        return f"Translation failed: {str(e)}"

def synthesize_with_claude(client: Anthropic, articles: Dict[str, str], target_lang: str, original_title: str) -> str:
    """
    Synthesizes multiple translated articles into one comprehensive article using Claude with streaming.
    
    Args:
        client: Anthropic client
        articles: Dictionary mapping language codes to translated article content
        target_lang: Target language code
        original_title: Original article title
        
    Returns:
        Synthesized article
    """
    # Create a structured input for Claude
    context = SYNTHESIS_CONTEXT(original_title, articles, target_lang)
    
    # We need to be careful about token limits, so we'll trim the content
    article_sections = []
    
    for lang, content in articles.items():
        # Trim content to a reasonable size
        trimmed_content = content[:128000] if len(content) > 128000 else content
        article_section = f"VERSION FROM {lang} WIKIPEDIA:\n{trimmed_content}\n\n---\n\n"
        article_sections.append(article_section)
    
    # Combine the context with article sections
    combined_input = context + "\n\n" + "".join(article_sections)
    
    prompt = SYNTHESIS_PROMPT(combined_input, target_lang)
    
    try:
        # Use the Anthropic SDK with streaming
        print(f"  Starting synthesis stream...")
        with client.messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=64000,
            messages=[
                {"role": "user", "content": prompt}
            ]
        ) as stream:
            # Collect the streamed response
            synthesis = ""
            for text in stream.text_stream:
                synthesis += text
            
            if synthesis:
                return synthesis
            else:
                print(f"Warning: Empty synthesis result")
                return f"Synthesis failed: Empty result"
            
    except Exception as e:
        print(f"Error in Claude API call: {e}")
        return f"Synthesis failed: {str(e)}"

def translate_article_worker(args):
    """
    Worker function for parallel translation.
    
    Args:
        args: Tuple containing (client, content, source_lang, target_lang, lang)
        
    Returns:
        Tuple of (lang, translated_content)
    """
    client, content, source_lang, target_lang, lang = args
    
    if lang == target_lang or content is None:
        return lang, content
        
    print(f"  Translating from {lang} to {target_lang}...")
    translated = translate_with_claude(client, content, lang, target_lang)
    
    if translated.startswith("Translation failed:"):
        print(f"  Warning: {translated}")
        return lang, None
    
    return lang, translated

def get_cache_key(title: str, language: str, max_translations: int) -> str:
    """
    Generate a unique cache key for an article request.
    
    Args:
        title: Article title
        language: Target language code
        max_translations: Maximum number of translations
        
    Returns:
        Cache key string
    """
    # Create a string that uniquely identifies this request
    cache_str = f"{language}/{title.replace(' ','_')}"
    
    # Hash it to create a filename-safe string
    return cache_str

def get_cache_path(cache_key: str) -> str:
    """
    Get the filesystem path for a cached article.
    
    Args:
        cache_key: Cache key string
        
    Returns:
        Path to the cached HTML file
    """
    return os.path.join(CACHE_DIR, f"{cache_key}.html")

def check_cache(title: str, language: str, max_translations: int) -> Optional[str]:
    """
    Check if an article is in the cache.
    
    Args:
        title: Article title
        language: Target language code
        max_translations: Maximum number of translations
        
    Returns:
        Path to cached file if it exists, None otherwise
    """
    cache_key = get_cache_key(title, language, max_translations)
    cache_path = get_cache_path(cache_key)
    
    if os.path.exists(cache_path):
        print(f"Cache hit: {cache_path}")
        return cache_path
    
    return None

def save_to_cache(title: str, language: str, max_translations: int, html_content: str) -> str:
    """
    Save an article to the cache.
    
    Args:
        title: Article title
        language: Target language code
        max_translations: Maximum number of translations
        html_content: HTML content to cache
        
    Returns:
        Path to the cached file
    """
    cache_key = get_cache_key(title, language, max_translations)
    cache_path = get_cache_path(cache_key)
    
    # Create cache directory if it doesn't exist
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    
    # Write the HTML content to the cache file
    with open(cache_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"Saved to cache: {cache_path}")
    return cache_path

def main():
    """Main function to run the Wikipedia article synthesizer."""
    parser = argparse.ArgumentParser(description='Synthesize Wikipedia articles from different languages')
    parser.add_argument('title', help='Title of the Wikipedia article')
    parser.add_argument('language', help='Target language code (e.g., en, es, fr)')
    parser.add_argument('--max_translations', type=int, default=5, 
                        help='Maximum number of translations to process (default: 5)')
    parser.add_argument('--output', help='Output file path (optional)')
    parser.add_argument('--api_key', help='Claude API key (optional, overrides default)')
    parser.add_argument('--threads', type=int, default=10,
                        help='Number of parallel threads for translation (default: 10)')
    parser.add_argument('--no-cache', action='store_true',
                        help='Disable caching (always generate fresh content)')
    
    args = parser.parse_args()
    
    # Update API key if provided
    global CLAUDE_API_KEY
    if args.api_key:
        CLAUDE_API_KEY = args.api_key
    
    # Check cache first unless no-cache is specified
    if not args.no_cache:
        cached_path = check_cache(args.title, args.language, args.max_translations)
        if cached_path:
            print(f"Using cached version from {cached_path}")
            
            if args.output:
                # Copy cache file to output if specified
                import shutil
                shutil.copy2(cached_path, args.output)
                print(f"Copied to {args.output}")
                
            else:
                # Print the cached content
                with open(cached_path, 'r', encoding='utf-8') as f:
                    print("\nCACHED ARTICLE:")
                    print("=" * 80)
                    print(f.read())
                    print("=" * 80)
                    
            return
    
    # Create Anthropic client
    client = Anthropic(api_key=CLAUDE_API_KEY)
    
    print(f"Step 1: Retrieving article '{args.title}' in {args.language}...")
    original_text, langlinks = get_wikipedia_article_with_tool(args.title, args.language)
    
    if not original_text or not langlinks:
        print(f"Error: Could not find article '{args.title}' in {args.language}")
        return
    
    print(f"Found article with {len(langlinks)} translations")
    
    # Select most relevant languages using Claude
    print(f"Step 2: Selecting the most relevant languages for this topic...")
    relevant_languages = select_relevant_languages(
        client, 
        args.title, 
        args.language, 
        langlinks, 
        max_translations=args.max_translations
    )
    
    # Create a list of (language, title) tuples for selected languages
    translations = []
    for lang_link in langlinks:
        if lang_link["language"] in relevant_languages:
            translations.append((lang_link["language"], lang_link["title"]))
    
    # Add the source language
    translations.append((args.language, args.title))
    
    print(f"Step 3: Retrieving content of translated articles...")
    translation_content = get_translation_content_with_tool(client, translations)
    
    print(f"Step 4: Translating articles in parallel (using {args.threads} threads)...")
    translated_articles = {}
    
    # Add the original language version first
    translated_articles[args.language] = original_text
    
    # Prepare arguments for parallel processing
    translation_args = []
    for lang, content in translation_content.items():
        if lang != args.language:  # Skip source language
            translation_args.append((client, content, lang, args.language, lang))
    
    # Use ThreadPool for parallel translations
    from multiprocessing.dummy import Pool as ThreadPool
    
    with ThreadPool(args.threads) as pool:
        # Map worker function to arguments
        results = pool.map(translate_article_worker, translation_args)
        
        # Process results
        for lang, translated in results:
            if translated is not None:
                translated_articles[lang] = translated
    
    print(f"Step 5: Synthesizing {len(translated_articles)} articles...")
    synthesized_article = synthesize_with_claude(client, translated_articles, args.language, args.title)
    
    if synthesized_article.startswith("Synthesis failed:"):
        print(f"Error: {synthesized_article}")
        return
    
    # Save to cache
    cache_path = save_to_cache(args.title, args.language, args.max_translations, synthesized_article)
    
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(synthesized_article)
        print(f"Synthesized article saved to {args.output}")
    else:
        print("\nSYNTHESIZED ARTICLE:")
        print("=" * 80)
        print(synthesized_article)
        print("=" * 80)

if __name__ == "__main__":
    main()