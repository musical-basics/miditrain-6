import React from 'react';
import { VexFlowRenderer } from './dreamflow/VexFlowRenderer';

/**
 * Modernized NotationView using the DreamFlow MIDI Rendering Engine.
 * This component acts as a lightweight wrapper around the VexFlowRenderer,
 * providing the IntermediateScore data fetched from Phase 4B (notation map).
 */
export default function NotationView({
  notationData,
  darkMode = true,
  layoutMode = 'horizontal',
  onNoteHover,
  onNoteClick
}) {
  if (!notationData || !notationData.measures) {
    return (
      <div style={{ 
        display: 'flex', 
        alignItems: 'center', 
        justifyContent: 'center', 
        height: '100%', 
        color: darkMode ? '#666' : '#999',
        fontSize: '14px',
        fontFamily: 'Inter, sans-serif',
        background: darkMode ? '#0d0d12' : '#f8f9fa'
      }}>
        No notation data available. Please run the ETME Engine.
      </div>
    );
  }

  const isPaged = layoutMode === 'paged';

  return (
    <div 
      className="notation-view-root"
      style={{ 
        width: '100%', 
        height: '100%', 
        overflowX: isPaged ? 'hidden' : 'auto', 
        overflowY: isPaged ? 'auto' : 'hidden',
        background: darkMode ? '#0d0d12' : '#f8f9fa', 
        padding: '20px',
        display: 'flex',
        flexDirection: 'column',
        transition: 'background 0.3s ease'
      }} 
    >
      <div style={{ flex: 1, minWidth: isPaged ? '100%' : 'fit-content', display: 'flex', justifyContent: isPaged ? 'center' : 'flex-start' }}>
        <VexFlowRenderer
          score={notationData}
          musicFont="Bravura" 
          darkMode={darkMode} 
          paged={isPaged}
          onNoteHover={(id, e) => onNoteHover?.(id, e)}
          onNoteClick={(id, e) => onNoteClick?.(id, e)}
        />
      </div>
      
      <style jsx global>{`
        .notation-view-root::-webkit-scrollbar {
          width: 8px;
          height: 8px;
        }
        .notation-view-root::-webkit-scrollbar-track {
          background: ${darkMode ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)'};
        }
        .notation-view-root::-webkit-scrollbar-thumb {
          background: ${darkMode ? 'rgba(255, 255, 255, 0.2)' : 'rgba(0, 0, 0, 0.2)'};
          border-radius: 4px;
        }
        .notation-view-root::-webkit-scrollbar-thumb:hover {
          background: ${darkMode ? 'rgba(255, 255, 255, 0.3)' : 'rgba(0, 0, 0, 0.3)'};
        }
      `}</style>
    </div>
  );
}
