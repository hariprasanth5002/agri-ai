import React, { useState, useRef, useCallback } from 'react';
import { Mic, Square, Globe } from 'lucide-react';

const VOICE_LANGUAGES = [
  { code: 'en-IN', label: 'English', short: 'en' },
  { code: 'hi-IN', label: 'हिंदी',   short: 'hi' },
  { code: 'ta-IN', label: 'தமிழ்',   short: 'ta' },
  { code: 'te-IN', label: 'తెలుగు',  short: 'te' },
  { code: 'bn-IN', label: 'বাংলা',   short: 'bn' },
  { code: 'mr-IN', label: 'मराठी',   short: 'mr' },
];

/**
 * Translate text to English using Google Translate free GTx API.
 * Returns the translated string, or the original if translation fails.
 */
async function translateToEnglish(text) {
  try {
    const url = `https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=en&dt=t&q=${encodeURIComponent(text)}`;
    const res = await fetch(url);
    const data = await res.json();
    if (data && data[0]) {
      return data[0].map(x => x[0]).join('');
    }
  } catch (e) {
    console.error('Voice translation failed:', e);
  }
  return text; // fallback to original
}

const VoiceRecorder = ({ onTranscription }) => {
  const [isRecording, setIsRecording] = useState(false);
  const [isTranslating, setIsTranslating] = useState(false);
  const [voiceLang, setVoiceLang] = useState('en-IN');
  const recognitionRef = useRef(null);

  const startRecognition = useCallback(() => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      alert("Speech recognition isn't supported in this browser.");
      return;
    }

    // Create a fresh instance each time so the language is always current
    const rec = new SpeechRecognition();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = voiceLang;

    rec.onresult = async (event) => {
      let finalTranscript = '';
      for (let i = event.resultIndex; i < event.results.length; ++i) {
        if (event.results[i].isFinal) {
          finalTranscript += event.results[i][0].transcript;
        }
      }
      if (finalTranscript) {
        rec.stop();
        setIsRecording(false);

        const shortLang = VOICE_LANGUAGES.find(l => l.code === voiceLang)?.short || 'en';
        const isEnglish = shortLang === 'en';

        if (isEnglish) {
          // English — no translation needed
          onTranscription({ original: finalTranscript, translated: finalTranscript, lang: shortLang });
        } else {
          // Non-English — auto-translate to English for the backend
          setIsTranslating(true);
          const englishText = await translateToEnglish(finalTranscript);
          setIsTranslating(false);
          onTranscription({ original: finalTranscript, translated: englishText, lang: shortLang });
        }
      }
    };

    rec.onerror = (event) => {
      console.error('Speech recognition error', event.error);
      setIsRecording(false);
    };

    rec.onend = () => {
      setIsRecording(false);
    };

    recognitionRef.current = rec;
    rec.start();
    setIsRecording(true);
  }, [voiceLang, onTranscription]);

  const toggleRecording = () => {
    if (isRecording && recognitionRef.current) {
      recognitionRef.current.stop();
      setIsRecording(false);
    } else {
      startRecognition();
    }
  };

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
      {/* Language selector — small dropdown next to mic */}
      <select
        value={voiceLang}
        onChange={(e) => setVoiceLang(e.target.value)}
        title="Voice input language"
        className="voice-lang-select"
        style={{
          background: '#121524',
          color: '#94a3b8',
          border: '1px solid rgba(255,255,255,0.12)',
          borderRadius: '8px',
          padding: '4px 6px',
          fontSize: '0.7rem',
          cursor: 'pointer',
          outline: 'none',
          width: '54px',
        }}
      >
        {VOICE_LANGUAGES.map(l => (
          <option key={l.code} value={l.code}>{l.label}</option>
        ))}
      </select>

      <button 
        type="button"
        className={`icon-btn circle-btn ${isRecording ? 'recording-active' : ''} ${isTranslating ? 'translating' : ''}`}
        onClick={(e) => { e.preventDefault(); toggleRecording(); }}
        title={isTranslating ? "Translating..." : isRecording ? "Stop recording" : "Record voice"}
        disabled={isTranslating}
      >
        {isTranslating ? (
          <Globe size={16} className="animate-spin" style={{ opacity: 0.7 }} />
        ) : isRecording ? (
          <Square size={16} />
        ) : (
          <Mic size={16} />
        )}
      </button>
    </div>
  );
};

export default VoiceRecorder;
