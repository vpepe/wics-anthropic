#!/usr/bin/env python3
"""
Wikipedia Synthesizer

This script takes a Wikipedia article in one language, finds translations,
translates them all to the target language using Claude AI, and synthesizes
them into a comprehensive article.
"""

import argparse
import json
import os
import time
from typing import Dict, List, Optional, Tuple
import wikipediaapi
from anthropic import Anthropic

# Claude API information
CLAUDE_API_KEY = "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"
CLAUDE_MODEL = "claude-3-7-sonnet-latest"
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"  # API endpoint

def get_wikipedia_article(title: str, language: str) -> Tuple[Optional[str], Optional[Dict]]:
    """
    Retrieves a Wikipedia article in the specified language.
    
    Args:
        title: The title of the Wikipedia article
        language: The language code (e.g., 'en', 'es', 'fr')
        
    Returns:
        Tuple containing article text and language links if successful, else (None, None)
    """
    wiki_wiki = wikipediaapi.Wikipedia(
        language=language,
        extract_format=wikipediaapi.ExtractFormat.WIKI,
        user_agent='WikipediaSynthesizer/1.0'
    )
    
    page = wiki_wiki.page(title)
    
    if not page.exists():
        return None, None
    
    return page.text, page.langlinks

def get_all_translations(langlinks: Dict) -> List[Tuple[str, str]]:
    """
    Retrieves all available translations for an article.
    
    Args:
        langlinks: Dictionary of language links from wikipediaapi
        
    Returns:
        List of tuples containing (language_code, article_title)
    """
    return [(lang, link.title) for lang, link in langlinks.items()]

def get_translation_content(translations: List[Tuple[str, str]]) -> Dict[str, Optional[str]]:
    """
    Retrieves the content of each translated article.
    
    Args:
        translations: List of tuples containing (language_code, article_title)
        
    Returns:
        Dictionary mapping language codes to article content
    """
    translation_content = {}
    
    for lang, title in translations:
        print(f"  Retrieving {lang} article: {title}")
        wiki_wiki = wikipediaapi.Wikipedia(
            language=lang,
            extract_format=wikipediaapi.ExtractFormat.WIKI,
            user_agent='WikipediaSynthesizer/1.0'
        )
        
        page = wiki_wiki.page(title)
        
        if page.exists():
            translation_content[lang] = page.text
        else:
            translation_content[lang] = None
            
    return translation_content

def translate_with_claude(text: str, source_lang: str, target_lang: str) -> str:
    """
    Translates text using the Claude API with streaming.
    
    Args:
        text: The text to translate
        source_lang: Source language code
        target_lang: Target language code
        
    Returns:
        Translated text
    """
    # Skip translation if source and target are the same
    if source_lang == target_lang:
        return text
    
    # Create Anthropic client
    client = Anthropic(api_key=CLAUDE_API_KEY)
    
    # Limit text length to handle API constraints (Claude has max token limits)
    text = text[:50000] if len(text) > 50000 else text
    
    prompt = f"""Translate the following text from {source_lang} to {target_lang}. 
Maintain the original section structure and formatting as much as possible.

TEXT TO TRANSLATE:
{text}

TRANSLATION:"""
    
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

def synthesize_with_claude(articles: Dict[str, str], target_lang: str, original_title: str) -> str:
    """
    Synthesizes multiple translated articles into one comprehensive article using Claude with streaming.
    
    Args:
        articles: Dictionary mapping language codes to translated article content
        target_lang: Target language code
        original_title: Original article title
        
    Returns:
        Synthesized article
    """
    # Create Anthropic client
    client = Anthropic(api_key=CLAUDE_API_KEY)
    
    # Create a structured input for Claude
    context = f"""I have collected versions of the Wikipedia article '{original_title}' from {len(articles)} different language editions, and translated them all to {target_lang}.

I will now provide each version. Your task is to synthesize these into a single comprehensive article."""
    
    # We need to be careful about token limits, so we'll trim the content and 
    # maybe need to batch process if there are many languages
    article_sections = []
    
    for lang, content in articles.items():
        # Trim content to a reasonable size
        trimmed_content = content[:15000] if len(content) > 15000 else content
        article_section = f"VERSION FROM {lang} WIKIPEDIA:\n{trimmed_content}\n\n---\n\n"
        article_sections.append(article_section)
    
    # Combine the context with article sections
    combined_input = context + "\n\n" + "".join(article_sections)
    
    prompt = f"""{combined_input}

Please synthesize these different Wikipedia versions into a single, comprehensive article in {target_lang}. 
Combine information from all sources, resolve any contradictions, and create a well-structured article that 
contains the most accurate and complete information from all language editions.

The article should:
1. Follow Wikipedia's neutral point of view
2. Maintain a proper encyclopedic tone
3. Include all important facts from the various language versions
4. Be well-structured with appropriate sections and subsections
5. Resolve any contradictory information by noting different perspectives or choosing the most reliable information

SYNTHESIZED ARTICLE:"""
    
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
            chunk_count = 0
            for text in stream.text_stream:
                synthesis += text
                # Print a progress marker every few chunks
                chunk_count += 1
                if chunk_count % 10 == 0:
                    print(".", end="", flush=True)
            
            print()  # New line after progress dots
            
            if synthesis:
                return synthesis
            else:
                print(f"Warning: Empty synthesis result")
                return f"Synthesis failed: Empty result"
            
    except Exception as e:
        print(f"Error in Claude API call: {e}")
        return f"Synthesis failed: {str(e)}"

