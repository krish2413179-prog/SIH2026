'use client';

import React, {
  Children,
  cloneElement,
  forwardRef,
  isValidElement,
  useEffect,
  useMemo,
  useRef,
} from 'react';
import gsap from 'gsap';
import './CardSwap.css';

// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  customClass?: string;
}

export const Card = forwardRef<HTMLDivElement, CardProps>(
  ({ customClass, className, ...rest }, ref) => (
    <div
      ref={ref}
      {...rest}
      className={['card', customClass, className].filter(Boolean).join(' ')}
    />
  ),
);
Card.displayName = 'Card';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const makeSlot = (i: number, distX: number, distY: number, total: number) => ({
  x:      i * distX,
  y:      -i * distY,
  z:      -i * distX * 1.5,
  zIndex: total - i,
});

const placeNow = (el: HTMLElement, slot: ReturnType<typeof makeSlot>, skew: number) =>
  gsap.set(el, {
    x:             slot.x,
    y:             slot.y,
    z:             slot.z,
    xPercent:      -50,
    yPercent:      -50,
    skewY:         skew,
    transformOrigin: 'center center',
    zIndex:        slot.zIndex,
    force3D:       true,
  });

// ---------------------------------------------------------------------------
// CardSwap
// ---------------------------------------------------------------------------

export interface CardSwapProps {
  width?:           number | string;
  height?:          number | string;
  cardDistance?:    number;
  verticalDistance?: number;
  delay?:           number;
  pauseOnHover?:    boolean;
  onCardClick?:     (idx: number) => void;
  skewAmount?:      number;
  easing?:          'linear' | 'elastic';
  children:         React.ReactNode;
}

const CardSwap = ({
  width            = 500,
  height           = 400,
  cardDistance     = 60,
  verticalDistance = 70,
  delay            = 5000,
  pauseOnHover     = false,
  onCardClick,
  skewAmount       = 6,
  easing           = 'elastic',
  children,
}: CardSwapProps) => {
  const config =
    easing === 'elastic'
      ? { ease: 'elastic.out(0.6,0.9)', durDrop: 2,   durMove: 2,   durReturn: 2,   promoteOverlap: 0.9,  returnDelay: 0.05 }
      : { ease: 'power1.inOut',          durDrop: 0.8, durMove: 0.8, durReturn: 0.8, promoteOverlap: 0.45, returnDelay: 0.2  };

  const childArr = useMemo(() => Children.toArray(children), [children]);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const refs     = useMemo(() => childArr.map(() => React.createRef<any>()), [childArr.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const order    = useRef(Array.from({ length: childArr.length }, (_, i) => i));
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const tlRef    = useRef<any>(null);
  const intervalRef = useRef<number | undefined>(undefined);
  const container   = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const total = refs.length;
    refs.forEach((r, i) => placeNow(r.current, makeSlot(i, cardDistance, verticalDistance, total), skewAmount));

    const swap = () => {
      if (order.current.length < 2) return;
      const [front, ...rest] = order.current;
      const elFront = refs[front].current;
      const tl = gsap.timeline();
      tlRef.current = tl;

      tl.to(elFront, { y: '+=500', duration: config.durDrop, ease: config.ease });
      tl.addLabel('promote', `-=${config.durDrop * config.promoteOverlap}`);

      rest.forEach((idx, i) => {
        const el   = refs[idx].current;
        const slot = makeSlot(i, cardDistance, verticalDistance, refs.length);
        tl.set(el, { zIndex: slot.zIndex }, 'promote');
        tl.to(el, { x: slot.x, y: slot.y, z: slot.z, duration: config.durMove, ease: config.ease }, `promote+=${i * 0.15}`);
      });

      const backSlot = makeSlot(refs.length - 1, cardDistance, verticalDistance, refs.length);
      tl.addLabel('return', `promote+=${config.durMove * config.returnDelay}`);
      tl.call(() => { gsap.set(elFront, { zIndex: backSlot.zIndex }); }, undefined, 'return');
      tl.to(elFront, { x: backSlot.x, y: backSlot.y, z: backSlot.z, duration: config.durReturn, ease: config.ease }, 'return');
      tl.call(() => { order.current = [...rest, front]; });
    };

    swap();
    intervalRef.current = window.setInterval(swap, delay);

    if (pauseOnHover) {
      const node = container.current!;
      const pause  = () => { tlRef.current?.pause(); clearInterval(intervalRef.current); };
      const resume = () => { tlRef.current?.play();  intervalRef.current = window.setInterval(swap, delay); };
      node.addEventListener('mouseenter', pause);
      node.addEventListener('mouseleave', resume);
      return () => {
        node.removeEventListener('mouseenter', pause);
        node.removeEventListener('mouseleave', resume);
        clearInterval(intervalRef.current);
      };
    }

    return () => clearInterval(intervalRef.current);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cardDistance, verticalDistance, delay, pauseOnHover, skewAmount, easing]);

  const rendered = childArr.map((child, i) =>
    isValidElement(child)
      ? cloneElement(child as React.ReactElement, {
          key: i,
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          ref: refs[i] as any,
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          style: { width, height, ...((child.props as any).style ?? {}) },
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          onClick: (e: React.MouseEvent) => { (child.props as any).onClick?.(e); onCardClick?.(i); },
        })
      : child,
  );

  return (
    <div ref={container} className="card-swap-container" style={{ width, height }}>
      {rendered}
    </div>
  );
};

export default CardSwap;
