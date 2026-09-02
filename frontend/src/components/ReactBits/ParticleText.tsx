'use client';

import { useEffect, useRef } from 'react';
import './ParticleText.css';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const hexToRgb = (hex: string) => {
  const clean = hex.replace('#', '').trim();
  if (!/^[0-9a-fA-F]{6}$/.test(clean)) return null;
  return {
    r: parseInt(clean.slice(0, 2), 16),
    g: parseInt(clean.slice(2, 4), 16),
    b: parseInt(clean.slice(4, 6), 16),
  };
};

const mixRgb = (
  from: { r: number; g: number; b: number },
  to:   { r: number; g: number; b: number },
  amount: number,
) => ({
  r: Math.round(from.r + (to.r - from.r) * amount),
  g: Math.round(from.g + (to.g - from.g) * amount),
  b: Math.round(from.b + (to.b - from.b) * amount),
});

const rgbToCss = (rgb: { r: number; g: number; b: number }) =>
  `rgb(${rgb.r}, ${rgb.g}, ${rgb.b})`;

const clamp = (value: number, min: number, max: number) =>
  Math.min(Math.max(value, min), max);

const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3);

const resolveFontSize = (
  value: number | string,
  container: HTMLElement,
  fontWeight: number | string,
  fontFamily: string,
): number => {
  if (typeof value === 'number') return value;
  const probe = document.createElement('span');
  probe.textContent = 'M';
  probe.style.cssText = `position:absolute;visibility:hidden;pointer-events:none;font-size:${value};font-weight:${fontWeight};font-family:${fontFamily}`;
  container.appendChild(probe);
  const size = parseFloat(window.getComputedStyle(probe).fontSize) || 96;
  probe.remove();
  return size;
};

