import React, { useEffect, useRef, useState } from 'react';
import { gsap } from 'gsap';
import './ParticleText.css';

const ParticleText = ({
  text,
  particleSize,
  density,
  color,
  highlightColor,
  scatter,
  gatherDuration,
  stagger,
  pointerRepel,
  repelRadius,
  idleDrift,
  trigger,
  fontSize,
  fontWeight,
  fontFamily,
  glow,
  className,
  style,
}: ParticleTextProps) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [buildId, setBuildId] = useState(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext('2d');
    if (!canvas || !context) return;

    const width  = canvas.width;
    const height = canvas.height;

    const baseRgb = color ? rgbToRgb(color) : null;
    const highlightRgb = highlightColor ? rgbToRgb(highlightColor) : null;

    const particles = Array.from({ length: density }, () => {
      const seed = Math.random();
      const depth = Math.random();
      const blend = baseRgb && highlightRgb
        ? clamp(target.x / Math.max(1, width) + (seed - 0.5) * 0.35, 0, 1)
        : 0;
      const particleColor = baseRgb && highlightRgb
        ? rgbToCss(mixRgb(baseRgb, highlightRgb, blend))
        : color;
      const angle    = seed * Math.PI * 2;
      const distance = (reducedMotion ? 0 : scatter) * (0.35 + depth * 0.75);
      const startX   = target.x + Math.cos(angle) * distance + (seed  - 0.5) * scatter * 0.45;
      const startY   = target.y + Math.sin(angle) * distance + (depth - 0.9) * scatter * 0.45;

      return {
        x: reducedMotion ? target.x : startX,
        y: reducedMotion ? target.y : startY,
        startX, startY,
        targetX: target.x, targetY: target.y,
        size:    Math.max(0.6, particleSize * (0.75 + target.alpha * 0.45)),
        color:   particleColor,
        seed, depth,
        delay:   seed * stagger,
      };
    });

    pointer.x = pointer.smoothX = width  / 2;
    pointer.y = pointer.smoothY = height / 2;

    if (reducedMotion) {
      particles.forEach(p => {
        p.x = p.targetX; p.y = p.targetY;
        p.startX = p.targetX; p.startY = p.targetY;
        p.delay = 0;
      });
      gathering = false;
    } else {
      startGather(false);
    }

    ensureRenderLoop();

    return () => {
      buildId++;
      ro.disconnect();
      mq?.removeEventListener('change', onMqChange);
      canvas.removeEventListener('pointerenter', handlePointerEnter);
      canvas.removeEventListener('pointermove',  handlePointerMove);
      canvas.removeEventListener('pointerleave', handlePointerLeave);
      canvas.removeEventListener('click',        handleClick);
      if (animationFrame !== null) window.cancelAnimationFrame(animationFrame);
      if (resizeFrame    !== null) window.cancelAnimationFrame(resizeFrame);
    };
  }, [text, particleSize, density, color, highlightColor, scatter, gatherDuration,
      stagger, pointerRepel, repelRadius, idleDrift, trigger, fontSize, fontWeight,
      fontFamily, glow]);

  return (
    <div ref={containerRef} className={`particle-text ${className}`} style={style} aria-label={text}>
      <canvas ref={canvasRef} className="particle-text__canvas" aria-hidden="true" />
      <span className="particle-text__sr">{text}</span>
    </div>
  );
};

export default ParticleText;
