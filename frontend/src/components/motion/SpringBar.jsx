import { motion, useReducedMotion } from 'motion/react';
import { SPRING, VIEWPORT, staggerDelay } from '../../lib/motion.js';

/*
  A proportion bar that grows into place when scrolled into view.

  The bar is laid out at its final width and animated with `scaleX` from a left
  origin, never by animating `width`. DESIGN.md section 6 restricts animation to
  transform and opacity, and width would force layout on every frame.

  The numeric value always sits beside the bar in the markup, so the bar carries
  no information the reader would lose if it never animated.
*/
export default function SpringBar({ percent, index = 0, className, style }) {
  const reduce = useReducedMotion();

  return (
    <motion.span
      className={className}
      style={{ width: `${percent}%`, transformOrigin: 'left center', ...style }}
      initial={reduce ? false : { scaleX: 0 }}
      whileInView={{ scaleX: 1 }}
      viewport={VIEWPORT}
      transition={{ ...SPRING, delay: reduce ? 0 : staggerDelay(index) }}
    />
  );
}
