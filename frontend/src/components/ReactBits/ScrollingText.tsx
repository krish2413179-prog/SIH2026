import React, { useEffect, useRef } from 'react';
import './ScrollingText.css';

export interface ScrollingTextProps {
  text: string;
  className?: string;
  style?: React.CSSProperties;
}

const ScrollingText = ({ text, className, style }: ScrollingTextProps) => {
  const containerRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    container.textContent = text;
  }, [text]);

  return (
    <span ref={containerRef} className={`scrolling-text ${className}`.trim()} style={style} />
  );
};

export default ScrollingText;
