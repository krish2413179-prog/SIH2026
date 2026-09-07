'use client';

import { useEffect, useRef, useCallback } from 'react';
import createGlobe, { type COBEOptions } from 'cobe';

const MARKERS: NonNullable<COBEOptions['markers']> = [
  { location: [40.7128,  -74.0060 ], size: 0.08, color: [0.2, 0.85, 1.0] }, // New York
  { location: [51.5074,  -0.1278  ], size: 0.07, color: [0.35, 0.7, 1.0] }, // London
  { location: [1.3521,   103.8198 ], size: 0.08, color: [0.2, 0.9, 0.7] },  // Singapore
  { location: [35.6762,  139.6503 ], size: 0.06, color: [0.4, 0.75, 1.0] }, // Tokyo
  { location: [25.2048,  55.2708  ], size: 0.07, color: [1.0, 0.45, 0.35] },// Dubai
  { location: [37.7749,  -122.4194], size: 0.08, color: [0.2, 0.85, 1.0] }, // San Francisco
  { location: [47.3769,  8.5417   ], size: 0.06, color: [0.35, 0.7, 1.0] }, // Zurich
  { location: [50.1109,  8.6821   ], size: 0.05, color: [0.35, 0.7, 1.0] }, // Frankfurt
  { location: [-33.8688, 151.2093 ], size: 0.06, color: [0.2, 0.9, 0.7] },  // Sydney
  { location: [22.3193,  114.1694 ], size: 0.07, color: [0.3, 0.85, 1.0] }, // Hong Kong
  { location: [39.0438,  125.7532 ], size: 0.08, color: [1.0, 0.25, 0.35] },// Threat node
  { location: [55.7558,  37.6173  ], size: 0.07, color: [1.0, 0.4, 0.3] },  // High risk node
];

const ARCS: NonNullable<COBEOptions['arcs']> = [
  { from: [40.7128, -74.0060],  to: [51.5074,  -0.1278],  color: [0.4, 0.65, 1.0] }, // NY → London
  { from: [51.5074,  -0.1278],  to: [1.3521,   103.8198], color: [0.4, 0.65, 1.0] }, // London → Singapore
  { from: [1.3521,  103.8198],  to: [35.6762,  139.6503], color: [0.35, 0.85, 0.9] },// Singapore → Tokyo
  { from: [37.7749,-122.4194],  to: [22.3193,  114.1694], color: [0.4, 0.65, 1.0] }, // SF → Hong Kong
  { from: [40.7128, -74.0060],  to: [25.2048,  55.2708],  color: [0.5, 0.55, 1.0] }, // NY → Dubai
  { from: [47.3769,  8.5417 ],  to: [25.2048,  55.2708],  color: [0.5, 0.55, 1.0] }, // Zurich → Dubai
  { from: [50.1109,  8.6821 ],  to: [1.3521,   103.8198], color: [0.35, 0.75, 1.0] },// Frankfurt → Singapore
  { from: [39.0438, 125.7532],  to: [55.7558,  37.6173],  color: [1.0, 0.35, 0.4] },  // Threat flow
  { from: [55.7558,  37.6173],  to: [25.2048,  55.2708],  color: [1.0, 0.45, 0.3] },  // Laundering route
];

export default function Globe({ className = '' }: { className?: string }) {
  const canvasRef    = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const globeRef     = useRef<any>(null);
  const rafRef       = useRef<number>(0);
  const phiRef       = useRef(0);
  const thetaRef     = useRef(0.25);
  const isDragging   = useRef(false);
  const lastX        = useRef(0);
  const lastY        = useRef(0);

  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    isDragging.current = true;
    lastX.current = e.clientX;
    lastY.current = e.clientY;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }, []);

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!isDragging.current) return;
    phiRef.current   += (e.clientX - lastX.current) / 220;
    thetaRef.current  = Math.max(-0.8, Math.min(0.8, thetaRef.current + (e.clientY - lastY.current) / 220));
    lastX.current = e.clientX;
    lastY.current = e.clientY;
  }, []);

  const handlePointerUp = useCallback(() => {
    isDragging.current = false;
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas) return;

    // Determine initial dimension — fallback to 750 if container is still measuring
    const initialSize = Math.max(
      container?.clientWidth || 0,
      canvas.offsetWidth || 0,
      700
    );

    const dpr = Math.min(window.devicePixelRatio || 1, 2);

    globeRef.current = createGlobe(canvas, {
      devicePixelRatio: dpr,
      width:            initialSize,
      height:           initialSize,
      phi:              0,
      theta:            0.25,
      dark:             1,
      diffuse:          1.2,
      scale:            1.05,
      mapSamples:       18000,
      mapBrightness:    8,
      mapBaseBrightness: 0.05,
      baseColor:        [0.75, 0.85, 1.0],   // luminous cyber landmass dots
      markerColor:      [0.2,  0.85, 1.0],   // cyan markers
      glowColor:        [0.25, 0.35, 0.85],  // electric indigo atmospheric glow
      arcColor:         [0.35, 0.65, 1.0],   // cyber blue arcs
      arcWidth:         2.2,
      arcHeight:        0.35,
      markers:          MARKERS,
      arcs:             ARCS,
    });

    // ResizeObserver ensures canvas updates dynamically whenever the window or container resizes
    let currentWidth = initialSize;
    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const w = Math.round(entry.contentRect.width);
        if (w > 0 && w !== currentWidth && globeRef.current) {
          currentWidth = w;
          globeRef.current.update({
            width:  w,
            height: w,
          });
        }
      }
    });

    if (container) {
      resizeObserver.observe(container);
    }

    // Smooth animation loop
    const tick = () => {
      if (!isDragging.current) {
        phiRef.current += 0.003;
      }
      globeRef.current?.update({
        phi:   phiRef.current,
        theta: thetaRef.current,
      });
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(rafRef.current);
      resizeObserver.disconnect();
      globeRef.current?.destroy();
    };
  }, []);

  return (
    <div
      ref={containerRef}
      className={`relative flex items-center justify-center w-full h-full aspect-square select-none ${className}`}
    >
      <canvas
        ref={canvasRef}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        className="w-full h-full aspect-square cursor-grab active:cursor-grabbing touch-none"
        style={{ width: '100%', height: '100%', aspectRatio: '1 / 1' }}
      />
    </div>
  );
}
