import { useEffect, useRef } from 'react';
import {
  useSpring,
  useMotionValueEvent,
  useInView,
  useReducedMotion,
} from 'motion/react';
import { SPRING } from '../../lib/motion.js';

/*
  A figure that settles into its value when it scrolls into view, using
  Motion's `useSpring` motion value driven by `useInView` (motion.dev
  "useSpring: direct control"). The spring writes straight to textContent via
  `useMotionValueEvent`, so counting never re-renders the React tree.

  Two deliberate constraints for a product that reports casualty figures:

  1. The element renders its true value on first paint. It is never blank and
     never starts life showing a wrong number.
  2. A safety timeout writes the true value regardless of what the animation
     did. A figure frozen part way through a count is a wrong figure, and on
     this subject a wrong figure is worse than no animation at all.
*/
export default function CountUp({
  value,
  format = (v) => Math.round(v).toLocaleString('en-IN'),
  className,
  duration = 1200,
}) {
  const ref = useRef(null);
  const reduce = useReducedMotion();
  const inView = useInView(ref, { once: true, amount: 0.6 });
  const spring = useSpring(value, { ...SPRING, restDelta: 0.4 });

  useMotionValueEvent(spring, 'change', (v) => {
    if (ref.current) ref.current.textContent = format(v);
  });

  useEffect(() => {
    if (!inView) return undefined;

    if (reduce) {
      spring.jump(value);
      return undefined;
    }

    // Drop to zero without animating, then spring up to the real figure.
    spring.jump(0);
    spring.set(value);

    const settle = setTimeout(() => {
      if (ref.current) ref.current.textContent = format(value);
    }, duration);

    return () => clearTimeout(settle);
  }, [inView, value, reduce, spring, format, duration]);

  return (
    <span ref={ref} className={className}>
      {format(value)}
    </span>
  );
}
