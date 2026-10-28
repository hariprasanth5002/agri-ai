import React, { useState, useEffect } from 'react';
import { Sun, Cloud, CloudRain, ChevronDown, ChevronUp, MapPin, CloudLightning, CloudSnow } from 'lucide-react';
import './WeatherCard.css';

const WeatherCard = ({ data }) => {
  const { current, forecast } = data;
  const locationName = current?.location_name || data?.location?.city || 'Unknown Location';
  
  // Dynamic Icon Helper
  const getIconColor = (condition) => {
    const c = condition?.toLowerCase() || '';
    if (c.includes('rain')) return '#3b82f6';
    if (c.includes('sun') || c.includes('clear')) return '#ff9f00';
    return '#f1f1f1'; // Default white for clouds
  };

  const getIcon = (condition, size = 28) => {
    const c = condition?.toLowerCase() || '';
    
    if (c.includes('rain') || c.includes('shower')) return <CloudRain size={size} color="#3b82f6" fill={c.includes('heavy') ? "#3b82f6" : "none"} />;
    if (c.includes('snow')) return <CloudSnow size={size} color="#e0e0e0" />;
    if (c.includes('thunder')) return <CloudLightning size={size} color="#f59e0b" />;
    if (c.includes('cloud') || c.includes('overcast')) return <Cloud size={size} color="#f1f1f1" fill="#f1f1f1" />;
    
    // Default Sun
    return <Sun size={size} color="#ff9f00" fill="#ff9f00" />;
  };

  const forecastList = Array.isArray(forecast) ? forecast : (forecast?.forecast || []);
  const hourlyByDate = forecast?.hourly_by_date || {};

  // Parse Days neatly mapping directly from backend
  const daysParsed = forecastList.map((d) => {
    const dayDate = new Date(d.date);
    return {
      date: d.date,
      dayName: dayDate.toLocaleDateString('en-US', { weekday: 'short' }),
      condition: d.condition,
      max: Math.round(d.temp_max || 0),
      min: Math.round(d.temp_min || 0),
      rain_prob: d.rain_prob || 0
    };
  }).slice(0, 8); // Keep to 8 days to fit the UI neatly as in image

  // Default to today
  const [selectedDate, setSelectedDate] = useState(null);

  useEffect(() => {
    if (daysParsed.length > 0 && !selectedDate) {
      setSelectedDate(daysParsed[0].date);
    }
  }, [daysParsed, selectedDate]);

  const selectedDay = daysParsed.find(d => d.date === selectedDate) || daysParsed[0];
  const isToday = selectedDay?.date === daysParsed[0]?.date;
  
  const displayTemp = isToday ? Math.round(current?.temperature || 0) : selectedDay?.max;
  const displayCondition = isToday ? (current?.condition || 'Plenty of sun') : (selectedDay?.condition || 'Plenty of sun');

  // Derive Hourly Temperature for selected day
  const hourlyForDay = hourlyByDate[selectedDate] || [];
  let hourlyTimeline = [];
  
  if (hourlyForDay.length > 0) {
    // We have actual hourly chunk data from the backend for the selected day!
    hourlyTimeline = hourlyForDay.map(h => ({
      timeStr: h.time, 
      temp: Math.round(h.temperature || 0) 
    })).slice(0, 8);
  } else {
    // Fallback UI ribbon
    const dailyTemp = selectedDay ? selectedDay.max : 0;
    hourlyTimeline = [
      { timeStr: '3pm', temp: dailyTemp },
      { timeStr: '6pm', temp: dailyTemp },
      { timeStr: '9pm', temp: dailyTemp },
      { timeStr: '12am', temp: dailyTemp },
      { timeStr: '3am', temp: dailyTemp },
      { timeStr: '6am', temp: dailyTemp },
      { timeStr: '9am', temp: dailyTemp },
      { timeStr: '12pm', temp: dailyTemp },
    ];
  }

  return (
    <div className="weather-widget animate-fade-up">
      <div className="widget-location">
        {locationName}
      </div>

      <div className="widget-temp-row">
        <div className="widget-temp-big">
          {displayTemp}°
        </div>
        <div className="widget-temp-unit">
          <span className="unit-active">C</span> / <span>F</span>
        </div>
      </div>
      
      <div className="widget-condition">
        {displayCondition}
      </div>

      <div className="widget-days-scroll">
        {daysParsed.map((day) => (
          <div 
            key={day.date} 
            className={`widget-day-card ${selectedDate === day.date ? 'active' : ''}`}
            onClick={() => setSelectedDate(day.date)}
          >
            <span className="day-name-text">{day.dayName}</span>
            <div className="day-icon">{getIcon(day.condition)}</div>
            <span className="day-temp-max">{day.max}°</span>
            <span className="day-temp-min">{day.min}°</span>
          </div>
        ))}
      </div>

      <div className="precipitation-section">
        <div className="precip-header">
          Hourly Temperature <ChevronUp size={14} color="#a0a0a0" />
        </div>
        
        <div className="precip-timeline">
          {hourlyTimeline.map((item, idx) => (
            <div key={idx} className="precip-item">
              <span className="precip-pop">{item.temp}°</span>
              <span className="precip-time">{item.timeStr}</span>
            </div>
          ))}
          {hourlyTimeline.length === 0 && (
            <span style={{color: '#a0a0a0', fontSize: '0.9rem'}}>No hourly data</span>
          )}
        </div>
      </div>

      <div className="widget-bottom-action">
        <button className="circle-arrow-btn">
          <ChevronDown size={20} />
        </button>
      </div>
    </div>
  );
};

export default WeatherCard;
