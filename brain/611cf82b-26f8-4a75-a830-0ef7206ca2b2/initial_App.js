import React, { useState, useEffect, useRef, useMemo } from 'react';
import axios from 'axios';
import { 
  Download, FileVideo, Trash2, 
  Globe, Sliders, Sparkles, RotateCcw, UploadCloud, Type
} from 'lucide-react';
import './App.css';

// Hex to RGB converter helper for transparency
const hexToRgb = (hex) => {
  const bigint = parseInt(hex.replace('#', ''), 16);
  if (isNaN(bigint)) return "0, 0, 0";
  const r = (bigint >> 16) & 255;
  const g = (bigint >> 8) & 255;
  const b = bigint & 255;
  return `${r}, ${g}, ${b}`;
};

function App() {
  // App Workflow States
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [videoId, setVideoId] = useState(null);
  const [videoData, setVideoData] = useState(null); // Metadata from backend
  const [segments, setSegments] = useState([]);
  
  // Player Sync State
  const [currentTime, setCurrentTime] = useState(0);
  const videoRef = useRef(null);

  // Transcription Language
  const [language, setLanguage] = useState('auto');
  
  // Custom Styles state
  const [fontColor, setFontColor] = useState("#ffff00");
  const [borderColor, setBorderColor] = useState("#000000");
  const [fontSize, setFontSize] = useState(24);
  const [borderWidth, setBorderWidth] = useState(1.5);
  const [fontFamily, setFontFamily] = useState("Inter");
  const [bgColor, setBgColor] = useState("#000000");
  const [bgOpacity, setBgOpacity] = useState(0.0);
  const [bold, setBold] = useState(true);
  const [italic, setItalic] = useState(false);
  const [showSpeakerLabels, setShowSpeakerLabels] = useState(false);
  
  // Presets State
  const [presets, setPresets] = useState([]);
  const [newPresetName, setNewPresetName] = useState("");
  const [selectedPresetId, setSelectedPresetId] = useState("");
  
  // Render / Burn state
  const [rendering, setRendering] = useState(false);
  const [renderedVideoUrl, setRenderedVideoUrl] = useState("");
  
  // Fetch Presets on Mount
  useEffect(() => {
    fetchPresets();
  }, []);

  const fetchPresets = async () => {
    try {
      const res = await axios.get('http://localhost:5000/api/presets');
      setPresets(res.data);
    } catch (err) {
      console.error("Failed to load presets", err);
    }
  };

  const applyPreset = (preset) => {
    setFontColor(preset.font_color);
    setBorderColor(preset.border_color);
    setFontSize(preset.font_size);
    setBorderWidth(preset.border_width);
    setFontFamily(preset.font_family);
    setBgColor(preset.bg_color);
    setBgOpacity(preset.bg_opacity);
    setBold(preset.bold);
    setItalic(preset.italic);
    setSelectedPresetId(preset.id);
  };

  const saveCustomPreset = async () => {
    if (!newPresetName.trim()) return alert("Enter preset name!");
    try {
      await axios.post('http://localhost:5000/api/presets', {
        name: newPresetName.trim(),
        font_color: fontColor,
        border_color: borderColor,
        font_size: fontSize,
        border_width: borderWidth,
        font_family: fontFamily,
        bg_color: bgColor,
        bg_opacity: bgOpacity,
        bold: bold,
        italic: italic
      });
      setNewPresetName("");
      fetchPresets();
      alert("Preset saved!");
    } catch (err) {
      alert("Failed to save preset");
    }
  };

  const deletePreset = async (id, e) => {
    e.stopPropagation();
    try {
      await axios.delete(`http://localhost:5000/api/presets/${id}`);
      fetchPresets();
    } catch (err) {
      alert("Failed to delete preset");
    }
  };

  // Upload Handlers
  const handleUpload = async () => {
    if (!file) return alert("Please select a video!");
    setUploading(true);
    setRenderedVideoUrl("");
    
    const formData = new FormData();
    formData.append('video', file);
    formData.append('language', language);
    
    try {
      const res = await axios.post('http://localhost:5000/api/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      setVideoId(res.data.videoId);
      setUploading(false);
      setTranscribing(true);
      startPollingStatus(res.data.videoId);
    } catch (err) {
      alert("Upload failed. Make sure backend is running on http://localhost:5000.");
      setUploading(false);
    }
  };

  const startPollingStatus = (id) => {
    const timer = setInterval(async () => {
      try {
        const res = await axios.get(`http://localhost:5000/api/videos/${id}`);
        setVideoData(res.data);
        if (res.data.status === 'completed') {
          clearInterval(timer);
          setTranscribing(false);
          fetchSegments(id);
        } else if (res.data.status === 'error') {
          clearInterval(timer);
          setTranscribing(false);
          alert("Whisper AI error: " + res.data.error_message);
        }
      } catch (err) {
        clearInterval(timer);
        setTranscribing(false);
        alert("Error reading video status.");
      }
    }, 2000);
  };

  const fetchSegments = async (id) => {
    try {
      const res = await axios.get(`http://localhost:5000/api/videos/${id}/segments`);
      setSegments(res.data.segments);
    } catch (err) {
      alert("Failed to load transcribed segments");
    }
  };

  // Subtitle Overlay TextShadow outline generation
  const textOutlineShadow = useMemo(() => {
    if (borderWidth === 0) return 'none';
    return `
      -${borderWidth}px -${borderWidth}px 0 ${borderColor},
       ${borderWidth}px -${borderWidth}px 0 ${borderColor},
      -${borderWidth}px  ${borderWidth}px 0 ${borderColor},
       ${borderWidth}px  ${borderWidth}px 0 ${borderColor},
       0px -${borderWidth}px 0 ${borderColor},
       0px  ${borderWidth}px 0 ${borderColor},
      -${borderWidth}px  0px 0 ${borderColor},
       ${borderWidth}px  0px 0 ${borderColor}
    `;
  }, [borderWidth, borderColor]);

  // Find active segment in player time
  const activeSegment = useMemo(() => {
    return segments.find(s => currentTime >= s.start_time && currentTime <= s.end_time);
  }, [segments, currentTime]);

  // Actions
  const handleExport = async (format) => {
    try {
      const res = await axios.post(`http://localhost:5000/api/videos/${videoId}/export`, {
        format,
        showSpeakerLabels
      });
      window.open(res.data.downloadUrl);
    } catch (err) {
      alert("Failed to export subtitles");
    }
  };

  const startPollingRenderStatus = (id) => {
    const timer = setInterval(async () => {
      try {
        const res = await axios.get(`http://localhost:5000/api/videos/${id}`);
        if (res.data.status === 'completed' && res.data.renderedUrl) {
          clearInterval(timer);
          setRenderedVideoUrl(res.data.renderedUrl);
          setRendering(false);
          alert("Video rendered successfully!");
        } else if (res.data.status === 'error') {
          clearInterval(timer);
          setRendering(false);
          alert("FFmpeg render failed:\n" + res.data.error_message);
        }
      } catch (err) {
        clearInterval(timer);
        setRendering(false);
        alert("Error polling render status.");
      }
    }, 2000);
  };

  const handleBurnVideo = async () => {
    setRendering(true);
    setRenderedVideoUrl("");
    try {
      const res = await axios.post(`http://localhost:5000/api/videos/${videoId}/burn`, {
        fontColor,
        borderColor,
        fontSize,
        borderWidth,
        fontFamily,
        bgColor,
        bgOpacity,
        bold,
        italic,
        showSpeakerLabels
      });
      if (res.data.status === 'rendering') {
        startPollingRenderStatus(videoId);
      }
    } catch (err) {
      alert("FFmpeg render failed to start. Make sure backend is running.");
      setRendering(false);
    }
  };

  const resetAll = () => {
    setFile(null);
    setVideoId(null);
    setVideoData(null);
    setSegments([]);
    setRenderedVideoUrl("");
  };

  return (
    <div className="app-container">
      {/* Navigation Header */}
      <header className="navbar">
        <div className="nav-container">
          <div className="logo">
            ≡ƒÄ¼ <span>AI SMART CAPTIONER</span>
          </div>
          {videoData && (
            <div className="nav-actions">
              <button className="btn-outline" onClick={resetAll}>
                <RotateCcw size={16} /> Start Over
              </button>
            </div>
          )}
        </div>
      </header>

      {/* Main Container */}
      {!videoData ? (
        // UPLOAD & INIT SCREEN
        <main className="hero-section">
          <div className="glass-card upload-container">
            <div className="badge">Week 1 Tier 1 Powered</div>
            <h2>Create Styled Captions in Seconds</h2>
            <p>Upload your English/Hindi video and let AI handle transcription. Edit and style captions in real-time.</p>

            <div className="settings-row">
              <div className="setting-control">
                <label><Globe size={14} /> AI Model Language</label>
                <select value={language} onChange={(e) => setLanguage(e.target.value)}>
                  <option value="auto">≡ƒîì Auto-Detect Language</option>
                  <option value="en">English (EN)</option>
                  <option value="hi">Hindi (HI)</option>
                  <option value="es">Spanish (ES)</option>
                  <option value="fr">French (FR)</option>
                </select>
              </div>
            </div>

            <div className="upload-box">
              <input 
                type="file" 
                id="video-file" 
                accept="video/*" 
                onChange={(e) => setFile(e.target.files[0])} 
                hidden 
              />
              <label htmlFor="video-file" className="dropzone">
                <UploadCloud size={40} className="upload-icon" />
                <span>{file ? `Γ£à ${file.name}` : "Click to select MP4/MKV video"}</span>
                <p>Support up to 100MB videos</p>
              </label>
            </div>

            {file && !uploading && !transcribing && (
              <button onClick={handleUpload} className="btn-primary start-btn">
                <Sparkles size={18} /> Transcribe Video
              </button>
            )}

            {/* Uploading progress states */}
            {uploading && (
              <div className="loading-state">
                <div className="pulse-loader"></div>
                <p>Uploading raw video to server...</p>
              </div>
            )}

            {transcribing && (
              <div className="loading-state">
                <div className="pulse-loader border-orange"></div>
                <p>AI Transcribing via Whisper... (May take a moment)</p>
                <div className="info-badge">Do not refresh this page.</div>
              </div>
            )}
          </div>
        </main>
      ) : (
        // INTERACTIVE WORKSPACE
        <main className="workspace">
          {/* COLUMN 1: STYLE SIDEBAR */}
          <aside className="editor-sidebar">
            <div className="sidebar-section">
              <h3><Sliders size={18} /> Style Presets</h3>
              <div className="preset-grid">
                {presets.map(p => {
                  const previewShadow = p.border_width > 0 ? `
                    -${p.border_width}px -${p.border_width}px 0 ${p.border_color},
                     ${p.border_width}px -${p.border_width}px 0 ${p.border_color},
                    -${p.border_width}px  ${p.border_width}px 0 ${p.border_color},
                     ${p.border_width}px  ${p.border_width}px 0 ${p.border_color}
                  ` : 'none';
                  return (
                    <button 
                      key={p.id} 
                      className={`preset-btn ${selectedPresetId === p.id ? 'active' : ''}`}
                      onClick={() => applyPreset(p)}
                    >
                      <div className="preset-info">
                        <span className="preset-name">{p.name}</span>
                        {p.id > 4 && (
                          <Trash2 size={12} className="trash-icon" onClick={(e) => deletePreset(p.id, e)} />
                        )}
                      </div>
                      <div className="preset-preview-wrap">
                        <span style={{
                          fontFamily: p.font_family,
                          color: p.font_color,
                          fontWeight: p.bold ? 'bold' : 'normal',
                          fontStyle: p.italic ? 'italic' : 'normal',
                          textShadow: previewShadow,
                          backgroundColor: p.bg_opacity > 0 ? `rgba(${hexToRgb(p.bg_color)}, ${p.bg_opacity})` : 'transparent',
                          padding: '2px 6px',
                          borderRadius: '3px',
                          fontSize: '13px',
                          lineHeight: 1,
                          display: 'inline-block'
                        }}>
                          Aa
                        </span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="sidebar-section border-top">
              <h3><Type size={18} /> Typography & Outline</h3>
              
              <div className="control-group">
                <label>Font Family</label>
                <select value={fontFamily} onChange={(e) => setFontFamily(e.target.value)}>
                  <option value="Arial">Arial</option>
                  <option value="Arial Black">Arial Black</option>
                  <option value="Calibri">Calibri</option>
                  <option value="Cambria">Cambria</option>
                  <option value="Candara">Candara</option>
                  <option value="Comic Sans MS">Comic Sans MS</option>
                  <option value="Consolas">Consolas</option>
                  <option value="Constantia">Constantia</option>
                  <option value="Corbel">Corbel</option>
                  <option value="Courier New">Courier New</option>
                  <option value="Georgia">Georgia</option>
                  <option value="Impact">Impact</option>
                  <option value="Lucida Console">Lucida Console</option>
                  <option value="Lucida Sans Unicode">Lucida Sans Unicode</option>
                  <option value="Microsoft Sans Serif">Microsoft Sans Serif</option>
                  <option value="Palatino Linotype">Palatino Linotype</option>
                  <option value="Segoe UI">Segoe UI</option>
                  <option value="Tahoma">Tahoma</option>
                  <option value="Times New Roman">Times New Roman</option>
                  <option value="Trebuchet MS">Trebuchet MS</option>
                  <option value="Verdana">Verdana</option>
                  <option value="Bebas Neue">Bebas Neue</option>
                  <option value="Inter">Inter</option>
                </select>
              </div>

              <div className="control-row-grid">
                <div className="control-group">
                  <label>Font Size ({fontSize}px)</label>
                  <input 
                    type="range" 
                    min="14" 
                    max="50" 
                    value={fontSize} 
                    onChange={(e) => setFontSize(parseInt(e.target.value))} 
                  />
                </div>
                <div className="control-group">
                  <label>Outline Width</label>
                  <input 
                    type="range" 
                    min="0" 
                    max="5" 
                    step="0.5" 
                    value={borderWidth} 
                    onChange={(e) => setBorderWidth(parseFloat(e.target.value))} 
                  />
                </div>
              </div>

              <div className="color-row-grid">
                <div className="control-group">
                  <label>Font Color</label>
                  <div className="color-picker-wrapper">
                    <input type="color" value={fontColor} onChange={(e) => setFontColor(e.target.value)} />
                    <span className="hex-label">{fontColor}</span>
                  </div>
                </div>
                <div className="control-group">
                  <label>Outline Color</label>
                  <div className="color-picker-wrapper">
                    <input type="color" value={borderColor} onChange={(e) => setBorderColor(e.target.value)} />
                    <span className="hex-label">{borderColor}</span>
                  </div>
                </div>
              </div>

              <div className="control-row-grid inline-options">
                <label className="checkbox-label">
                  <input type="checkbox" checked={bold} onChange={(e) => setBold(e.target.checked)} />
                  <span>Bold</span>
                </label>
                <label className="checkbox-label">
                  <input type="checkbox" checked={italic} onChange={(e) => setItalic(e.target.checked)} />
                  <span>Italic</span>
                </label>
              </div>
            </div>

            <div className="sidebar-section border-top">
              <h3>≡ƒÄ¿ Background Backdrop</h3>
              <div className="color-row-grid">
                <div className="control-group">
                  <label>Backdrop Color</label>
                  <div className="color-picker-wrapper">
                    <input type="color" value={bgColor} onChange={(e) => setBgColor(e.target.value)} />
                    <span className="hex-label">{bgColor}</span>
                  </div>
                </div>
                <div className="control-group">
                  <label>Backdrop Opacity ({Math.round(bgOpacity * 100)}%)</label>
                  <input 
                    type="range" 
                    min="0" 
                    max="1" 
                    step="0.1" 
                    value={bgOpacity} 
                    onChange={(e) => setBgOpacity(parseFloat(e.target.value))} 
                  />
                </div>
              </div>
            </div>

            <div className="sidebar-section border-top">
              <h3>≡ƒÆ╛ Save Custom Style</h3>
              <div className="save-preset-row">
                <input 
                  type="text" 
                  placeholder="Style Name" 
                  value={newPresetName}
                  onChange={(e) => setNewPresetName(e.target.value)}
                />
                <button className="btn-secondary" onClick={saveCustomPreset}>Save</button>
              </div>
            </div>
          </aside>

          {/* COLUMN 2: PLAYBACK & RENDER */}
          <section className="playback-area">
            <div className="glass-card player-card">
              <div className="video-viewport">
                <video 
                  ref={videoRef}
                  src={videoData.videoUrl} 
                  controls 
                  onTimeUpdate={(e) => setCurrentTime(e.target.currentTime)}
                />
                {/* LIVE DYNAMIC SUBTITLE OVERLAY */}
                {activeSegment && (
                  <div 
                    className="subtitle-overlay"
                    style={{
                      position: 'absolute',
                      bottom: '10%',
                      left: '50%',
                      transform: 'translateX(-50%)',
                      textAlign: 'center',
                      pointerEvents: 'none',
                      fontFamily: fontFamily,
                      fontSize: `${fontSize}px`,
                      color: fontColor,
                      fontWeight: bold ? 'bold' : 'normal',
                      fontStyle: italic ? 'italic' : 'normal',
                      textShadow: textOutlineShadow,
                      backgroundColor: bgOpacity > 0 ? `rgba(${hexToRgb(bgColor)}, ${bgOpacity})` : 'transparent',
                      padding: bgOpacity > 0 ? '6px 14px' : '0',
                      borderRadius: '6px',
                      maxWidth: '85%',
                      whiteSpace: 'pre-wrap',
                      zIndex: 10,
                      transition: 'all 0.1s ease-out'
                    }}
                  >
                    {showSpeakerLabels ? `[${activeSegment.speaker}]: ${activeSegment.text}` : activeSegment.text}
                  </div>
                )}
              </div>
              
              <div className="render-controls border-top">
                <div className="render-options">
                  <label className="checkbox-label">
                    <input 
                      type="checkbox" 
                      checked={showSpeakerLabels} 
                      onChange={(e) => setShowSpeakerLabels(e.target.checked)} 
                    />
                    <span>Show speaker tags in final render/export</span>
                  </label>
                </div>
                <div className="btn-row">
                  <button className="btn-primary" onClick={handleBurnVideo} disabled={rendering}>
                    {rendering ? (
                      <>
                        <div className="mini-spinner"></div> Rendering Subtitles...
                      </>
                    ) : (
                      <>
                        <FileVideo size={16} /> Burn Styles & Render Video
                      </>
                    )}
                  </button>

                  <div className="export-dropdown">
                    <button className="btn-outline">
                      <Download size={16} /> Export Subtitles
                    </button>
                    <div className="dropdown-menu">
                      <button onClick={() => handleExport('srt')}>Export as SRT</button>
                      <button onClick={() => handleExport('vtt')}>Export as VTT</button>
                      <button onClick={() => handleExport('json')}>Export as JSON</button>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* rendered download block */}
            {renderedVideoUrl && (
              <div className="glass-card render-output-card animate-slideup">
                <h4>≡ƒÄë Your Rendered Video is Ready!</h4>
                <video src={renderedVideoUrl} controls width="100%" />
                <div className="btn-row mt-15">
                  <a href={renderedVideoUrl} download className="btn-success text-dec-none">
                    <Download size={16} /> Download Final MP4
                  </a>
                </div>
              </div>
            )}
          </section>
        </main>
      )}
    </div>
  );
}

export default App;
