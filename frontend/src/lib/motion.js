/*
  Shared motion constants.

  DESIGN.md section 6 fixes the physics for the whole product: spring defaults
  of stiffness 100 / damping 20, a 30ms stagger cascade, and a 180ms cross-fade.
  They live here so no component invents its own timing.
*/

/** The one spring in the product. Every interactive transition uses it. */
export const SPRING = { type: 'spring', stiffness: 100, damping: 20 };

/** Lists mount on a 30ms cascade. Capped so long lists do not crawl. */
export const STAGGER_STEP = 0.03;
export const STAGGER_CAP = 16;

export function staggerDelay(index) {
  return Math.min(index, STAGGER_CAP) * STAGGER_STEP;
}

/**
 * Viewport options for scroll-triggered reveals.
 *
 * `once: true` because a safety dashboard should not re-perform every time the
 * reader scrolls back up. `amount` is low so tall sections trigger as soon as
 * their top edge is comfortably in view rather than waiting to be centred.
 */
export const VIEWPORT = { once: true, amount: 0.2 };

/** Distance a revealing element travels. Small: this is settling, not entering. */
export const REVEAL_Y = 14;
