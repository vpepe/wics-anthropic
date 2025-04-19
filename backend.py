import wikipediaapi
import sys

def get_article_translations(title, source_lang="en"):
    """
    Get all language translations available for a Wikipedia article.
    
    Args:
        title (str): The title of the Wikipedia article
        source_lang (str): The language code of the source article (default: "en")
        
    Returns:
        dict: A dictionary with source article info and translations
    """
    # Create a Wikipedia API object with a user agent
    user_agent = "ArticleTranslationScript/1.0 (your-email@example.com)"
    wiki = wikipediaapi.Wikipedia(user_agent, source_lang)
    
    # Try to get the page
    page = wiki.page(title)
    
    # Check if page exists
    if not page.exists():
        return {"error": f"Article '{title}' not found in {source_lang} Wikipedia"}
    
    # Get language links
    langlinks = page.langlinks
    
    # Format results
    translations = {lang: langlinks[lang].title for lang in langlinks}
    
    result = {
        "source": f"({source_lang}) {page.title}",
        "translations": translations
    }
    
    return result

def main():
    # Get input from user
    if len(sys.argv) > 1:
        title = sys.argv[1]
    else:
        title = input("Enter the Wikipedia article title: ")
    
    if len(sys.argv) > 2:
        source_lang = sys.argv[2]
    else:
        source_lang = input("Enter the language code (e.g., 'en', 'fr', 'ja', etc.) or press Enter for English: ")
    
    if not source_lang:
        source_lang = "en"  # Default to English
    
    # Get translations
    result = get_article_translations(title, source_lang)
    
    # Display results
    if "error" in result:
        print(f"Error: {result['error']}")
    else:
        print(f"\nSource article: {result['source']}")
        print(f"Found {len(result['translations'])} translations:")
        
        # Print translations sorted by language code
        for lang_code in sorted(result['translations'].keys()):
            print(f"  ({lang_code}) {result['translations'][lang_code]}")

if __name__ == "__main__":
    main()
