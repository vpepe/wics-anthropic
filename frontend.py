import { useState } from 'react';

const WikiTranslator = () => {
  const [searchTerm, setSearchTerm] = useState('');
  const [sourceLang, setSourceLang] = useState('en');
  const [results, setResults] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedTranslations, setSelectedTranslations] = useState([]);
  const [synthesisResult, setSynthesisResult] = useState('');

  // Common language codes and their names for the dropdown
  const commonLanguages = [
    { code: 'en', name: 'English' },
    { code: 'es', name: 'Spanish' },
    { code: 'fr', name: 'French' },
    { code: 'de', name: 'German' },
    { code: 'it', name: 'Italian' },
    { code: 'pt', name: 'Portuguese' },
    { code: 'ru', name: 'Russian' },
    { code: 'ja', name: 'Japanese' },
    { code: 'zh', name: 'Chinese' },
    { code: 'ar', name: 'Arabic' },
    { code: 'hi', name: 'Hindi' },
    { code: 'ko', name: 'Korean' }
  ];

  // Simulated API call to backend - in a real app, this would call your Python backend
  const searchWikipedia = () => {
    if (!searchTerm.trim()) {
      setError('Please enter a search term');
      return;
    }

    setIsLoading(true);
    setError(null);
    
    // This is a simulation - in a real implementation, this would be an actual API call
    setTimeout(() => {
      try {
        // Example response structure based on your backend
        const mockResponse = {
          source: `(${sourceLang}) ${searchTerm}`,
          translations: {
            en: searchTerm,
            es: `${searchTerm} (Español)`,
            fr: `${searchTerm} (Français)`,
            de: `${searchTerm} (Deutsch)`,
            it: `${searchTerm} (Italiano)`,
            ja: `${searchTerm} (日本語)`,
            zh: `${searchTerm} (中文)`,
            ru: `${searchTerm} (Русский)`,
          }
        };
        
        setResults(mockResponse);
        setIsLoading(false);
      } catch (err) {
        setError('An error occurred while fetching data');
        setIsLoading(false);
      }
    }, 1000);
  };

  const handleCheckboxChange = (langCode) => {
    if (selectedTranslations.includes(langCode)) {
      setSelectedTranslations(selectedTranslations.filter(code => code !== langCode));
    } else {
      setSelectedTranslations([...selectedTranslations, langCode]);
    }
  };

  const synthesizeContent = () => {
    if (selectedTranslations.length === 0) {
      setError('Please select at least one language for synthesis');
      return;
    }
    
    setIsLoading(true);
    
    // In a real implementation, this would call your backend to gather content from each language
    setTimeout(() => {
      const synthesis = `
# Synthesized Article: ${searchTerm}

## Content from ${selectedTranslations.length} languages:
${selectedTranslations.map(lang => {
  const langName = commonLanguages.find(l => l.code === lang)?.name || lang;
  return `
### ${langName} Version
The article "${results.translations[lang] || `${searchTerm} (${lang})`}" contains unique cultural perspectives. In a real implementation, this would contain actual content synthesized from the ${langName} Wikipedia.
  
Some unique information found only in the ${langName} Wikipedia version:
- Cultural significance specific to ${langName}-speaking regions
- Different historical perspective
- Additional facts and statistics relevant to ${langName}-speaking audience
`;
}).join('\n')}

## Synthesis of Perspectives
This synthesized version combines knowledge across all selected language versions, highlighting:
- Cross-cultural similarities and differences
- Supplementary information found only in specific language editions
- Different cultural emphases and historical interpretations

In a full implementation, this would process the actual content from each language's Wikipedia page and intelligently synthesize the information.
`;
      
      setSynthesisResult(synthesis);
      setIsLoading(false);
    }, 1500);
  };

  return (
    <div className="p-6 max-w-6xl mx-auto bg-white rounded-lg shadow-lg">
      <h1 className="text-3xl font-bold text-blue-800 mb-6">Wikipedia Translation Synthesizer</h1>
      
      <div className="mb-8 bg-blue-50 p-4 rounded-lg">
        <p className="text-gray-700">
          This tool finds all available translations of a Wikipedia article and can synthesize content across different language versions to provide a more complete perspective.
        </p>
      </div>
      
      <div className="flex flex-col md:flex-row gap-4 mb-6">
        <div className="flex-grow">
          <label htmlFor="search-term" className="block text-gray-700 font-medium mb-2">Wikipedia Article Title</label>
          <input
            id="search-term"
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Enter article title (e.g., 'Albert Einstein')"
            className="w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        
        <div className="w-full md:w-48">
          <label htmlFor="source-lang" className="block text-gray-700 font-medium mb-2">Source Language</label>
          <select
            id="source-lang"
            value={sourceLang}
            onChange={(e) => setSourceLang(e.target.value)}
            className="w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {commonLanguages.map(lang => (
              <option key={lang.code} value={lang.code}>
                {lang.name} ({lang.code})
              </option>
            ))}
          </select>
        </div>
        
        <div className="w-full md:w-48 self-end">
          <button
            onClick={searchWikipedia}
            disabled={isLoading}
            className="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 px-4 rounded-md disabled:bg-blue-300"
          >
            {isLoading ? 'Searching...' : 'Search'}
          </button>
        </div>
      </div>
      
      {error && (
        <div className="mb-6 p-4 bg-red-50 text-red-700 rounded-md">
          {error}
        </div>
      )}
      
      {results && (
        <div className="mb-8">
          <h2 className="text-2xl font-semibold mb-4">Available Translations</h2>
          <p className="mb-4">Source article: <span className="font-medium">{results.source}</span></p>
          <p className="mb-2">Select languages to include in synthesis:</p>
          
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-2">
            {Object.keys(results.translations).map(langCode => {
              const langName = commonLanguages.find(l => l.code === langCode)?.name || langCode;
              return (
                <div key={langCode} className="flex items-center space-x-2">
                  <input
                    type="checkbox"
                    id={`lang-${langCode}`}
                    checked={selectedTranslations.includes(langCode)}
                    onChange={() => handleCheckboxChange(langCode)}
                    className="h-5 w-5 text-blue-600"
                  />
                  <label htmlFor={`lang-${langCode}`} className="text-gray-700">
                    ({langCode}) {langName}: {results.translations[langCode]}
                  </label>
                </div>
              );
            })}
          </div>
          
          <div className="mt-6">
            <button
              onClick={synthesizeContent}
              disabled={isLoading || selectedTranslations.length === 0}
              className="bg-green-600 hover:bg-green-700 text-white font-medium py-2 px-6 rounded-md disabled:bg-green-300"
            >
              {isLoading ? 'Synthesizing...' : 'Synthesize Selected Languages'}
            </button>
          </div>
        </div>
      )}
      
      {synthesisResult && (
        <div className="mt-8 border-t pt-6">
          <h2 className="text-2xl font-semibold mb-4">Synthesized Content</h2>
          <div className="whitespace-pre-line bg-gray-50 p-6 rounded-lg border">
            {synthesisResult}
          </div>
          <div className="mt-4">
            <button
              onClick={() => {
                const blob = new Blob([synthesisResult], { type: 'text/markdown' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `${searchTerm}-synthesized.md`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
              }}
              className="bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 px-4 rounded-md"
            >
              Download as Markdown
            </button>
          </div>
        </div>
      )}
      
      <div className="mt-8 text-sm text-gray-500">
        <p>Note: This frontend demo simulates the functionality. In a real implementation, it would connect to your Python backend to retrieve actual Wikipedia content across languages.</p>
      </div>
    </div>
  );
};

export default WikiTranslator;
