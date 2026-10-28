import React, { useState, useEffect, useRef, useCallback } from 'react';
import ChatWindow from './components/ChatWindow';
import ChatInput from './components/ChatInput';
import { Leaf, MapPin, MapPinOff, Loader } from 'lucide-react';
import './index.css';
import './App.css';

// ---------------------------------------------------------------------------
// Production API URL guard
// ---------------------------------------------------------------------------
const rawApiUrl = import.meta.env.VITE_API_BASE_URL;
if (!rawApiUrl && import.meta.env.PROD) {
  console.error(
    '[AgriAI] CRITICAL: VITE_API_BASE_URL is not set. ' +
    'Add it to Vercel Environment Variables → VITE_API_BASE_URL=https://<your-render-url>.onrender.com'
  );
}
const API_BASE_URL = (rawApiUrl || 'http://localhost:8001').replace(/\/+$/, '');

// ---------------------------------------------------------------------------
// Coordinate validation helpers
// ---------------------------------------------------------------------------
function isValidCoords(lat, lon) {
  return (
    typeof lat === 'number' &&
    typeof lon === 'number' &&
    isFinite(lat) &&
    isFinite(lon) &&
    lat >= -90 && lat <= 90 &&
    lon >= -180 && lon <= 180
  );
}

const GEO_TIMEOUT_MS = 8000;

/**
 * Attempt to get current position once. Resolves with {lat, lon} or null.
 * Never rejects — errors are swallowed and null is returned.
 */
function requestGeolocation() {
  return new Promise((resolve) => {
    if (!('geolocation' in navigator)) {
      resolve(null);
      return;
    }
    const timer = setTimeout(() => resolve(null), GEO_TIMEOUT_MS + 500);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        clearTimeout(timer);
        const lat = pos.coords.latitude;
        const lon = pos.coords.longitude;
        resolve(isValidCoords(lat, lon) ? { lat, lon } : null);
      },
      (err) => {
        clearTimeout(timer);
        resolve(null);
      },
      { timeout: GEO_TIMEOUT_MS, maximumAge: 120000, enableHighAccuracy: false }
    );
  });
}

// ---------------------------------------------------------------------------
// Translation helper
// ---------------------------------------------------------------------------
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

