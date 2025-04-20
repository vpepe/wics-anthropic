"""
Wikipedia Fuzzy Search Module

This module enhances the Wikipedia search functionality with fuzzy matching
capabilities to handle misspellings and provide better search results.
"""

import wikipediaapi
import wikipedia
import re
import json
from typing import List, Dict, Tuple, Optional, Any
import tiktoken

# Global variable to store the last searched title
_last_searched_title = None

def get_full_article_content(title: str, language: str) -> Tuple[Optional[str], Optional[List[Dict]]]:
    """
    Retrieves the full content of an article, including all pages and language links.
    
    Args:
        title: The title of the Wikipedia article
        language: The language code
        
    Returns:
        Tuple containing article text and language links if successful, else (None, None)
    """
    full_text = ""
    current_page = 0
    langlinks = None
    
    while True:
        try:
            result = search_wikipedia(title, language, current_page)
            
            if not result["found"]:
                print(f"Article not found: {result.get('error', 'Unknown error')}")
                return None, None
            
            full_text += result["content"]
            
            # Store langlinks from first page
            if current_page == 0:
                langlinks = result["langlinks"]
            
            # Check if we've reached the last page
            if current_page >= result["total_pages"] - 1:
                break
                
            current_page += 1
            print(f"  Retrieved page {current_page} of {result['total_pages']}")
            
        except Exception as e:
            print(f"Error retrieving Wikipedia article: {e}")
            if full_text and langlinks:
                # Return what we have so far
                return full_text, langlinks
            return None, None
    
    return full_text, langlinks

def get_last_searched_title() -> Optional[str]:
    """
    Get the title that was actually used in the last search.
    Useful for detecting when fuzzy search used a different title than requested.
    
    Returns:
        The actual title used in the last search, or None if no search has been performed
    """
    global _last_searched_title
    return _last_searched_title

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
    Function to implement the search_wikipedia tool functionality with article text.
    
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

def perform_fuzzy_search(title: str, language: str, max_results: int = 5) -> List[Dict[str, str]]:
    """
    Perform a fuzzy search using Wikipedia API's search function.
    
    Args:
        title: The search query
        language: Language code
        max_results: Maximum number of results to return
        
    Returns:
        List of dictionaries with search results
    """
    wiki_wiki = wikipediaapi.Wikipedia(
        language=language,
        extract_format=wikipediaapi.ExtractFormat.WIKI,
        user_agent='WikipediaSynthesizer/1.0'
    )
    
    # Use search method to find articles related to the title
    wikipedia.set_lang(language)
    search_results = wikipedia.search(title)
    
    # Format results as a list of dictionaries
    formatted_results = []
    for result_title in search_results:
        try:
            # Get the article page
            page = wiki_wiki.page(result_title)
            
            # Get a snippet of the article content
            snippet = page.summary[:150] + "..." if len(page.summary) > 150 else page.summary
            
            formatted_results.append({
                "title": result_title,
                "description": snippet,
                "url": page.canonicalurl,
                "snippet": snippet
            })
        except Exception as e:
            print(f"Error retrieving page for {result_title}: {e}")
    
    return formatted_results

# Claude evaluation prompt for selecting the best result
SEARCH_EVALUATION_PROMPT = """
I need your help selecting the most relevant Wikipedia article from search results for a user query.

User query: "{user_query}"

Search results:
{search_results}

Please select the single most relevant article from these results for the user's query. 
Consider how closely the article title and content match the intent of the query, 
especially in cases where the query might have typos or misspellings.

Format your response as a JSON object like this:
{{
  "selected_article": "Exact title of the selected article",
  "rationale": "Brief explanation of why this article is the most relevant"
}}
"""

