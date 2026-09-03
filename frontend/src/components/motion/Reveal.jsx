import { motion, useReducedMotion } from 'motion/react';
import { SPRING, VIEWPORT, REVEAL_Y, staggerDelay } from '../../lib/motion.js';

/*
  Scroll-triggered reveal, following Motion's `whileInView` + `viewport.once`
  pattern (motion.dev "Animate once on scroll"). Motion drives these through a
  pooled IntersectionObserver, so adding one per section is cheap.

  Deliberately restrained: opacity plus a 14px settle, nothing else. DESIGN.md
  puts this product at motion level 4, and bans cinematic scroll choreography.
  Data settles into place, it does not perform.
*/
export default function Reveal({
  children,
  as = 'div',
  index,
  delay = 0,
  className,
  ...rest
}) {
  const reduce = useReducedMotion();
  const Tag = motion[as] ?? motion.div;

  const totalDelay = index === undefined ? delay : delay + staggerDelay(index);

  return (
    <Tag
      className={className}
      // Under reduced motion the element simply starts where it ends.
      initial={reduce ? false : { opacity: 0, y: REVEAL_Y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={VIEWPORT}
      transition={{ ...SPRING, delay: reduce ? 0 : totalDelay }}
      {...rest}
    >
      {children}
    </Tag>
  );
}
