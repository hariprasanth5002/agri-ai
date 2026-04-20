import React, { Component, useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import { Volume2, VolumeX, Languages, Loader2 } from 'lucide-react';

class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, errorStr: '' };
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, errorStr: error.toString() };
  }
  render() {
    if (this.state.hasError) {
      return <div className="markdown-body" style={{color: 'red'}}>UI Render Error: {this.state.errorStr}. Raw fallback: {this.props.rawText}</div>;
    }
    return this.props.children;
  }
}


const MessageBubble = ({ role, content, images, originalContent, voiceLang }) => {
  const isAssistant = role === 'assistant';
  
  // If originalContent exists, 'content' is actually a pre-translated text from App.jsx
  // We initialize translatedText to that content so the UI shows it by default.
  const [translatedText, setTranslatedText] = useState(originalContent ? content : null);
  const [isTranslating, setIsTranslating] = useState(false);
  const [targetLang, setTargetLang] = useState(voiceLang || 'hi'); 
  
  const [isPlaying, setIsPlaying] = useState(false);
  const isPlayingRef = useRef(false);
  const currentAudioRef = useRef(null);

  const setPlayingState = (state) => {
      setIsPlaying(state);
      isPlayingRef.current = state;
  };

  // Stop playing if component unmounts
  useEffect(() => {
    return () => {
      if (window.speechSynthesis) window.speechSynthesis.cancel();
      if (currentAudioRef.current) {
          currentAudioRef.current.pause();
          currentAudioRef.current = null;
      }
    }
  }, []);

  const handleTranslate = async () => {
    // Use originalContent as the base if it exists, otherwise use content
    const baseText = originalContent || content;
    if (!baseText) return;
    
    // If English is selected, simply revert to original text
    if (targetLang === 'en') {
      setTranslatedText(null);
      return;
    }
    
    setIsTranslating(true);
    try {
        const textToTsl = typeof baseText === 'string' ? baseText : JSON.stringify(baseText);
        
        // Chunk the text to gracefully avoid Google's URI 414 (Length Too Long) constraint
        const chunks = textToTsl.split('\n');
        let translatedChunks = [];
        
        for (let chunk of chunks) {
            if (!chunk.trim()) {
                translatedChunks.push('');
                continue;
            }
            // Fetch chunk via free GTx endpoint
            const url = `https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=${targetLang}&dt=t&q=${encodeURIComponent(chunk)}`;
            const res = await fetch(url);
            const data = await res.json();
            
            if (data && data[0]) {
                const finalStr = data[0].map(x => x[0]).join('');
                translatedChunks.push(finalStr);
            } else {
                translatedChunks.push(chunk); // fallback if something odd happens
            }
        }
        
        setTranslatedText(translatedChunks.join('\n'));
    } catch (e) {
        console.error('Translation failed', e);
        alert("Translation service is currently unavailable or text is too large.");
    }
    setIsTranslating(false);
  };

  const handleSpeak = async () => {
    if (isPlaying) {
        if (window.speechSynthesis) window.speechSynthesis.cancel();
        if (currentAudioRef.current) {
            currentAudioRef.current.pause();
            currentAudioRef.current = null;
        }
        setPlayingState(false);
        return;
    }
    
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    if (currentAudioRef.current) {
        currentAudioRef.current.pause();
        currentAudioRef.current = null;
    }
    
    // Use translatedText (either auto-translated or manual) or the base content
    const baseText = originalContent || content;
    const textToSpeak = translatedText || (typeof baseText === 'string' ? baseText : JSON.stringify(baseText));
    const cleanedText = textToSpeak.replace(/[\*#_```-]/g, '');
    
    // Map short codes to full BCP-47 locale tags for Indian languages
    const localeMap = { 'hi': 'hi-IN', 'ta': 'ta-IN', 'te': 'te-IN', 'bn': 'bn-IN', 'mr': 'mr-IN' };
    
    // Determine language code: manual translation target, or auto-voice lang, or default English
    const currentLang = translatedText ? 
                        (originalContent && translatedText === content ? voiceLang : targetLang) 
                        : 'en';
                        
    const langCode = localeMap[currentLang] || (currentLang === 'en' ? 'en-IN' : currentLang);
    const shortLang = currentLang;
    
    setPlayingState(true);

    // Some OS (like Windows) register broken stub voices for regional languages that fail silently.
    // We only trust native Web Speech API for English and Hindi.
    const isReliableNativeLang = ['en-IN', 'hi-IN'].includes(langCode);

    if (isReliableNativeLang && 'speechSynthesis' in window) {
        const voices = window.speechSynthesis.getVoices();
        const targetedVoice = voices.find(v => v.lang.replace('_', '-') === langCode) || 
                              voices.find(v => v.lang.replace('_', '-').toLowerCase().startsWith(langCode.split('-')[0].toLowerCase()));
        
        const msg = new SpeechSynthesisUtterance(cleanedText);
        msg.lang = langCode;
        if (targetedVoice) msg.voice = targetedVoice;
        
        msg.onend = () => setPlayingState(false);
        msg.onerror = () => setPlayingState(false);
        window.speechSynthesis.speak(msg);
        return;
    }
    
    // Cloud Fallback Strategy: Google Translate Audio stream
    try {
        const words = cleanedText.split(/\s+/);
        const chunks = [];
        let currentChunk = '';
        for (const w of words) {
            if ((currentChunk + ' ' + w).length < 150) {
                currentChunk += (currentChunk ? ' ' : '') + w;
            } else {
                if (currentChunk) chunks.push(currentChunk);
                currentChunk = w;
            }
        }
        if (currentChunk) chunks.push(currentChunk);

        let currentIdx = 0;
        const playNext = () => {
            if (!isPlayingRef.current || currentIdx >= chunks.length) {
                setPlayingState(false);
                return;
            }
            const chunk = chunks[currentIdx];
            const apiBase = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8001").replace(/\/+$/, "");
            const url = `${apiBase}/tts?lang=${shortLang}&text=${encodeURIComponent(chunk)}`;
            const audio = new Audio(url);
            currentAudioRef.current = audio;
            
            if (shortLang !== 'en') {
                 audio.playbackRate = 1.15; 
            }
            
            audio.onended = () => {
                currentIdx++;
                playNext();
            };
            audio.onerror = () => {
                console.error("Audio playback error on chunk", currentIdx);
                setPlayingState(false);
            };
            audio.play().catch(e => {
                console.error("Audio play blocked", e);
                setPlayingState(false);
            });
        };
        
        playNext();
    } catch (e) {
        console.error("Audio fallback failed", e);
        setPlayingState(false);
    }
  };

  // Custom Markdown renderer for highlighted list items
  const MarkdownComponents = {
    li: ({ node, children, ...props }) => {
      // Extract rough text to sniff for keywords
      let plainText = '';
      React.Children.forEach(children, child => {
        if (typeof child === 'string') plainText += child;
        else if (child?.props?.children && typeof child.props.children === 'string') plainText += child.props.children;
        else if (child?.props?.children && Array.isArray(child.props.children)) {
           child.props.children.forEach(c => { if (typeof c === 'string') plainText += c; });
        }
      });
      
      const lowerText = plainText.toLowerCase().trim();
      
      if (lowerText.startsWith('dosage:')) {
        return (
          <li className="dosage-row" {...props}>
             <span className="alert-badge">DOSAGE</span>
             <span>{children}</span>
          </li>
        );
      }
      
      if (lowerText.startsWith('precautions:') || lowerText.startsWith('warning:')) {
        return (
          <li className="warning-row" {...props}>
             <span className="alert-badge">WARNING</span>
             <span>{children}</span>
          </li>
        );
      }
      
      return <li {...props}>{children}</li>;
    }
  };

  const baseContent = originalContent || content;
  const activeContent = translatedText || baseContent;
  const contentText = typeof activeContent === 'string' ? activeContent : JSON.stringify(activeContent, null, 2);

  return (
    <div className={`message-bubble-wrapper ${isAssistant ? 'assistant' : 'user'} animate-fade-up`}>
      <div className={`message-bubble ${isAssistant ? 'glass-panel' : 'user-panel'}`} style={{ display: 'flex', flexDirection: 'column' }}>
        
        {images && images.map((img, i) => (
          <img key={i} src={img} alt="Uploaded preview" className="message-image" style={{ marginBottom: '12px', borderRadius: '8px' }}/>
        ))}

        <div className="message-content-core">
          <ErrorBoundary rawText={contentText}>
            {isAssistant ? (
               <div className="markdown-body">
                  <ReactMarkdown components={MarkdownComponents}>{contentText}</ReactMarkdown>
               </div>
            ) : (
               <div className="markdown-body">
                  <ReactMarkdown>{contentText}</ReactMarkdown>
               </div>
            )}
          </ErrorBoundary>
        </div>

        {isAssistant && (
          <div className="message-actions-footer" style={{ 
              marginTop: '1.2rem', paddingTop: '0.8rem', borderTop: '1px solid rgba(255, 255, 255, 0.08)',
              display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '0.8rem'
          }}>
             
             <button onClick={handleSpeak} style={{ background: 'transparent', border: 'none', color: isPlaying ? '#00e676' : '#94a3b8', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px', padding: '4px' }}>
                {isPlaying ? <VolumeX size={15} /> : <Volume2 size={15} />}
                <span style={{ fontSize: '0.8rem', fontWeight: 500 }}>{isPlaying ? 'Stop audio' : 'Listen aloud'}</span>
             </button>

             <div style={{ width: '1px', height: '14px', background: 'rgba(255,255,255,0.1)' }}></div>
             
             <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                 <select 
                    value={targetLang} 
                    onChange={(e) => setTargetLang(e.target.value)}
                    style={{ background: '#121524', color: '#f1f5f9', border: '1px solid rgba(255,255,255,0.15)', borderRadius: '6px', padding: '4px 8px', fontSize: '0.8rem', cursor: 'pointer', outline: 'none' }}
                 >
                    <option value="en">English (Original)</option>
                    <option value="hi">Hindi (हिंदी)</option>
                    <option value="ta">Tamil (தமிழ்)</option>
                    <option value="te">Telugu (తెలుగు)</option>
                    <option value="bn">Bengali (বাংলা)</option>
                    <option value="mr">Marathi (मராठी)</option>
                 </select>

                 <button onClick={handleTranslate} disabled={isTranslating} style={{ background: 'rgba(0, 230, 118, 0.1)', border: 'none', color: '#00e676', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px', padding: '5px 12px', borderRadius: '20px' }}>
                    {isTranslating ? <Loader2 size={13} className="animate-spin" /> : <Languages size={13} />}
                    <span style={{ fontSize: '0.8rem', fontWeight: 600 }}>Translate</span>
                 </button>
             </div>

             {/* REVERT ACTION */}
             {(translatedText && (originalContent ? translatedText !== originalContent : true)) && (
                 <button 
                    onClick={() => {
                        setTranslatedText(null);
                        if (isPlaying) { window.speechSynthesis.cancel(); setIsPlaying(false); }
                    }} 
                    style={{ 
                        background: 'transparent', border: 'none', 
                        color: '#8e95b0', fontSize: '0.75rem', cursor: 'pointer', 
                        marginLeft: 'auto', textDecoration: 'underline' 
                    }}
                 >
                     View original
                 </button>
             )}

          </div>
        )}
      </div>
    </div>
  );
};

export default MessageBubble;
