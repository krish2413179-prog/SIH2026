import React, { useEffect, useRef } from 'react';
import './DynamicBackground.css';

export interface DynamicBackgroundProps {
  className?: string;
  style?: React.CSSProperties;
}

const DynamicBackground = ({ className, style }: DynamicBackgroundProps) => {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const layers = Array.from({ length: 3 }, (_, i) => (
      <div className="dynamic-background__layer" key={i} />
    ));

    container.innerHTML = '';
    container.appendChild(...layers);
  }, []);

  return (
    <div ref={containerRef} className={`dynamic-background ${className}`.trim()} style={style} />
  );
};

export default DynamicBackground;
