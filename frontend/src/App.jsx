import React, { useState, useEffect } from 'react';
import ChatWindow from './components/ChatWindow';
import ChatInput from './components/ChatInput';
import { Leaf } from 'lucide-react';
import './index.css';
import './App.css';

/**
 * Translate text to a target language using Google Translate free GTx API.
 * Splits by newlines to preserve formatting and stay within URI limits.
 * Returns translated text, or original if translation fails.
 */
async function autoTranslateResponse(text, targetLang) {
  if (!text || !targetLang || targetLang === 'en') return text;
  try {
    const lines = text.split('\n');
    const translated = [];
    for (const line of lines) {
      if (!line.trim()) { translated.push(''); continue; }
      const url = `https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=${targetLang}&dt=t&q=${encodeURIComponent(line)}`;
      const res = await fetch(url);
      const data = await res.json();
      if (data && data[0]) {
        translated.push(data[0].map(x => x[0]).join(''));
      } else {
        translated.push(line);
      }
    }
    return translated.join('\n');
  } catch (e) {
    console.error('Auto-translate response failed:', e);
    return text;
  }
}

function App() {
  const [messages, setMessages] = useState([]);
  const [isTyping, setIsTyping] = useState(false);
  const [coords, setCoords] = useState(null);

  useEffect(() => {
    if ("geolocation" in navigator) {
      navigator.geolocation.getCurrentPosition(
        (position) => setCoords({ lat: position.coords.latitude, lon: position.coords.longitude }),
        (error) => console.log("Geolocation error:", error)
      );
    }
  }, []);

  const LANG_NAMES = { hi: 'Hindi', ta: 'Tamil', te: 'Telugu', bn: 'Bengali', mr: 'Marathi' };

  const handleSend = async (text, imageFile, originalText = null, voiceLang = null) => {
    // 1. Add User Message — show ORIGINAL language in the chat bubble
    const displayText = originalText || text || '';
    const isVoiceTranslated = originalText && voiceLang && voiceLang !== 'en';

    const userMsg = {
      role: 'user',
      content: isVoiceTranslated
        ? `🎙️ *${LANG_NAMES[voiceLang] || voiceLang}:* ${displayText}`
        : displayText,
      images: imageFile ? [URL.createObjectURL(imageFile)] : []
    };
    
    setMessages((prev) => [...prev, userMsg]);
    setIsTyping(true);

    // 2. Prepare FormData — always send ENGLISH text to backend
    const backendText = text;
    const formData = new FormData();
    const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8001";
    let endpoint = `${API_BASE_URL}/multimodal`;

    if (coords) {
      formData.append("lat", coords.lat);
      formData.append("lon", coords.lon);
    }

    if (backendText && imageFile) {
      formData.append("text", backendText);
      formData.append("image", imageFile);
      endpoint = `${API_BASE_URL}/multimodal`;
    } else if (imageFile) {
      formData.append("file", imageFile);
      endpoint = `${API_BASE_URL}/image`;
    } else if (backendText) {
      formData.append("text", backendText);
      endpoint = `${API_BASE_URL}/text`;
    }

    // 3. API Call
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        body: formData
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();

      // 4. Handle Server Response (including early exit errors)
      const englishResponse = data.response || data.error;
      let responseText = englishResponse;

      // 5. Auto-translate response to farmer's language if voice was non-English
      if (isVoiceTranslated && responseText) {
        const translatedResponse = await autoTranslateResponse(responseText, voiceLang);
        responseText = translatedResponse;
      }
      
      const assistantMsgBase = { 
        role: 'assistant', 
        content: responseText || "I'm sorry, no response generated.",
        originalContent: (isVoiceTranslated && responseText) ? englishResponse : null,
        voiceLang: isVoiceTranslated ? voiceLang : null
      };

      if (data.type === 'weather' && !data.error) {
        if (responseText) {
          setMessages((prev) => [
            ...prev,
            { ...assistantMsgBase, type: 'text' }
          ]);
        }
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', type: 'weather', data: data }
        ]);
        
      } else {
        setMessages((prev) => [
            ...prev,
            { ...assistantMsgBase, type: 'text' }
        ]);
      }

    } catch (error) {
      console.error("API Error:", error);
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', type: 'text', content: `**Error:** Unable to connect to backend system. Details: ${error.message}` }
      ]);
    } finally {
      setIsTyping(false);
    }
  };

  return (
    <div className="app-layout">
      {/* Exact Header matching image */}
      <header className="app-header">
        <div className="brand-section">
          <div className="brand-title-group">
            <Leaf size={28} color="var(--accent-green)" />
            <h1 className="brand-title">Agri AI</h1>
          </div>
          <p className="brand-subtitle">Advanced Multimodal Intelligence</p>
        </div>
      </header>

      {/* Dynamic Chat Window */}
      <ChatWindow messages={messages} isTyping={isTyping} />

      {/* Input Bar exactly matching image */}
      <div className="input-section">
        <ChatInput onSend={handleSend} isLoading={isTyping} />
      </div>

      <div className="watermark-logo">N</div>
    </div>
  );
}

export default App;
