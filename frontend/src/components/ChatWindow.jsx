import React, { useEffect, useRef, useState } from 'react';
import { Leaf } from 'lucide-react';
import MessageBubble from './MessageBubble';
import WeatherCard from './WeatherCard';

const LoadingBubble = () => {
  const [step, setStep] = useState(0);
  const loadingStates = [
    { emoji: '🤔', text: 'Thinking' },
    { emoji: '🔍', text: 'Analyzing' },
    { emoji: '🌱', text: 'Processing' }
  ];

  useEffect(() => {
    const interval = setInterval(() => {
      setStep((prev) => (prev + 1) % loadingStates.length);
    }, 1500); // Change text every 1.5s
    return () => clearInterval(interval);
  }, []);

  const current = loadingStates[step];

  return (
    <div className="message-bubble-wrapper assistant animate-fade-up">
      <div className="message-bubble glass-panel" style={{ padding: '1rem 1.5rem', display: 'flex', alignItems: 'center', gap: '8px', minWidth: '150px' }}>
        <span key={`emoji-${step}`} style={{ fontSize: '1.2rem', animation: 'typing-pulse 1.5s infinite ease-in-out' }}>
          {current.emoji}
        </span>
        <span key={`text-${step}`} style={{ fontSize: '0.95rem', color: '#94a3b8', fontWeight: 500, animation: 'fade-in-up 0.3s ease-out' }}>
          {current.text}
        </span>
        <div style={{ display: 'flex', gap: '4px', marginLeft: 'auto', marginTop: '6px' }}>
          <div style={{ width: '4px', height: '4px', backgroundColor: '#00e676', borderRadius: '50%', animation: 'typing-pulse 1s infinite' }}></div>
          <div style={{ width: '4px', height: '4px', backgroundColor: '#00e676', borderRadius: '50%', animation: 'typing-pulse 1s infinite 0.2s' }}></div>
          <div style={{ width: '4px', height: '4px', backgroundColor: '#00e676', borderRadius: '50%', animation: 'typing-pulse 1s infinite 0.4s' }}></div>
        </div>
      </div>
    </div>
  );
};

const ChatWindow = ({ messages, isTyping }) => {
  const bottomRef = useRef(null);

  // Auto-scroll to bottom
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  return (
    <div className="chat-window">
      {messages.length === 0 && (
        <div style={{ margin: 'auto', textAlign: 'center', opacity: 0.9, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '1.2rem', transform: 'translateY(-20px)' }}>
          <div style={{ 
            background: 'rgba(0, 230, 118, 0.05)', 
            padding: '1.2rem', 
            borderRadius: '50%',
            boxShadow: '0 0 30px rgba(0, 230, 118, 0.15), inset 0 0 20px rgba(0, 230, 118, 0.05)',
            border: '1px solid rgba(0, 230, 118, 0.2)'
          }}>
            <Leaf size={42} color="#00e676" style={{ filter: 'drop-shadow(0 0 12px rgba(0,230,118,0.6))' }} />
          </div>
          <div>
            <h3 style={{ fontSize: '1.3rem', fontWeight: 600, color: '#f8fafc', marginBottom: '0.4rem', letterSpacing: '0.5px' }}>Welcome to Agri AI</h3>
            <p style={{ fontSize: '0.9rem', color: '#64748b' }}>Describe your crop issue, upload an image, or ask for the weather.</p>
          </div>
        </div>
      )}

      {messages.map((msg, idx) => {
        // Render special Weather Card
        if (msg.type === 'weather' && msg.role === 'assistant') {
          return <WeatherCard key={idx} data={msg.data} />;
        }
        
        // Default Message Bubble
        return (
          <MessageBubble 
            key={idx} 
            role={msg.role} 
            content={msg.content} 
            images={msg.images} 
            originalContent={msg.originalContent}
            voiceLang={msg.voiceLang}
          />
        );
      })}

      {isTyping && <LoadingBubble />}

      <div ref={bottomRef} />
    </div>
  );
};

export default ChatWindow;
