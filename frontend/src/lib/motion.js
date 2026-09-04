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

/**
 * The 180ms cross-fade, in seconds, as motion's `duration` wants it.
 *
 * Used where a panel's content is replaced but its data is already in memory -
 * switching route, changing a filter - so the swap reads as a change of state
 * rather than a fresh load. It is stated in DESIGN.md section 6 alongside the
 * spring and the stagger, and belongs here with them rather than as a literal
 * at each call site.
 */
export const CROSSFADE = 0.18;
