import React, { useRef, useState } from 'react';
import { Send, Image as ImageIcon } from 'lucide-react';
import VoiceRecorder from './VoiceRecorder';
import ImagePreview from './ImagePreview';

const LANG_LABELS = { hi: 'Hindi', ta: 'Tamil', te: 'Telugu', bn: 'Bengali', mr: 'Marathi' };

const ChatInput = ({ onSend, isLoading }) => {
  const [text, setText] = useState('');
  const [imageFile, setImageFile] = useState(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const fileInputRef = useRef(null);

  // Voice translation state — stores the English translation of voice input
  const [voiceTranslation, setVoiceTranslation] = useState(null);
  // voiceTranslation = { original: "தக்காளி நோய்", translated: "tomato disease", lang: "ta" }

  const handleSend = (e) => {
    e.preventDefault();
    if (!text.trim() && !imageFile) return;

    // If we have a voice translation pending, send the English version to backend
    // but pass the original language text for display in the chat bubble
    if (voiceTranslation && text === voiceTranslation.original) {
      onSend(voiceTranslation.translated, imageFile, voiceTranslation.original, voiceTranslation.lang);
    } else {
      // Normal typed text — no translation needed
      onSend(text, imageFile, null, null);
    }

    // Reset everything
    setText('');
    setImageFile(null);
    setVoiceTranslation(null);
    setFileInputKey(prev => prev + 1);
  };

  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (file) {
      setImageFile(file);
    }
  };

  const removeImage = () => {
    setImageFile(null);
    setFileInputKey(prev => prev + 1);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend(e);
    }
  };

  const handleVoiceTranscription = (result) => {
    // result = { original, translated, lang }
    const isTranslated = result.lang !== 'en' && result.original !== result.translated;
    
    // Show the original language text in the input field
    setText(prev => prev ? `${prev} ${result.original}` : result.original);

    if (isTranslated) {
      // Store the translation mapping so handleSend can use it
      setVoiceTranslation({
        original: result.original,
        translated: result.translated,
        lang: result.lang,
      });
    } else {
      setVoiceTranslation(null);
    }
  };

  return (
    <div className="input-container animate-fade-up">
      <form className={`chat-input-form ${imageFile ? 'has-attachment' : ''}`} onSubmit={handleSend}>
        
        {imageFile && (
          <div className="input-attachments">
            <ImagePreview imageFile={imageFile} onRemove={removeImage} />
          </div>
        )}

        {/* Voice translation indicator */}
        {voiceTranslation && (
          <div style={{
            padding: '4px 12px',
            background: 'rgba(0, 230, 118, 0.08)',
            borderRadius: '6px 6px 0 0',
            fontSize: '0.72rem',
            color: '#00e676',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
          }}>
            🌐 Voice in {LANG_LABELS[voiceTranslation.lang] || voiceTranslation.lang} → translated to English for AI
            <button
              type="button"
              onClick={() => { setVoiceTranslation(null); setText(''); }}
              style={{ background: 'none', border: 'none', color: '#8e95b0', cursor: 'pointer', fontSize: '0.7rem', marginLeft: 'auto' }}
            >✕ Clear</button>
          </div>
        )}

        <div className="input-controls">
          <button 
            type="button" 
            className="icon-btn image-icon" 
            onClick={() => fileInputRef.current?.click()}
            title="Upload Image"
          >
            <ImageIcon size={20} />
          </button>
          
          <input 
            key={fileInputKey}
            type="file" 
            accept="image/*" 
            ref={fileInputRef} 
            onChange={handleFileChange} 
            style={{ display: 'none' }} 
          />

          <textarea
            className="text-input"
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              // If user manually edits the text, clear voice translation
              if (voiceTranslation) setVoiceTranslation(null);
            }}
            onKeyDown={handleKeyDown}
            placeholder="Ask about crop diseases, fertilizers, or weather..."
            rows={1}
            disabled={isLoading}
          />

          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <VoiceRecorder 
              onTranscription={handleVoiceTranscription} 
            />

            <button 
              type="submit" 
              className={`send-btn ${(!text.trim() && !imageFile) || isLoading ? 'disabled' : ''}`}
              disabled={(!text.trim() && !imageFile) || isLoading}
            >
              <Send size={16} />
            </button>
          </div>
        </div>
      </form>
    </div>
  );
};

export default ChatInput;
