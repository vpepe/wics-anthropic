"""
Fuzzy Cache Matching Module for Linguapedia

This module enhances the caching system by using Claude to determine
if a search query is similar enough to an existing cached article to 
redirect to it, rather than creating a new one.
"""

import os
import re
import json
import difflib
from typing import List, Dict, Optional, Tuple
from anthropic import Anthropic

# Cache similarity threshold
SIMILARITY_THRESHOLD = 0.8

# Function to get Claude to evaluate cache matches
CACHE_MATCH_PROMPT = """
I need your help determining if a user's search query is similar enough to existing cached articles that we should redirect to one of them, rather than creating a new article.

User search query: "{query}"
Language: {language}

Existing cached articles in this language:
{cached_articles}

Please determine if any of these cached articles are similar enough to the user's query that we should redirect to it instead of creating a new article. Consider:
1. If the query is a slight misspelling of an existing article
2. If the query is a synonym or alternative form of an existing article
3. If the query is a more or less specific version of an existing article (e.g. "Albert Einstein" vs "Einstein")
4. If the query is a related concept that would be fully covered by an existing article

Format your response as a JSON object like this:
{{
  "redirect": true or false,
  "filename": "exact name of the file to redirect to, if any",
  "confidence": 0-1 score of how confident you are in this match,
  "rationale": "brief explanation of your decision"
}}

Be relatively conservative in your matching - only suggest a redirect if you're confident the existing article would satisfy the user's query. We prefer to create new articles when in doubt.
"""

def get_cached_articles(cache_dir: str, language: str) -> List[Dict]:
    """
    Get a list of all cached articles for a specific language.
    
    Args:
        cache_dir: Path to the cache directory
        language: Language code to filter by
        
    Returns:
        List of dictionaries with info about cached articles
    """
    cache_dir = cache_dir + "/" + language + "/"
    

    cached_articles = []
    
    if not os.path.exists(cache_dir):
        return cached_articles
    
    for filename in os.listdir(cache_dir):
        path = os.path.join(cache_dir, filename)
        
        cached_articles.append({
            "filename": filename,
            "path": path,
        })

    return cached_articles

def basic_similarity_check(query: str, cached_articles: List[Dict]) -> Optional[Dict]:
    """
    Perform a basic similarity check using difflib to see if there's a very close match.
    This can catch obvious cases without needing to call Claude.
    
    Args:
        query: User's search query
        cached_articles: List of cached articles
        
    Returns:
        Matching article dict if a high-confidence match is found, None otherwise
    """
    # Normalize the query
    query_normalized = query.lower().strip()
    
    # Check for exact matches first
    for article in cached_articles:
        article_name_normalized = article["filename"].lower().strip()
        
        # If exact match, return immediately
        if query_normalized == article_name_normalized:
            return article
    
    # Check for high similarity matches
    for article in cached_articles:
        article_name_normalized = article["filename"].lower().strip()
        
        # Use difflib's SequenceMatcher to get similarity ratio
        similarity = difflib.SequenceMatcher(None, query_normalized, article_name_normalized).ratio()
        
        # If very similar, return the match
        if similarity > SIMILARITY_THRESHOLD:
            return article
    
    return None

def claude_cache_match(client: Anthropic, query: str, language: str, cached_articles: List[Dict]) -> Tuple[bool, Optional[Dict], float, str]:
    """
    Use Claude to determine if the query should redirect to an existing cached article.
    
    Args:
        client: Anthropic client
        query: User's search query
        language: Language code
        cached_articles: List of cached articles
        
    Returns:
        Tuple of (should_redirect, matching_article_dict, confidence, rationale)
    """
    if not cached_articles:
        return False, None, 0.0, "No cached articles available"
    
    # Format cached articles for the prompt
    cached_articles_text = ""
    for i, article in enumerate(cached_articles):
        cached_articles_text += f"{i+1}. {article['filename']}\n"
    
    # Prepare the prompt
    prompt = CACHE_MATCH_PROMPT.format(
        query=query,
        language=language,
        cached_articles=cached_articles_text
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
        import re
        json_match = re.search(r'({[\s\S]*})', response_text)
        
        if json_match:
            try:
                json_data = json.loads(json_match.group(1))
                should_redirect = json_data.get("redirect", False)
                article_name = json_data.get("filename", "")
                confidence = json_data.get("confidence", 0.0)
                rationale = json_data.get("rationale", "No rationale provided")
                
                # Find the matching article dict
                matching_article = None
                if should_redirect and article_name:
                    for article in cached_articles:
                        if article["filename"].lower() == article_name.lower():
                            matching_article = article
                            break
                
                return should_redirect, matching_article, confidence, rationale
                
            except json.JSONDecodeError:
                print(f"Failed to parse JSON response: {response_text}")
        else:
            print(f"Failed to extract JSON from response: {response_text}")
            
    except Exception as e:
        print(f"Error in Claude API call: {e}")
    
    return False, None, 0.0, "Error processing the request"

def find_fuzzy_cache_match(client: Anthropic, query: str, language: str, cache_dir: str) -> Tuple[bool, Optional[str], float, str]:
    """
    Main function to determine if a query should redirect to an existing cached article.
    
    Args:
        client: Anthropic client
        query: User's search query
        language: Language code
        cache_dir: Path to the cache directory
        
    Returns:
        Tuple of (should_redirect, redirect_path, confidence, rationale)
    """
    # Get all cached articles for this language
    cached_articles = get_cached_articles(cache_dir, language)
    
    if not cached_articles:
        return False, None, 0.0, "No cached articles available"
    
    # Try basic similarity check first for efficiency
    basic_match = basic_similarity_check(query, cached_articles)
    if basic_match:
        return True, basic_match["path"], 1.0, f"Exact or near-exact match found: {basic_match['filename']}"
    
    # If no obvious match, use Claude for more sophisticated matching
    should_redirect, matching_article, confidence, rationale = claude_cache_match(
        client, query, language, cached_articles
    )
    
    if should_redirect and matching_article:
        return True, matching_article["path"], confidence, rationale
    
    return False, None, confidence, rationale