// ---------------------------------------------------------------------------
// App Component
// ---------------------------------------------------------------------------
function App() {
  const [messages, setMessages] = useState([]);
  const [isTyping, setIsTyping] = useState(false);

  // coords: { lat, lon } | null
  const [coords, setCoords] = useState(null);
  // locationStatus: 'pending' | 'granted' | 'denied' | 'unavailable' | 'unsupported'
  const [locationStatus, setLocationStatus] = useState('pending');

  // Keep a ref so handleSend can read the latest coords without stale closure
  const coordsRef = useRef(null);

  // Track whether we have already attempted geolocation once (avoid re-prompting)
  const geoAttempted = useRef(false);

  const LANG_NAMES = { hi: 'Hindi', ta: 'Tamil', te: 'Telugu', bn: 'Bengali', mr: 'Marathi' };

  // ── Initial geolocation attempt ────────────────────────────────────────────
  useEffect(() => {
    if (geoAttempted.current) return;
    geoAttempted.current = true;

    if (!('geolocation' in navigator)) {
      setLocationStatus('unsupported');
      return;
    }

    requestGeolocation().then((result) => {
      if (result) {
        setCoords(result);
        coordsRef.current = result;
        setLocationStatus('granted');
      } else {
        setLocationStatus('denied');
      }
    });
  }, []);

  // ── Append coords to FormData (validates before appending) ─────────────────
  const appendCoords = useCallback((formData, overrideCoords) => {
    const c = overrideCoords || coordsRef.current;
    if (c && isValidCoords(c.lat, c.lon)) {
      formData.append('lat', String(c.lat));
      formData.append('lon', String(c.lon));
    }
  }, []);

  // ── Main send handler ──────────────────────────────────────────────────────
  const handleSend = async (text, imageFile, originalText = null, voiceLang = null) => {
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

    // If we previously couldn't get coords, try once more before a text request
    // (user may have granted permission since). Only attempt if status is 'denied'
    // to avoid re-prompting on every message when the user already has coords.
    let currentCoords = coordsRef.current;
    if (!currentCoords && locationStatus === 'denied' && text && !imageFile) {
      const fresh = await requestGeolocation();
      if (fresh) {
        setCoords(fresh);
        coordsRef.current = fresh;
        setLocationStatus('granted');
        currentCoords = fresh;
      }
    }

    const backendText = text;
    const formData = new FormData();
    let endpoint = `${API_BASE_URL}/multimodal`;

    // Append validated coordinates
    appendCoords(formData, currentCoords);

    if (backendText && imageFile) {
      formData.append('text', backendText);
      formData.append('image', imageFile);
      endpoint = `${API_BASE_URL}/multimodal`;
    } else if (imageFile) {
      formData.append('file', imageFile);
      endpoint = `${API_BASE_URL}/image`;
    } else if (backendText) {
      formData.append('text', backendText);
      endpoint = `${API_BASE_URL}/text`;
    }

    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        body: formData
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();

      const englishResponse = data.response || data.error;
      let responseText = englishResponse;

      if (isVoiceTranslated && responseText) {
        responseText = await autoTranslateResponse(responseText, voiceLang);
      }

      const assistantMsgBase = {
        role: 'assistant',
        content: responseText || "I'm sorry, no response generated.",
        originalContent: (isVoiceTranslated && responseText) ? englishResponse : null,
        voiceLang: isVoiceTranslated ? voiceLang : null
      };

      if (data.type === 'weather' && !data.error) {
        if (responseText) {
          setMessages((prev) => [...prev, { ...assistantMsgBase, type: 'text' }]);
        }
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', type: 'weather', data: data }
        ]);
      } else {
        setMessages((prev) => [...prev, { ...assistantMsgBase, type: 'text' }]);
      }

    } catch (error) {
      console.error('API Error:', error);
      const isNetworkError = error.message.includes('Failed to fetch') || error.message.includes('NetworkError');
      const hint = isNetworkError && !rawApiUrl
        ? ' (VITE_API_BASE_URL is not set — check Vercel environment variables)'
        : '';
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          type: 'text',
          content: `**Error:** Unable to connect to backend system. Details: ${error.message}${hint}`
        }
      ]);
    } finally {
      setIsTyping(false);
    }
  };

  // ── Location status badge ──────────────────────────────────────────────────
  const renderLocationBadge = () => {
    if (locationStatus === 'granted') return null; // no badge needed when OK
    const styles = {
      display: 'inline-flex',
      alignItems: 'center',
      gap: '5px',
      fontSize: '0.72rem',
      padding: '3px 10px',
      borderRadius: '20px',
      marginRight: '8px',
    };
    if (locationStatus === 'pending') {
      return (
        <span style={{ ...styles, background: 'rgba(255,193,7,0.12)', color: '#ffc107' }}>
          <Loader size={11} /> Locating…
        </span>
      );
    }
    if (locationStatus === 'denied' || locationStatus === 'unavailable') {
      return (
        <span
          title="Location unavailable — weather queries will use the city you mention, or may be limited."
          style={{ ...styles, background: 'rgba(255,82,82,0.10)', color: '#ff5252', cursor: 'default' }}
        >
          <MapPinOff size={11} /> Location off
        </span>
      );
    }
    if (locationStatus === 'unsupported') {
      return (
        <span style={{ ...styles, background: 'rgba(120,120,120,0.12)', color: '#888' }}>
          <MapPinOff size={11} /> GPS not supported
        </span>
      );
    }
    return null;
  };

  return (
    <div className="app-layout">
      <header className="app-header">
        <div className="brand-section">
          <div className="brand-title-group">
            <Leaf size={28} color="var(--accent-green)" />
            <h1 className="brand-title">Agri AI</h1>
          </div>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            {renderLocationBadge()}
            <p className="brand-subtitle">Advanced Multimodal Intelligence</p>
          </div>
        </div>
      </header>

      <ChatWindow messages={messages} isTyping={isTyping} />

      <div className="input-section">
        <ChatInput onSend={handleSend} isLoading={isTyping} />
      </div>

      <div className="watermark-logo">N</div>
    </div>
  );
}

export default App;