def evaluate_search_results(client, user_query: str, search_results: List[Dict[str, str]]) -> str:
    """
    Uses Claude to evaluate search results and select the most relevant one.
    
    Args:
        client: Anthropic client
        user_query: The original search query
        search_results: List of search results to evaluate
        
    Returns:
        Title of the selected article
    """
    # Format search results for the prompt
    results_text = ""
    for i, result in enumerate(search_results):
        results_text += f"{i+1}. Title: {result['title']}\n"
        results_text += f"   Description: {result['description']}\n"
        results_text += f"   Content snippet: {result['snippet']}\n\n"
    
    # Prepare the prompt
    prompt = SEARCH_EVALUATION_PROMPT.format(
        user_query=user_query,
        search_results=results_text
    )
    
    try:
        # Make API call to Claude
        response = client.messages.create(
            model="claude-3-7-sonnet-latest",
            max_tokens=1000,
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.2
        )
        
        # Extract JSON response
        response_text = response.content[0].text
        
        # Find JSON object in response
        json_match = re.search(r'({[\s\S]*})', response_text)
        
        if json_match:
            try:
                json_data = json.loads(json_match.group(1))
                selected_article = json_data.get("selected_article", "")
                
                if selected_article:
                    return selected_article
                    
            except json.JSONDecodeError:
                print(f"Failed to parse JSON response: {response_text}")
        else:
            print(f"Failed to extract JSON from response: {response_text}")
            
    except Exception as e:
        print(f"Error in Claude API call: {e}")
    
    # Fallback: return the first search result if Claude fails
    return search_results[0]["title"] if search_results else ""

def get_wikipedia_article_with_fuzzy_search(
    client,
    title: str,
    language: str,
    first_article: bool = False
) -> Tuple[Optional[str], Optional[List[Dict]]]:
    """
    Retrieves a Wikipedia article, trying exact matches first (in the requested language,
    then in fallback languages), and only then resorting to fuzzy search.
    
    Args:
        client: Anthropic client
        title: The title of the Wikipedia article
        language: The language code
        first_article: Flag to allow fuzzy search in fallback languages
    Returns:
        Tuple containing article text and language links if successful, else (None, None)
    """
    global _last_searched_title
    print(f"Searching for article: {title} in {language}")
    
    # Normalize title
    title = title.replace("_", " ")
    
    # 1) Exact match in requested language
    exact_result = search_wikipedia(title, language, 0)
    if exact_result.get("found"):
        _last_searched_title = title
        return get_full_article_content(title, language)
    
    # 2) Exact match in fallback languages
    for fallback_lang in ["en", "es", "fr", "de", "ru", "zh", "ja"]:
        if fallback_lang == language:
            continue
        print(f"Checking exact match in fallback language: {fallback_lang}")
        fb_exact = search_wikipedia(title, fallback_lang, 0)
        if fb_exact.get("found"):
            print(f"Found exact article in {fallback_lang}")
            _last_searched_title = title
            return get_full_article_content(title, fallback_lang)
    
    # 3) Fuzzy search in requested language
    print("Article not found by exact match. Trying fuzzy search in primary language...")
    primary_fuzzy = perform_fuzzy_search(title, language)
    if primary_fuzzy:
        selected = evaluate_search_results(client, title, primary_fuzzy)
        if selected:
            print(f"Selected article by fuzzy in {language}: {selected}")
            _last_searched_title = selected
            return get_full_article_content(selected, language)
        else:
            print("Fuzzy search returned candidates, but none were selected.")
    else:
        print("No fuzzy-search results in primary language.")
    
    # 4) (Optional) Fuzzy search in fallback languages, if this is the first article
    if first_article:
        for fallback_lang in ["en", "es", "fr", "de", "ru", "zh", "ja"]:
            if fallback_lang == language:
                continue
            print(f"Trying fuzzy search in fallback language: {fallback_lang}")
            fb_fuzzy = perform_fuzzy_search(title, fallback_lang)
            if fb_fuzzy:
                selected = evaluate_search_results(client, title, fb_fuzzy)
                if selected:
                    print(f"Found article in {fallback_lang} by fuzzy: {selected}")
                    _last_searched_title = selected
                    return get_full_article_content(selected, fallback_lang)
        print("No fuzzy-search results in fallback languages.")
    
    # Not found anywhere
    return None, None