def main():
    """Main function to run the Wikipedia article synthesizer."""
    parser = argparse.ArgumentParser(description='Synthesize Wikipedia articles from different languages')
    parser.add_argument('title', help='Title of the Wikipedia article')
    parser.add_argument('language', help='Target language code (e.g., en, es, fr)')
    parser.add_argument('--max_translations', type=int, default=5, 
                        help='Maximum number of translations to process (default: 5)')
    parser.add_argument('--output', help='Output file path (optional)')
    parser.add_argument('--api_key', help='Claude API key (optional, overrides default)')
    
    args = parser.parse_args()
    
    # Update API key if provided
    global CLAUDE_API_KEY
    if args.api_key:
        CLAUDE_API_KEY = args.api_key
    
    print(f"Step 1: Retrieving article '{args.title}' in {args.language}...")
    original_text, langlinks = get_wikipedia_article(args.title, args.language)
    
    if not original_text or not langlinks:
        print(f"Error: Could not find article '{args.title}' in {args.language}")
        return
    
    print(f"Found article with {len(langlinks)} translations")
    
    translations = get_all_translations(langlinks) + [(args.language, args.title)]

    print(f"Step 2: Retrieving content of translated articles...")
    translation_content = get_translation_content(translations)
    
    # Convert dictionary to sorted list of tuples by content length
    content_with_length = [(lang, content) for lang, content in translation_content.items() if content is not None]
    sorted_by_length = sorted(content_with_length, key=lambda x: len(x[1]), reverse=True)
    
    # Print top 5 longest languages
    if sorted_by_length:
        print(f"Top 5 longest languages: {[lang for lang, _ in sorted_by_length[:5]]}")
    
    # Limit translations to max_translations
    if len(sorted_by_length) > args.max_translations:
        # Check if source language is in top articles by length
        source_lang_in_top = any(lang == args.language for lang, _ in sorted_by_length[:args.max_translations])
        
        if not source_lang_in_top and original_text:
            # If source language not in top articles, replace the last one with source language
            selected_translations = sorted_by_length[:args.max_translations-1]
            # Add source language to selected translations
            selected_translations.append((args.language, original_text))
        else:
            # If source language already in top articles, just use top n
            selected_translations = sorted_by_length[:args.max_translations]
    else:
        selected_translations = sorted_by_length
        
        # Make sure source language is included if not already
        if not any(lang == args.language for lang, _ in selected_translations) and original_text:
            selected_translations.append((args.language, original_text))
    
    print(f"Step 3: Translating articles to {args.language}...")
    translated_articles = {}
    
    # Add the original language version first
    translated_articles[args.language] = original_text
    
    # Translate each article
    for lang, content in selected_translations:
        if lang != args.language:  # Skip translating source language
            print(f"  Translating from {lang} to {args.language}...")
            translated = translate_with_claude(content, lang, args.language)
            if not translated.startswith("Translation failed:"):
                translated_articles[lang] = translated
            else:
                print(f"  Warning: {translated}")
            
            # Add a short delay to avoid rate limits
            time.sleep(1)
    
    print(f"Step 4: Synthesizing {len(translated_articles)} articles...")
    synthesized_article = synthesize_with_claude(translated_articles, args.language, args.title)
    
    if synthesized_article.startswith("Synthesis failed:"):
        print(f"Error: {synthesized_article}")
        return
    
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
