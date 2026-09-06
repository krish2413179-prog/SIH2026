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
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const globeRef = useRef<any>(null);
  const phiRef = useRef(0);
  const thetaRef = useRef(0.3);
  const isDragging = useRef(false);
  const lastX = useRef(0);
  const lastY = useRef(0);

  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    isDragging.current = true;
    lastX.current = e.clientX;
    lastY.current = e.clientY;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }, []);

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!isDragging.current) return;
    phiRef.current += (e.clientX - lastX.current) / 200;
    thetaRef.current = Math.max(-0.8, Math.min(0.8, thetaRef.current + (e.clientY - lastY.current) / 200));
    lastX.current = e.clientX;
    lastY.current = e.clientY;
  }, []);

  const handlePointerUp = useCallback(() => {
    isDragging.current = false;
  }, []);

  useEffect(() => {
  // Delay initialization until we know the canvas has a non‑zero size.
  // This avoids WebGL errors when the canvas is rendered with width/height = 0.
  let initId: number | null = null;
  const initGlobe = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const size = canvas.offsetWidth;
    if (size === 0) {
      // Canvas not sized yet – try again on the next animation frame.
      initId = requestAnimationFrame(initGlobe);
      return;
    }
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    globeRef.current = createGlobe(canvas, {
      devicePixelRatio: dpr,
      width: size * dpr,
      height: size * dpr,
      phi: phiRef.current,
      theta: thetaRef.current,
      dark: 1,
      diffuse: 1.4,
      mapSamples: 16000,
      mapBrightness: 8,
      baseColor: [0.15, 0.15, 0.15],
      markers: MARKERS,
      markerColor: [1.0, 1.0, 1.0],
      glowColor: [0.6, 0.6, 0.6],
      arcColor: [1.0, 1.0, 1.0],
      arcWidth: 1.8,
      arcHeight: 0.4,
      arcs: ARCS,
      onRender: (state) => {
        if (!isDragging.current) phiRef.current += 0.003;
        state.phi = phiRef.current;
        state.theta = thetaRef.current;
      },
    });
  };
  initGlobe();

  return () => {
    if (initId !== null) cancelAnimationFrame(initId);
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