const waitForFonts = async (font: string) => {
  if (!('fonts' in document)) return;
  try { await (document as Document & { fonts: FontFaceSet }).fonts.load(font); } catch {}
  await (document as Document & { fonts: FontFaceSet }).fonts.ready;
};

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface ParticleTextProps {
  text?: string;
  particleSize?: number;
  density?: number;
  color?: string;
  highlightColor?: string;
  scatter?: number;
  gatherDuration?: number;
  stagger?: number;
  pointerRepel?: number;
  repelRadius?: number;
  idleDrift?: number;
  trigger?: 'mount' | 'hover' | 'click';
  fontSize?: number | string;
  fontWeight?: number | string;
  fontFamily?: string;
  glow?: boolean;
  className?: string;
  style?: React.CSSProperties;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const ParticleText = ({
  text           = 'React Bits',
  particleSize   = 2,
  density        = 4,
  color          = '#ffffff',
  highlightColor = '#8b5cf6',
  scatter        = 180,
  gatherDuration = 1600,
  stagger        = 420,
  pointerRepel   = 40,
  repelRadius    = 120,
  idleDrift      = 0.7,
  trigger        = 'mount',
  fontSize       = 'clamp(3rem, 12vw, 8rem)',
  fontWeight     = 800,
  fontFamily     = 'inherit',
  glow           = true,
  className      = '',
  style,
}: ParticleTextProps) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef    = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (typeof window === 'undefined') return;

    const container = containerRef.current;
    const canvas    = canvasRef.current;
    if (!container || !canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let particles:      any[]               = [];
    let animationFrame: number | null        = null;
    let resizeFrame:    number | null        = null;
    let buildId         = 0;
    let gathering       = false;
    let gatherStart     = 0;
    let reducedMotion   = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
    let width           = 0;
    let height          = 0;
    let dpr             = 1;

    const pointer = { active: false, x: 0, y: 0, smoothX: 0, smoothY: 0 };

    const startGather = (fromScatter = true) => {
      if (!particles.length) return;
      const now   = performance.now();
      const spread = reducedMotion ? 0 : scatter;
      particles.forEach(p => {
        if (fromScatter) {
          const angle    = p.seed * Math.PI * 2;
          const distance = spread * (0.35 + p.depth * 0.75);
          p.x = p.targetX + Math.cos(angle) * distance + (p.depth - 0.5) * spread * 0.55;
          p.y = p.targetY + Math.sin(angle) * distance + (p.seed  - 0.5) * spread * 0.55;
        }
        p.startX = p.x;
        p.startY = p.y;
        p.delay  = reducedMotion ? 0 : p.seed * stagger;
      });
      gatherStart = now;
      gathering   = true;
    };

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const drawParticle = (p: any) => {
      ctx.fillStyle = p.color;
      if (p.size <= 2.1) {
        ctx.fillRect(p.x - p.size / 2, p.y - p.size / 2, p.size, p.size);
        return;
      }
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.size / 2, 0, Math.PI * 2);
      ctx.fill();
    };

    const render = (now: number) => {
      ctx.clearRect(0, 0, width, height);

      if (glow && !reducedMotion) {
        ctx.shadowBlur  = particleSize * 3;
        ctx.shadowColor = highlightColor;
      } else {
        ctx.shadowBlur = 0;
      }

      pointer.smoothX += (pointer.x - pointer.smoothX) * 0.18;
      pointer.smoothY += (pointer.y - pointer.smoothY) * 0.18;

      let complete = true;

      particles.forEach(p => {
        let baseX    = p.targetX;
        let baseY    = p.targetY;
        let progress = 1;

        if (gathering) {
          const local = (now - gatherStart - p.delay) / Math.max(1, reducedMotion ? 1 : gatherDuration);
          progress = clamp(local, 0, 1);
          const eased = easeOutCubic(progress);
          baseX = p.startX + (p.targetX - p.startX) * eased;
          baseY = p.startY + (p.targetY - p.startY) * eased;
          if (progress < 1) complete = false;
        } else if (!reducedMotion && idleDrift > 0) {
          const t = now * 0.001;
          baseX += Math.sin(t * 0.9  + p.seed  * 10) * idleDrift * p.depth;
          baseY += Math.cos(t * 0.75 + p.depth * 10) * idleDrift * p.depth;
        }

        if (pointer.active && !reducedMotion && pointerRepel > 0 && repelRadius > 0) {
          const dx  = baseX - pointer.smoothX;
          const dy  = baseY - pointer.smoothY;
          const dist = Math.hypot(dx, dy);
          if (dist > 0 && dist < repelRadius) {
            const force = Math.pow(1 - dist / repelRadius, 2) * pointerRepel;
            baseX += (dx / dist) * force;
            baseY += (dy / dist) * force;
          }
        }

        const follow = reducedMotion ? 1 : 0.22;
        p.x += (baseX - p.x) * follow;
        p.y += (baseY - p.y) * follow;

        ctx.globalAlpha = clamp(0.35 + progress * 0.65, 0, 1);
        drawParticle(p);
      });

      ctx.globalAlpha = 1;
      ctx.shadowBlur  = 0;
      if (gathering && complete) gathering = false;
      animationFrame = window.requestAnimationFrame(render);
    };

    const ensureRenderLoop = () => {
      if (animationFrame === null)
        animationFrame = window.requestAnimationFrame(render);
    };

    const sampleText = async () => {
      const currentBuild = ++buildId;
      const rect = container.getBoundingClientRect();
      width  = Math.floor(rect.width);
      height = Math.floor(rect.height);
      if (width <= 0 || height <= 0) return;

      dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width  = Math.max(1, Math.floor(width  * dpr));
      canvas.height = Math.max(1, Math.floor(height * dpr));
      canvas.style.width  = '100%';
      canvas.style.height = '100%';
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      const computed        = window.getComputedStyle(container);
      const resolvedFamily  = fontFamily === 'inherit' ? computed.fontFamily || 'sans-serif' : fontFamily;
      let   resolvedSize    = resolveFontSize(fontSize, container, fontWeight, resolvedFamily);
      let   font            = `${fontWeight} ${resolvedSize}px ${resolvedFamily}`;

      await waitForFonts(font);
      if (currentBuild !== buildId) return;

      const offscreen = document.createElement('canvas');
      const offCtx    = offscreen.getContext('2d', { willReadFrequently: true });
      if (!offCtx) return;

      const content      = String(text || ' ');
      const maxTextWidth = width * 0.92;
      offCtx.font        = font;
      let metrics        = offCtx.measureText(content);

      if (metrics.width > maxTextWidth) {
        resolvedSize = Math.max(18, resolvedSize * (maxTextWidth / Math.max(1, metrics.width)));
        font         = `${fontWeight} ${resolvedSize}px ${resolvedFamily}`;
        await waitForFonts(font);
        if (currentBuild !== buildId) return;
        offCtx.font = font;
        metrics     = offCtx.measureText(content);
      }

      const left    = Math.ceil(metrics.actualBoundingBoxLeft    || 0);
      const right   = Math.ceil(metrics.actualBoundingBoxRight   || metrics.width);
      const ascent  = Math.ceil(metrics.actualBoundingBoxAscent  || resolvedSize * 0.78);
      const descent = Math.ceil(metrics.actualBoundingBoxDescent || resolvedSize * 0.22);
      const padding = Math.max(12, Math.ceil(resolvedSize * 0.08));

      offscreen.width  = Math.max(1, left + right) + padding * 2;
      offscreen.height = Math.max(1, ascent + descent) + padding * 2;

      offCtx.clearRect(0, 0, offscreen.width, offscreen.height);
      offCtx.font          = font;
      offCtx.textAlign     = 'left';
      offCtx.textBaseline  = 'alphabetic';
      offCtx.fillStyle     = '#ffffff';
      offCtx.fillText(content, padding - left, padding + ascent);

      const imageData = offCtx.getImageData(0, 0, offscreen.width, offscreen.height);
      const targets: { x: number; y: number; alpha: number }[] = [];
      const step = Math.max(2, Math.floor(density));

      for (let y = 0; y < offscreen.height; y += step) {
        for (let x = 0; x < offscreen.width; x += step) {
          const alpha = imageData.data[(y * offscreen.width + x) * 4 + 3];
          if (alpha > 40) {
            targets.push({
              x: width  / 2 - offscreen.width  / 2 + x,
              y: height / 2 - offscreen.height / 2 + y,
              alpha: alpha / 255,
            });
          }
        }
      }

      const maxParticles = Math.max(900, Math.min(5200, Math.floor((width * height) / 90)));
      const stride       = Math.max(1, Math.ceil(targets.length / maxParticles));
      const baseRgb      = hexToRgb(color);
      const highlightRgb = hexToRgb(highlightColor);
      const selected     = targets.filter((_, i) => i % stride === 0);

      particles = selected.map((target, index) => {
        const seed  = ((index * 9301 + 49297) % 233280) / 233280;
        const depth = 0.45 + (((index * 233 + 97) % 1000) / 1000) * 0.9;
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
    };

    const queueSample = () => {
      if (resizeFrame) window.cancelAnimationFrame(resizeFrame);
      resizeFrame = window.requestAnimationFrame(sampleText);
    };

    const handlePointerMove  = (e: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      pointer.x  = e.clientX - rect.left;
      pointer.y  = e.clientY - rect.top;
      pointer.active = true;
    };
    const handlePointerLeave = () => { pointer.active = false; };
    const handlePointerEnter = (e: PointerEvent) => {
      handlePointerMove(e);
      if (trigger === 'hover') startGather(true);
    };
    const handleClick = () => { if (trigger === 'click') startGather(true); };

    const mq = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    const onMqChange = (e: MediaQueryListEvent) => { reducedMotion = e.matches; sampleText(); };
    mq?.addEventListener('change', onMqChange);

    canvas.addEventListener('pointerenter', handlePointerEnter);
    canvas.addEventListener('pointermove',  handlePointerMove);
    canvas.addEventListener('pointerleave', handlePointerLeave);
    canvas.addEventListener('click',        handleClick);

    const ro = new ResizeObserver(queueSample);
    ro.observe(container);
    sampleText();

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
