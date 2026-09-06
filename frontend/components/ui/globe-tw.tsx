'use client';

import { useEffect, useRef, useCallback } from 'react';
import createGlobe, { type COBEOptions } from 'cobe';

const MARKERS: COBEOptions['markers'] = [
  { location: [40.7128,  -74.006  ], size: 0.08 }, // New York
  { location: [51.5074,  -0.1278  ], size: 0.07 }, // London
  { location: [1.3521,   103.8198 ], size: 0.07 }, // Singapore
  { location: [35.6762,  139.6503 ], size: 0.06 }, // Tokyo
  { location: [25.2048,  55.2708  ], size: 0.06 }, // Dubai
  { location: [37.7749, -122.4194 ], size: 0.07 }, // San Francisco
  { location: [48.8566,  2.3522   ], size: 0.05 }, // Paris
  { location: [-23.5505,-46.6333  ], size: 0.05 }, // São Paulo
  { location: [22.3193,  114.1694 ], size: 0.07 }, // Hong Kong
];

const ARCS: COBEOptions['arcs'] = [
  { from: [40.7128, -74.006 ],  to: [51.5074,  -0.1278 ]  }, // NY → London
  { from: [51.5074,  -0.1278],  to: [1.3521,   103.8198]  }, // London → Singapore
  { from: [1.3521,  103.8198],  to: [35.6762,  139.6503]  }, // Singapore → Tokyo
  { from: [37.7749,-122.4194],  to: [22.3193,  114.1694]  }, // SF → Hong Kong
  { from: [40.7128, -74.006 ],  to: [25.2048,  55.2708 ]  }, // NY → Dubai
  { from: [48.8566,  2.3522 ],  to: [25.2048,  55.2708 ]  }, // Paris → Dubai
];

export default function Globe({ className = '' }: { className?: string }) {
  const canvasRef  = useRef<HTMLCanvasElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const globeRef   = useRef<any>(null);
  const rafRef     = useRef<number>(0);
  const phiRef     = useRef(0);
  const thetaRef   = useRef(0.3);
  const isDragging = useRef(false);
  const lastX      = useRef(0);
  const lastY      = useRef(0);

  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    isDragging.current = true;
    lastX.current = e.clientX;
    lastY.current = e.clientY;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }, []);

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!isDragging.current) return;
    phiRef.current   += (e.clientX - lastX.current) / 200;
    thetaRef.current  = Math.max(-0.8, Math.min(0.8, thetaRef.current + (e.clientY - lastY.current) / 200));
    lastX.current = e.clientX;
    lastY.current = e.clientY;
  }, []);

  const handlePointerUp = useCallback(() => { isDragging.current = false; }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const size = canvas.offsetWidth;
    const dpr  = Math.min(window.devicePixelRatio || 1, 2);

    globeRef.current = createGlobe(canvas, {
      devicePixelRatio: dpr,
      width:            size * dpr,
      height:           size * dpr,
      phi:              0,
      theta:            0.3,
      dark:             1,
      diffuse:          1.4,
      mapSamples:       16000,
      mapBrightness:    8,
      baseColor:        [0.15, 0.15, 0.15],  // dark gray ocean
      markerColor:      [1.0,  1.0,  1.0 ],  // white markers
      glowColor:        [0.6,  0.6,  0.6 ],  // soft white glow
      arcColor:         [1.0,  1.0,  1.0 ],  // white arcs
      arcWidth:         1.8,
      arcHeight:        0.4,
      markers:          MARKERS,
      arcs:             ARCS,
    });

    const tick = () => {
      if (!isDragging.current) phiRef.current += 0.003;
      globeRef.current?.update({
        phi:   phiRef.current,
        theta: thetaRef.current,
      });
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(rafRef.current);
      globeRef.current?.destroy();
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      className={`cursor-grab active:cursor-grabbing ${className}`}
      style={{ width: '100%', height: '100%', aspectRatio: '1' }}
    />
  );
}
